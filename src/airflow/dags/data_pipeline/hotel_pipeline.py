"""Seven-stage ingest of Booking.com and Agoda hotel datasets.

Feeds `destinations`, `hotels`, `rooms` and `room_prices`. The attraction DAGs
crawl OTA pages live; this pipeline instead consumes already-exported scraper
datasets, so the extract stage reads files rather than the network.

Stage functions stay pure list-in/list-out to keep them unit-testable; the DAG
owns all file and database IO.
"""

import json
import os
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

try:
    import psycopg2
except ImportError:  # Allows pure transform tests outside the Airflow image.
    psycopg2 = None

from hotel_adapters import SUPPORTED_SOURCES, detect_source, to_canonical
from hotel_utils import (
    clean_list,
    clean_text,
    destination_payload,
    file_digest,
    haversine_meters,
    normalize_property_name,
    stable_uuid,
    token_set_ratio,
    token_sort_ratio,
)

# Duplicate thresholds. Deliberately asymmetric: merging two distinct
# properties destroys data and is hard to undo, while leaving a duplicate pair
# for review costs only a manual check.
AUTO_MERGE_METERS = 80.0
AUTO_MERGE_RATIO = 92.0
REVIEW_METERS = 300.0
REVIEW_RATIO = 80.0
# Same-OTA pairs are never merged automatically, so this only controls how
# noisy the "possible double listing" queue is.
SAME_SOURCE_REVIEW_RATIO = 95.0

# Nightly VND prices outside this band are scraper artefacts, not real offers.
VND_PRICE_RANGE = (100_000.0, 200_000_000.0)
SUPPORTED_CURRENCIES = ("VND", "USD")

REQUIRED_CANDIDATE_FIELDS = ("name", "source_id", "source_url", "destination_key")

# Which source wins per field when the same hotel is sold on both OTAs.
# Booking carries higher coordinate precision and richer surroundings; Agoda
# publishes structured check-in times and a star rating far more often.
FIELD_SOURCE_PRIORITY = {
    "name": ("booking", "agoda"),
    "star_rating": ("agoda", "booking"),
    "coordinates": ("booking", "agoda"),
    "latitude": ("booking", "agoda"),
    "longitude": ("booking", "agoda"),
    "check_in_time": ("agoda", "booking"),
    "check_out_time": ("agoda", "booking"),
    "area_name": ("agoda", "booking"),
    "accommodation_type": ("booking", "agoda"),
}


# --- Stage 1: dataset discovery ------------------------------------------------


def discover_dataset_files(dataset_dir: str, source: str = "both") -> list[dict[str, str]]:
    """List dataset files to ingest, skipping byte-identical re-exports.

    Scrapers are re-downloaded by hand, so the same export routinely lands twice
    under names like "dataset_x.json" and "dataset_x (1).json".
    """
    if source not in {"booking", "agoda", "both"}:
        raise ValueError("source must be 'booking', 'agoda', or 'both'.")
    if not os.path.isdir(dataset_dir):
        raise ValueError(f"Dataset directory does not exist: {dataset_dir}")

    wanted = SUPPORTED_SOURCES if source == "both" else (source,)
    seen_digests: dict[str, str] = {}
    files: list[dict[str, str]] = []

    for file_name in sorted(os.listdir(dataset_dir)):
        if not file_name.endswith(".json"):
            continue
        file_source = detect_source(file_name)
        if file_source is None:
            print(f"[hotels] Skipped file with no recognizable source: {file_name}")
            continue
        if file_source not in wanted:
            continue

        path = os.path.join(dataset_dir, file_name)
        digest = file_digest(path)
        if digest in seen_digests:
            print(f"[hotels] Skipped duplicate of {seen_digests[digest]}: {file_name}")
            continue
        seen_digests[digest] = file_name
        files.append({"path": path, "source": file_source, "digest": digest})

    if not files:
        raise ValueError(f"No {source} dataset files found in {dataset_dir}")
    return files


# --- Stage 2: extract ----------------------------------------------------------


