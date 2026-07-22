"""Convert raw OTA dataset records into one canonical hotel candidate shape.

Adapters only reshape. Every decision that needs a rule (currency, city, type,
coordinate validity) is delegated to `hotel_utils`, so adding a third OTA means
writing one function here and nothing else.

Canonical candidate::

    {
      "source", "source_id", "source_url", "canonical_url",
      "name", "description", "accommodation_type", "star_rating",
      "city_raw", "destination_key", "address", "latitude", "longitude",
      "amenities", "images", "rating", "review_count",
      "check_in_time", "check_out_time", "area_name",
      "crawl_profile",            # "price" when the crawl carried offers
      "scraped_at",
      "rooms": [{
          "source_room_id", "synthetic_room_id", "name",
          "max_adults", "max_children", "number_of_beds", "bed_type",
          "facilities", "images",
          "prices": [{
              "price", "currency", "check_in_date", "check_out_date",
              "source_url", "package_details", "available_rooms", "crawled_at",
          }],
      }],
    }
"""

from typing import Any

from hotel_utils import (
    city_slug,
    clean_list,
    clean_text,
    format_coordinates,
    is_amenity_group,
    looks_like_room_size,
    normalize_accommodation_type,
    normalize_currency,
    normalize_star_rating,
    package_signature,
    parse_coordinates,
    parse_first_int,
    parse_time_of_day,
    split_coordinate_string,
    strip_url_query,
)

SUPPORTED_SOURCES = ("booking", "agoda")


def detect_source(file_name: str) -> str | None:
    """Infer the OTA from a dataset file name.

    Explicit routing on purpose: a glob wide enough to catch every dataset also
    feeds Agoda records into the Booking adapter, which fails in confusing ways.
    """
    lowered = file_name.lower()
    for source in SUPPORTED_SOURCES:
        if source in lowered:
            return source
    return None


def to_canonical(record: dict[str, Any], source: str) -> dict[str, Any]:
    """Dispatch a raw record to its adapter."""
    if source == "booking":
        return booking_to_canonical(record)
    if source == "agoda":
        return agoda_to_canonical(record)
    raise ValueError(f"Unsupported source: {source}")


# --- Booking.com ---------------------------------------------------------------


def _booking_amenities(record: dict[str, Any]) -> list[str]:
    """Flatten facilities[].facilities[].name."""
    names = []
    for group in record.get("facilities") or []:
        for facility in (group or {}).get("facilities") or []:
            names.append((facility or {}).get("name"))
    return clean_list(names)


def _booking_room_images(record: dict[str, Any]) -> dict[str, list[str]]:
    """Group hotel-level roomImages by the room they belong to."""
    by_room: dict[str, list[str]] = {}
    for image in record.get("roomImages") or []:
        url = clean_text((image or {}).get("largeUrl") or (image or {}).get("thumbUrl"))
        if not url:
            continue
        for room_id in (image or {}).get("associatedRoomIds") or []:
            by_room.setdefault(str(room_id), []).append(url)
    return by_room


def _booking_bed_summary(room: dict[str, Any]) -> dict[str, Any]:
    """Summarize bedTypes into a label and a bed count.

    Booking lists alternatives, not a set: "1 giường đôi" and "1 giường đôi lớn"
    on the same room mean the guest picks one. Counting the maximum rather than
    the sum avoids inventing beds. Stray punctuation entries such as ")" also
    appear in the feed and are dropped.
    """
    labels = []
    for bed_group in room.get("bedTypes") or []:
        for bed in (bed_group or {}).get("beds") or []:
            text = clean_text(bed)
            if text and any(char.isalnum() for char in text):
                labels.append(text)
    labels = list(dict.fromkeys(labels))
    counts = [parse_first_int(label) or 0 for label in labels]
    return {
        "bed_type": " hoặc ".join(labels) if labels else None,
        "number_of_beds": max(counts) if counts and max(counts) > 0 else None,
    }