def extract_hotel_candidates(files: Sequence[dict[str, str]]) -> list[dict[str, Any]]:
    """Read dataset files and reshape every record into a canonical candidate."""
    candidates: list[dict[str, Any]] = []
    for entry in files:
        with open(entry["path"], encoding="utf-8") as handle:
            records = json.load(handle)
        for record in records:
            candidate = to_canonical(record, entry["source"])
            candidate["source_file"] = os.path.basename(entry["path"])
            candidates.append(candidate)
    return candidates


# --- Stage 3: validate and clean ----------------------------------------------


def _valid_dates(check_in: str | None, check_out: str | None) -> bool:
    try:
        return date.fromisoformat(str(check_in)) < date.fromisoformat(str(check_out))
    except (TypeError, ValueError):
        return False


def _price_rejection(price: dict[str, Any]) -> str | None:
    """Return the reason this price cannot be trusted, or None when usable."""
    raw_amount = price.get("price")
    try:
        amount = float(raw_amount)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "price_not_numeric"
    if amount <= 0:
        return "price_not_positive"

    currency = price.get("currency")
    if currency not in SUPPORTED_CURRENCIES:
        return "currency_unsupported"
    if currency == "VND" and not VND_PRICE_RANGE[0] <= amount <= VND_PRICE_RANGE[1]:
        return "vnd_price_out_of_range"
    if not _valid_dates(price.get("check_in_date"), price.get("check_out_date")):
        return "invalid_stay_dates"
    if not price.get("source_url"):
        return "missing_price_source_url"
    return None