def _booking_prices(record: dict[str, Any], room: dict[str, Any]) -> list[dict[str, Any]]:
    """One canonical price per bookable option.

    The package signature has to separate every option of a room, because
    `room_prices` is unique on it: two options that produce the same label
    collapse into one row and the cheaper rate is silently lost. Cancellation
    and Genius alone do not separate them — one room routinely sells the same
    refundable, Genius-eligible rate at several prices for different meal plans
    and occupancies. Booking's own block id is the only field that always
    differs, so it anchors the signature; cancellation and occupancy stay in it
    to keep the stored value legible.
    """
    check_in = clean_text(record.get("checkInDate"))
    check_out = clean_text(record.get("checkOutDate"))
    if not check_in or not check_out:
        return []

    prices = []
    for option in room.get("options") or []:
        option = option or {}
        cancellation = clean_text(option.get("cancellationType"))
        if not cancellation:
            cancellation = "fully_refundable" if option.get("freeCancellation") else "non_refundable"
        persons = parse_first_int(option.get("persons"))
        prices.append({
            "price": option.get("price"),
            "currency": normalize_currency(option.get("currency") or record.get("currency")),
            "check_in_date": check_in,
            "check_out_date": check_out,
            "source_url": clean_text(record.get("url")),
            "package_details": package_signature([
                cancellation,
                "genius" if option.get("hasGeniusDiscount") else None,
                f"p{persons}" if persons else None,
                clean_text(option.get("id")),
            ]),
            "available_rooms": room.get("roomsLeft"),
            "crawled_at": clean_text(record.get("timeOfScrapeISO")),
        })
    return prices


def _booking_rooms(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Build canonical rooms from the bookable `rooms[]` array.

    `roomOfferings` holds a larger catalogue but carries no room names, so it
    cannot populate `rooms.name`; rooms that were not on sale during the crawl
    are therefore not represented.
    """
    images_by_room = _booking_room_images(record)
    hotel_id = record.get("hotelId")
    rooms = []
    for index, room in enumerate(record.get("rooms") or []):
        room = room or {}
        name = clean_text(room.get("roomType"))
        if not name:
            continue

        raw_id = room.get("id")
        synthetic = raw_id in (None, "")
        # Room names repeat inside one hotel, so a name-based fallback collides.
        # Positional ids stay unique but are not stable between crawls.
        room_id = str(raw_id) if not synthetic else f"h{hotel_id}-r{index}"

        facilities = [
            facility for facility in clean_list(room.get("facilities"))
            if not looks_like_room_size(facility)
        ]
        occupancy = [option.get("persons") for option in room.get("options") or [] if (option or {}).get("persons")]

        rooms.append({
            "source_room_id": room_id,
            "synthetic_room_id": synthetic,
            "name": name,
            "max_adults": max(occupancy) if occupancy else parse_first_int(room.get("persons")),
            "max_children": None,
            "bed_type": _booking_bed_summary(room)["bed_type"],
            "number_of_beds": _booking_bed_summary(room)["number_of_beds"],
            "facilities": facilities,
            "images": clean_list(images_by_room.get(str(raw_id))) if not synthetic else [],
            "prices": _booking_prices(record, room),
        })
    return rooms


def booking_to_canonical(record: dict[str, Any]) -> dict[str, Any]:
    """Map one Booking.com dataset record to the canonical candidate."""
    address = record.get("address") or {}
    location = record.get("location") or {}
    latitude, longitude = parse_coordinates(location.get("lat"), location.get("lng"))
    rooms = _booking_rooms(record)
    has_prices = any(room["prices"] for room in rooms)

    return {
        "source": "booking",
        "source_id": clean_text(record.get("hotelId")),
        "source_url": clean_text(record.get("url")),
        "canonical_url": strip_url_query(record.get("url")),
        "name": clean_text(record.get("name")),
        "description": clean_text(record.get("description")),
        "accommodation_type": normalize_accommodation_type(record.get("type")),
        "star_rating": normalize_star_rating(record.get("stars")),
        "city_raw": clean_text(address.get("city")),
        "destination_key": city_slug(address.get("city")),
        "address": clean_text(address.get("full")),
        "latitude": latitude,
        "longitude": longitude,
        "coordinates": format_coordinates(latitude, longitude),
        "amenities": _booking_amenities(record),
        "images": clean_list(record.get("images")),
        "rating": record.get("rating"),
        "review_count": record.get("reviews"),
        "check_in_time": parse_time_of_day(record.get("checkIn")),
        "check_out_time": parse_time_of_day(record.get("checkOut")),
        "area_name": None,
        "crawl_profile": "price" if has_prices else "metadata",
        "scraped_at": clean_text(record.get("timeOfScrapeISO")),
        "rooms": rooms,
    }


# --- Agoda ---------------------------------------------------------------------


def _agoda_amenities(record: dict[str, Any]) -> list[str]:
    """Flatten amenity_groups, skipping groups that do not list facilities.

    The flat `amenities[]` array is ignored because it arrives pre-mixed with
    no group labels. Reading the groups instead is what makes it possible to
    drop the spoken-language group, which otherwise lands in hotel amenities.
    """
    names = []
    for group_name, group_items in (record.get("amenity_groups") or {}).items():
        if not is_amenity_group(group_name):
            continue
        names.extend(group_items or [])
    return clean_list(names)


def _agoda_rooms(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Build canonical rooms; each Agoda room carries a single nightly price."""
    check_in = clean_text(record.get("check_in"))
    check_out = clean_text(record.get("check_out"))
    source_url = clean_text(record.get("property_url"))
    crawled_at = clean_text(record.get("scraped_at"))

    rooms = []
    for index, room in enumerate(record.get("rooms") or []):
        room = room or {}
        name = clean_text(room.get("name"))
        if not name:
            continue

        raw_id = room.get("room_id")
        synthetic = raw_id in (None, "")
        room_id = str(raw_id) if not synthetic else f"h{record.get('hotel_id')}-r{index}"

        facilities = []
        for group_items in (room.get("amenity_groups") or {}).values():
            facilities.extend(group_items or [])

        prices = []
        # A sold-out room still describes a real room type, but it has no price.
        if not room.get("sold_out") and check_in and check_out:
            prices.append({
                "price": room.get("price_per_night"),
                "currency": normalize_currency(room.get("currency") or record.get("currency")),
                "check_in_date": check_in,
                "check_out_date": check_out,
                "source_url": source_url,
                "package_details": package_signature(["discounted" if room.get("crossed_out") else None]),
                "available_rooms": None,
                "crawled_at": crawled_at,
            })

        rooms.append({
            "source_room_id": room_id,
            "synthetic_room_id": synthetic,
            "name": name,
            "max_adults": parse_first_int(room.get("max_occupancy")),
            "max_children": None,
            "bed_type": clean_text(room.get("bed")),
            "number_of_beds": parse_first_int(room.get("bed")),
            "facilities": clean_list(facilities),
            "images": clean_list(room.get("images")),
            "prices": prices,
        })
    return rooms


def agoda_to_canonical(record: dict[str, Any]) -> dict[str, Any]:
    """Map one Agoda dataset record to the canonical candidate."""
    latitude, longitude = split_coordinate_string(record.get("coordinates"))
    rooms = _agoda_rooms(record)
    has_prices = any(room["prices"] for room in rooms)

    return {
        "source": "agoda",
        "source_id": clean_text(record.get("hotel_id")),
        "source_url": clean_text(record.get("property_url")),
        "canonical_url": strip_url_query(record.get("property_url")),
        "name": clean_text(record.get("hotel_name")),
        "description": clean_text(record.get("description")),
        "accommodation_type": normalize_accommodation_type(record.get("accommodation_type")),
        "star_rating": normalize_star_rating(record.get("star_rating")),
        "city_raw": clean_text(record.get("city")),
        "destination_key": city_slug(record.get("city")),
        "address": clean_text(record.get("address")),
        "latitude": latitude,
        "longitude": longitude,
        "coordinates": format_coordinates(latitude, longitude),
        "amenities": _agoda_amenities(record),
        "images": clean_list(record.get("all_images")),
        "rating": record.get("review_score"),
        "review_count": record.get("review_count"),
        # Agoda already publishes structured times; Booking only has free text.
        "check_in_time": parse_time_of_day(record.get("check_in_time")),
        "check_out_time": parse_time_of_day(record.get("check_out_time")),
        "area_name": clean_text(record.get("area_name")),
        "crawl_profile": "price" if has_prices else "metadata",
        "scraped_at": clean_text(record.get("scraped_at")),
        "rooms": rooms,
    }