def validate_clean_hotel_candidates(
    candidates: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split candidates into loadable records and rejects with a reason.

    A bad price drops only that offer, never the hotel: metadata-only crawls are
    a legitimate profile, and discarding the hotel would lose its description,
    amenities and images too.
    """
    kept: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []

    for candidate in candidates:
        missing = [field for field in REQUIRED_CANDIDATE_FIELDS if not candidate.get(field)]
        if missing:
            rejects.append({
                "level": "hotel",
                "reason": f"missing_required:{','.join(missing)}",
                "source": candidate.get("source"),
                "source_id": candidate.get("source_id"),
                "name": candidate.get("name"),
                "city_raw": candidate.get("city_raw"),
                "source_file": candidate.get("source_file"),
            })
            continue

        rooms = []
        for room in candidate.get("rooms") or []:
            prices = []
            for price in room.get("prices") or []:
                reason = _price_rejection(price)
                if reason:
                    rejects.append({
                        "level": "price",
                        "reason": reason,
                        "source": candidate.get("source"),
                        "source_id": candidate.get("source_id"),
                        "room": room.get("name"),
                        "price": price.get("price"),
                        "currency": price.get("currency"),
                        "source_file": candidate.get("source_file"),
                    })
                    continue
                prices.append(price)
            rooms.append({**room, "prices": prices})

        has_prices = any(room["prices"] for room in rooms)
        kept.append({
            **candidate,
            "rooms": rooms,
            "crawl_profile": "price" if has_prices else "metadata",
        })

    return kept, rejects


# --- Stage 4: normalize --------------------------------------------------------


def normalize_hotel_candidates(
    candidates: Iterable[dict[str, Any]],
    destination_ids: dict[str, str],
) -> list[dict[str, Any]]:
    """Attach destination ids and deterministic primary keys."""
    records = []
    for candidate in candidates:
        destination_id = destination_ids.get(candidate["destination_key"])
        if not destination_id:
            raise ValueError(
                f"No destination id prepared for '{candidate['destination_key']}'. "
                "The data_source stage must run before normalize."
            )
        records.append({
            **candidate,
            "id": stable_uuid("hotel", candidate["source"], candidate["source_id"]),
            "destination_id": destination_id,
            "source_urls": [candidate["source_url"]],
            "source_ids": [f"{candidate['source']}:{candidate['source_id']}"],
            "videos": [],
        })
    return records


# --- Stage 5: deduplicate ------------------------------------------------------


def _duplicate_relation(left: dict[str, Any], right: dict[str, Any]) -> str | None:
    """Classify a pair as "merge", "review" or None.

    Geographic matching only ever applies across OTAs. Two different listing
    ids on the *same* OTA are two products that the OTA itself considers
    distinct: neighbouring apartments in one tower, or a chain's separate
    buildings on the same street. Merging those destroys real inventory, so
    within a source only an identical source_id is a duplicate.
    """
    same_source = left["source"] == right["source"]
    if same_source and left["source_id"] == right["source_id"]:
        return "merge"

    left_name = normalize_property_name(left.get("name"))
    right_name = normalize_property_name(right.get("name"))
    if not left_name or not right_name:
        return None

    coords = (left.get("latitude"), left.get("longitude"), right.get("latitude"), right.get("longitude"))
    if any(value is None for value in coords):
        return None
    distance = haversine_meters(*coords)  # type: ignore[arg-type]
    if distance > REVIEW_METERS:
        return None

    # Subset names such as "Nicecy" vs "Nicecy Ben Thanh" score 100 on the
    # set ratio, so the stricter sort ratio decides whether a pair may merge.
    sort_ratio = token_sort_ratio(left_name, right_name)

    if same_source:
        # Near-identical names on one OTA are worth a look as a possible
        # double listing, but never an automatic merge.
        if distance <= AUTO_MERGE_METERS and sort_ratio >= SAME_SOURCE_REVIEW_RATIO:
            return "review"
        return None

    # Chain properties share a prefix but are separate buildings, for example
    # "Grandma Lu's Saigon Signature" and "Grandma Lu's Saigon Japan Town".
    # Their similarity sits right on the review threshold, so whether the pair
    # gets examined must not depend on which side of it the score lands.
    shares_chain_prefix = left_name.split()[0] == right_name.split()[0] and left_name != right_name
    if shares_chain_prefix and distance <= AUTO_MERGE_METERS:
        return "review"

    if distance <= AUTO_MERGE_METERS and sort_ratio >= AUTO_MERGE_RATIO:
        return "merge"
    if token_set_ratio(left_name, right_name) >= REVIEW_RATIO:
        return "review"
    return None


def _pick(records: Sequence[dict[str, Any]], field: str) -> Any:
    """Choose one value for `field` using the declared source priority."""
    priority = FIELD_SOURCE_PRIORITY.get(field, ())
    ordered = sorted(
        records,
        key=lambda record: priority.index(record["source"]) if record["source"] in priority else len(priority),
    )
    for record in ordered:
        if record.get(field) not in (None, "", []):
            return record.get(field)
    return None


def _merge_group(group: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Fold duplicates of one property into a single hotel record.

    Ratings are not averaged or summed: each OTA scores a different review
    population. The winning source's rating is kept as-is and the other is
    preserved only in the audit fields.
    """
    primary = sorted(group, key=lambda record: (record["source"] != "booking", record["source_id"]))[0]
    merged = dict(primary)

    for field in ("name", "star_rating", "coordinates", "latitude", "longitude",
                  "check_in_time", "check_out_time", "area_name", "accommodation_type"):
        merged[field] = _pick(group, field)

    descriptions: list[str] = [str(record["description"]) for record in group if record.get("description")]
    merged["description"] = max(descriptions, key=len) if descriptions else None

    merged["amenities"] = clean_list([value for record in group for value in record.get("amenities") or []])
    merged["images"] = clean_list([value for record in group for value in record.get("images") or []])
    merged["source_urls"] = clean_list([value for record in group for value in record.get("source_urls") or []])
    merged["source_ids"] = clean_list([value for record in group for value in record.get("source_ids") or []])
    merged["rooms"] = [
        {**room, "source": record["source"]}
        for record in group
        for room in record.get("rooms") or []
    ]
    merged["merged_sources"] = sorted({record["source"] for record in group})
    merged["ratings_by_source"] = {
        record["source"]: {"rating": record.get("rating"), "review_count": record.get("review_count")}
        for record in group
    }
    merged["crawl_profile"] = "price" if any(
        record.get("crawl_profile") == "price" for record in group
    ) else "metadata"
    return merged


def _assign_child_ids(record: dict[str, Any]) -> dict[str, Any]:
    """Derive room and price keys from the final (post-merge) hotel id."""
    rooms = []
    for room in record.get("rooms") or []:
        room_id = stable_uuid("room", record["id"], room.get("source", record["source"]), room["source_room_id"])
        prices = [
            {
                **price,
                "id": stable_uuid(
                    "price",
                    room_id,
                    price["check_in_date"],
                    price["check_out_date"],
                    price["source_url"],
                    price["package_details"],
                ),
                "room_id": room_id,
            }
            for price in room.get("prices") or []
        ]
        rooms.append({**room, "id": room_id, "hotel_id": record["id"], "prices": prices})
    return {**record, "rooms": rooms}


def deduplicate_hotels(
    records: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge duplicates and report the pairs that need a human decision.

    Grouping is single-pass union-find over candidate pairs, restricted to
    hotels of the same destination so the comparison stays linear per city.
    """
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_destination: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        by_destination.setdefault(record["destination_id"], []).append(index)

    review_pairs: list[dict[str, Any]] = []
    for indexes in by_destination.values():
        for position, left_index in enumerate(indexes):
            for right_index in indexes[position + 1:]:
                relation = _duplicate_relation(records[left_index], records[right_index])
                if relation == "merge":
                    union(left_index, right_index)
                elif relation == "review":
                    left_record, right_record = records[left_index], records[right_index]
                    left_name = normalize_property_name(left_record.get("name"))
                    right_name = normalize_property_name(right_record.get("name"))
                    review_pairs.append({
                        "kind": "double_listing" if left_record["source"] == right_record["source"]
                                else "cross_source",
                        "left": f"{left_record['source']}:{left_record['source_id']}",
                        "left_name": left_record.get("name"),
                        "right": f"{right_record['source']}:{right_record['source_id']}",
                        "right_name": right_record.get("name"),
                        "distance_meters": round(haversine_meters(
                            left_record["latitude"], left_record["longitude"],
                            right_record["latitude"], right_record["longitude"],
                        ), 1),
                        "name_set_ratio": token_set_ratio(left_name, right_name),
                        "name_sort_ratio": token_sort_ratio(left_name, right_name),
                    })

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        groups.setdefault(find(index), []).append(record)

    merged = [_assign_child_ids(_merge_group(group)) for group in groups.values()]
    merged.sort(key=lambda record: (record["destination_id"], record["name"] or ""))
    return merged, review_pairs


# --- Stage 6: load -------------------------------------------------------------

HOTEL_UPSERT = """
    INSERT INTO hotels (
        id, destination_id, name, description, star_rating, amenities,
        coordinates, images, videos, source_urls, source_ids
    ) VALUES (
        %(id)s, %(destination_id)s, %(name)s, %(description)s, %(star_rating)s, %(amenities)s,
        %(coordinates)s, %(images)s, %(videos)s, %(source_urls)s, %(source_ids)s
    )
    ON CONFLICT (id) DO UPDATE SET
        destination_id = EXCLUDED.destination_id,
        name = EXCLUDED.name,
        description = EXCLUDED.description,
        star_rating = EXCLUDED.star_rating,
        amenities = EXCLUDED.amenities,
        coordinates = EXCLUDED.coordinates,
        images = EXCLUDED.images,
        videos = EXCLUDED.videos,
        source_urls = EXCLUDED.source_urls,
        source_ids = EXCLUDED.source_ids,
        updated_at = CURRENT_TIMESTAMP;
"""

ROOM_UPSERT = """
    INSERT INTO rooms (
        id, hotel_id, name, max_adults, max_children, number_of_beds,
        bed_type, room_facilities, images
    ) VALUES (
        %(id)s, %(hotel_id)s, %(name)s, %(max_adults)s, %(max_children)s, %(number_of_beds)s,
        %(bed_type)s, %(room_facilities)s, %(images)s
    )
    ON CONFLICT (id) DO UPDATE SET
        hotel_id = EXCLUDED.hotel_id,
        name = EXCLUDED.name,
        max_adults = EXCLUDED.max_adults,
        max_children = EXCLUDED.max_children,
        number_of_beds = EXCLUDED.number_of_beds,
        bed_type = EXCLUDED.bed_type,
        room_facilities = EXCLUDED.room_facilities,
        images = EXCLUDED.images,
        updated_at = CURRENT_TIMESTAMP;
"""

# Matches the UNIQUE(room_id, check_in_date, check_out_date, source_url,
# package_details) constraint. package_details is never NULL by construction:
# PostgreSQL treats NULLs as distinct, which would defeat the upsert.
PRICE_UPSERT = """
    INSERT INTO room_prices (
        id, room_id, price, currency, check_in_date, check_out_date,
        source_url, package_details, available_rooms, crawled_at
    ) VALUES (
        %(id)s, %(room_id)s, %(price)s, %(currency)s, %(check_in_date)s, %(check_out_date)s,
        %(source_url)s, %(package_details)s, %(available_rooms)s, COALESCE(%(crawled_at)s, CURRENT_TIMESTAMP)
    )
    ON CONFLICT (room_id, check_in_date, check_out_date, source_url, package_details) DO UPDATE SET
        price = EXCLUDED.price,
        currency = EXCLUDED.currency,
        available_rooms = EXCLUDED.available_rooms,
        crawled_at = EXCLUDED.crawled_at;
"""


def _hotel_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "destination_id": record["destination_id"],
        "name": record["name"],
        "description": record.get("description"),
        "star_rating": record.get("star_rating"),
        "amenities": record.get("amenities") or [],
        "coordinates": record.get("coordinates"),
        "images": record.get("images") or [],
        "videos": record.get("videos") or [],
        "source_urls": record.get("source_urls") or [],
        "source_ids": record.get("source_ids") or [],
    }


def _room_row(room: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": room["id"],
        "hotel_id": room["hotel_id"],
        "name": room["name"],
        "max_adults": room.get("max_adults"),
        "max_children": room.get("max_children"),
        "number_of_beds": room.get("number_of_beds"),
        "bed_type": room.get("bed_type"),
        "room_facilities": room.get("facilities") or [],
        "images": room.get("images") or [],
    }


def load_hotels_to_db(records: Sequence[dict[str, Any]], db_conn_kwargs: dict[str, str]) -> dict[str, int]:
    """Upsert hotels, rooms and prices inside a single transaction."""
    if not records:
        raise ValueError("No hotel records to load.")

    hotel_rows = [_hotel_row(record) for record in records]
    room_rows = [_room_row(room) for record in records for room in record.get("rooms") or []]
    price_rows = [
        price
        for record in records
        for room in record.get("rooms") or []
        for price in room.get("prices") or []
    ]

    conn = None
    try:
        conn = psycopg2.connect(**db_conn_kwargs)
        cursor = conn.cursor()
        cursor.executemany(HOTEL_UPSERT, hotel_rows)
        if room_rows:
            cursor.executemany(ROOM_UPSERT, room_rows)
        if price_rows:
            cursor.executemany(PRICE_UPSERT, price_rows)
        conn.commit()
    except Exception as error:
        print(f"Database insertion error: {error}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            cursor.close()
            conn.close()

    return {"hotels": len(hotel_rows), "rooms": len(room_rows), "room_prices": len(price_rows)}


def get_or_create_destinations(
    slugs: Iterable[str],
    db_conn_kwargs: dict[str, str],
) -> dict[str, str]:
    """Resolve every destination slug to a stable UUID, creating rows as needed.

    Unlike the attraction DAGs, the destination set comes from the datasets
    themselves rather than a DAG parameter.
    """
    select_query = "SELECT id FROM destinations WHERE name = %s LIMIT 1;"
    insert_query = """
        INSERT INTO destinations (id, name, region, coordinates, description)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING;
    """
    update_query = """
        UPDATE destinations
        SET region = COALESCE(NULLIF(%s, ''), region),
            coordinates = COALESCE(NULLIF(%s, ''), coordinates),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
    """

    resolved: dict[str, str] = {}
    conn = None
    try:
        conn = psycopg2.connect(**db_conn_kwargs)
        cursor = conn.cursor()
        for slug in sorted(set(slugs)):
            meta = destination_payload(slug)
            cursor.execute(select_query, (meta["name"],))
            existing = cursor.fetchone()
            if existing:
                cursor.execute(update_query, (meta["region"], meta["coordinates"], existing[0]))
                resolved[slug] = str(existing[0])
                continue
            destination_id = stable_uuid("destination", slug)
            cursor.execute(insert_query, (
                destination_id,
                meta["name"],
                meta["region"],
                meta["coordinates"],
                f"Điểm đến du lịch {meta['name']}, Việt Nam.",
            ))
            resolved[slug] = destination_id
        conn.commit()
    except Exception as error:
        print(f"Database error in get_or_create_destinations: {error}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            cursor.close()
            conn.close()
    return resolved


# --- Stage 7: quality check ----------------------------------------------------


def summarize_hotel_quality(
    records: Sequence[dict[str, Any]],
    extracted_count: int = 0,
    reject_count: int = 0,
    review_pair_count: int = 0,
) -> dict[str, Any]:
    """Deterministic coverage metrics for the loaded hotel records."""
    total = len(records)
    rooms = [room for record in records for room in record.get("rooms") or []]
    prices = [price for room in rooms for price in room.get("prices") or []]

    def coverage(matches: int, denominator: int) -> float:
        return round((matches / denominator) * 100, 1) if denominator else 0.0

    return {
        "extracted_records": extracted_count or total,
        "loaded_hotels": total,
        "loaded_rooms": len(rooms),
        "loaded_room_prices": len(prices),
        "rejected_records": reject_count,
        "reject_rate_percent": coverage(reject_count, (extracted_count or total) + reject_count),
        "merge_review_pairs": review_pair_count,
        "cross_source_hotels": sum(len(record.get("merged_sources") or []) > 1 for record in records),
        "description_coverage_percent": coverage(sum(bool(r.get("description")) for r in records), total),
        "coordinate_coverage_percent": coverage(sum(bool(r.get("coordinates")) for r in records), total),
        "star_rating_coverage_percent": coverage(sum(r.get("star_rating") is not None for r in records), total),
        "image_coverage_percent": coverage(sum(bool(r.get("images")) for r in records), total),
        "synthetic_room_ids": sum(bool(room.get("synthetic_room_id")) for room in rooms),
        "currency_counts": dict(sorted(Counter(str(price.get("currency")) for price in prices).items())),
        "source_counts": dict(sorted(Counter(
            source for record in records for source in record.get("merged_sources") or [record["source"]]
        ).items())),
        "crawl_profile_counts": dict(sorted(Counter(
            str(record.get("crawl_profile")) for record in records
        ).items())),
    }


def write_jsonl(path: str, rows: Iterable[dict[str, Any]]) -> int:
    """Persist stage output next to the run instead of pushing it through XCom.

    A 1000-hotel export with images and offers is far past what the XCom
    metadata backend should carry, so stages exchange file paths.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def read_jsonl(path: str) -> list[dict[str, Any]]:
    """Read a stage output file back."""
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def collect_hotel_records(
    dataset_dir: str,
    destination_ids: dict[str, str],
    source: str = "both",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Run every in-memory stage. Convenience entry point for tests and CLI use.

    `destination_ids` maps slug -> UUID; pass the result of
    `get_or_create_destinations` when running against a real database.
    """
    files = discover_dataset_files(dataset_dir, source)
    candidates = extract_hotel_candidates(files)
    clean, rejects = validate_clean_hotel_candidates(candidates)
    normalized = normalize_hotel_candidates(clean, destination_ids)
    merged, review_pairs = deduplicate_hotels(normalized)
    return merged, rejects, review_pairs


def destination_keys_from_candidates(candidates: Iterable[dict[str, Any]]) -> list[str]:
    """Collect the distinct destination slugs referenced by extracted candidates.

    Derived after extraction rather than up front so the datasets are parsed
    once; these files run to tens of megabytes each.
    """
    keys = set()
    unknown: Counter = Counter()
    for candidate in candidates:
        if candidate.get("destination_key"):
            keys.add(candidate["destination_key"])
        else:
            unknown[clean_text(candidate.get("city_raw")) or "<empty>"] += 1
    if unknown:
        # Loud on purpose: a new city spelling must be added to CITY_ALIASES
        # rather than silently loading hotels without a destination.
        print(f"[hotels] Unmapped city values: {dict(unknown)}")
    if not keys:
        raise ValueError("No dataset record mapped to a known destination.")
    return sorted(keys)
