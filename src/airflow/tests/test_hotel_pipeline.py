import sys
import unittest
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parents[1] / "dags" / "data_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from hotel_adapters import (  # noqa: E402
    agoda_to_canonical,
    booking_to_canonical,
    detect_source,
)
from hotel_pipeline import (  # noqa: E402
    deduplicate_hotels,
    destination_keys_from_candidates,
    normalize_hotel_candidates,
    summarize_hotel_quality,
    validate_clean_hotel_candidates,
)
from hotel_utils import (  # noqa: E402
    city_slug,
    normalize_accommodation_type,
    normalize_currency,
    normalize_property_name,
    normalize_star_rating,
    package_signature,
    parse_coordinates,
    parse_time_of_day,
    split_coordinate_string,
    stable_uuid,
    strip_url_query,
    token_set_ratio,
)

BOOKING_RECORD = {
    "name": "Alba Hotel",
    "type": "hotel",
    "stars": 3,
    "rating": 9,
    "reviews": 572,
    "price": 30.05,
    "currency": "US",
    "checkInDate": "2026-07-24",
    "checkOutDate": "2026-07-25",
    "checkIn": "Từ 14:00Khách được yêu cầu xuất trình giấy tờ tùy thân",
    "checkOut": "Từ 00:00 đến 12:00",
    "url": "https://www.booking.com/hotel/vn/hue-queen-2.vi.html?checkin=2026-07-24&selected_currency=USD",
    "hotelId": 265476,
    "description": "Alba Hotel nằm ở Huế.",
    "address": {"full": "12 Nguyen Van Cu Street, Huế, Việt Nam", "country": "vn", "city": "Huế"},
    "location": {"lat": "16.461707182968038", "lng": "107.59009957300805"},
    "images": ["https://cf.bstatic.com/a.jpg", "https://cf.bstatic.com/a.jpg"],
    "roomImages": [
        {"largeUrl": "https://cf.bstatic.com/room.jpg", "associatedRoomIds": ["26547603"]},
    ],
    "facilities": [
        {"name": "Great for your stay", "facilities": [{"name": "WiFi miễn phí"}, {"name": "Máy điều hòa"}]},
        {"name": "Bathroom", "facilities": [{"name": "WiFi miễn phí"}]},
    ],
    "rooms": [
        {
            "roomType": "Phòng Deluxe Giường Đôi",
            "id": None,
            "roomsLeft": 2,
            "bedTypes": [{"beds": ["1 giường đôi", "1 giường đôi lớn", ")"]}],
            "facilities": ["35 m²", "Máy điều hòa", "WiFi miễn phí"],
            "options": [
                {"price": 30.05, "currency": "US", "persons": 2, "freeCancellation": True,
                 "cancellationType": "fully_refundable", "hasGeniusDiscount": False},
            ],
        },
        {
            "roomType": "Phòng Alba Executive",
            "id": 26547603,
            "roomsLeft": 1,
            "bedTypes": [{"beds": ["2 giường đơn"]}],
            "facilities": ["Ngắm cảnh"],
            "options": [
                {"price": 43.77, "currency": "US$", "persons": 3, "freeCancellation": False,
                 "cancellationType": None, "hasGeniusDiscount": True},
            ],
        },
    ],
    "timeOfScrapeISO": "2026-07-22T04:56:28.483Z",
}

AGODA_RECORD = {
    "hotel_id": 545120,
    "hotel_name": "Asian Ruby Center Point Hotel",
    "accommodation_type": "Khách sạn",
    "address": "46-48 Mạc Thị Bưởi, Quận 1, Thành Phố Hồ Chí Minh, Việt Nam",
    "city": "Hồ Chí Minh",
    "area_name": "Quận 1",
    "star_rating": 3,
    "review_score": 7.6,
    "review_count": 3832,
    "price": 557628,
    "currency": "VND",
    "check_in": "2026-07-29",
    "check_out": "2026-07-30",
    "check_in_time": "14:00",
    "check_out_time": "12:00",
    "coordinates": "10.77538013458252,106.70466613769531",
    "property_url": "https://www.agoda.com/asian-ruby/hotel/ho-chi-minh-city-vn.html?checkIn=2026-07-29",
    "description": "Khách sạn trung tâm Quận 1.",
    "all_images": ["https://pix8.agoda.net/a.png"],
    "amenities": ["tiếng Việt", "Internet"],
    "amenity_groups": {
        "Ngôn ngữ được sử dụng": ["tiếng Việt"],
        "Truy cập Internet": ["Internet", "WiFi miễn phí"],
    },
    "rooms": [
        {
            "name": "Deluxe Hướng Thành Phố",
            "room_id": 918412173,
            "bed": "1 giường đôi lớn",
            "max_occupancy": "Tối đa 2 người lớn",
            "amenity_groups": {"Phòng tắm": ["Vòi sen", "Máy sấy tóc"]},
            "sold_out": False,
            "price_per_night": 557628,
            "currency": "VND",
            "crossed_out": True,
            "images": ["https://pix8.agoda.net/room.png"],
        },
        {
            "name": "Superior Không Cửa Sổ",
            "room_id": 918412174,
            "bed": None,
            "max_occupancy": "Tối đa 1 người lớn",
            "amenity_groups": {},
            "sold_out": True,
            "price_per_night": 300000,
            "currency": "VND",
            "images": [],
        },
    ],
    "scraped_at": "2026-07-22T04:23:29.489445+00:00",
}


class NormalizationRuleTests(unittest.TestCase):
    def test_currency_aliases_collapse_to_iso_codes(self):
        self.assertEqual(normalize_currency("US"), "USD")
        self.assertEqual(normalize_currency("US$"), "USD")
        self.assertEqual(normalize_currency("VND"), "VND")
        self.assertIsNone(normalize_currency("GBP"))

    def test_city_slug_accepts_both_spellings(self):
        self.assertEqual(city_slug("Hue"), "hue")
        self.assertEqual(city_slug("Huế"), "hue")
        self.assertEqual(city_slug("Ho Chi Minh City"), "ho-chi-minh")
        self.assertEqual(city_slug("Hồ Chí Minh"), "ho-chi-minh")
        self.assertIsNone(city_slug("Bangkok"))

    def test_unrated_properties_become_null_stars(self):
        self.assertIsNone(normalize_star_rating(0))
        self.assertIsNone(normalize_star_rating(None))
        self.assertEqual(normalize_star_rating(3), 3)

    def test_agoda_guest_house_label_maps_to_booking_enum(self):
        self.assertEqual(normalize_accommodation_type("Nhà nghỉ"), "guest_house")
        self.assertEqual(normalize_accommodation_type("guest_house"), "guest_house")
        self.assertEqual(normalize_accommodation_type("Khách sạn"), "hotel")

    def test_coordinates_outside_vietnam_are_dropped(self):
        self.assertEqual(parse_coordinates("16.4617", "107.5900"), (16.4617, 107.59))
        self.assertEqual(parse_coordinates("48.85", "2.35"), (None, None))
        self.assertEqual(split_coordinate_string("10.7753,106.7046"), (10.7753, 106.7046))

    def test_check_in_time_is_pulled_out_of_booking_free_text(self):
        self.assertEqual(parse_time_of_day("Từ 14:00Khách được yêu cầu xuất trình"), "14:00")
        self.assertIsNone(parse_time_of_day(None))

    def test_url_query_is_stripped_for_identity(self):
        self.assertEqual(
            strip_url_query("https://www.booking.com/hotel/vn/x.vi.html?checkin=2026-07-24"),
            "https://www.booking.com/hotel/vn/x.vi.html",
        )

    def test_package_signature_never_returns_null(self):
        self.assertEqual(package_signature([None, ""]), "standard")
        self.assertEqual(package_signature(["genius", "fully_refundable"]), "fully_refundable|genius")

    def test_stable_uuid_is_reproducible(self):
        self.assertEqual(stable_uuid("hotel", "booking", 265476), stable_uuid("hotel", "booking", 265476))
        self.assertNotEqual(stable_uuid("hotel", "booking", 265476), stable_uuid("hotel", "agoda", 265476))


class AdapterTests(unittest.TestCase):
    def test_detect_source_from_file_name(self):
        self.assertEqual(detect_source("dataset_booking-scraper_2026-07-22.json"), "booking")
        self.assertEqual(detect_source("dataset_agoda-hotel-room_2026-07-22.json"), "agoda")
        self.assertIsNone(detect_source("dataset_unknown.json"))

    def test_booking_candidate_shape(self):
        candidate = booking_to_canonical(BOOKING_RECORD)
        self.assertEqual(candidate["source"], "booking")
        self.assertEqual(candidate["source_id"], "265476")
        self.assertEqual(candidate["destination_key"], "hue")
        self.assertEqual(candidate["coordinates"], "16.461707,107.590100")
        self.assertEqual(candidate["check_in_time"], "14:00")
        self.assertEqual(candidate["crawl_profile"], "price")
        # Duplicate facility names across groups collapse to one amenity.
        self.assertEqual(candidate["amenities"], ["WiFi miễn phí", "Máy điều hòa"])
        # Duplicate image URLs collapse too.
        self.assertEqual(candidate["images"], ["https://cf.bstatic.com/a.jpg"])

    def test_booking_room_ids_fall_back_when_the_feed_omits_them(self):
        rooms = booking_to_canonical(BOOKING_RECORD)["rooms"]
        self.assertTrue(rooms[0]["synthetic_room_id"])
        self.assertEqual(rooms[0]["source_room_id"], "h265476-r0")
        self.assertFalse(rooms[1]["synthetic_room_id"])
        self.assertEqual(rooms[1]["source_room_id"], "26547603")

    def test_booking_bed_alternatives_are_not_summed(self):
        rooms = booking_to_canonical(BOOKING_RECORD)["rooms"]
        self.assertEqual(rooms[0]["number_of_beds"], 1)
        self.assertEqual(rooms[0]["bed_type"], "1 giường đôi hoặc 1 giường đôi lớn")

    def test_booking_room_size_is_not_stored_as_a_facility(self):
        rooms = booking_to_canonical(BOOKING_RECORD)["rooms"]
        self.assertNotIn("35 m²", rooms[0]["facilities"])

    def test_booking_prices_normalize_both_currency_tokens(self):
        rooms = booking_to_canonical(BOOKING_RECORD)["rooms"]
        self.assertEqual(rooms[0]["prices"][0]["currency"], "USD")
        self.assertEqual(rooms[1]["prices"][0]["currency"], "USD")
        self.assertEqual(rooms[0]["prices"][0]["package_details"], "fully_refundable|p2")
        self.assertEqual(rooms[1]["prices"][0]["package_details"], "genius|non_refundable|p3")

    def test_booking_options_alike_but_for_the_block_id_stay_separate_prices(self):
        """Rates of one room that differ only by meal plan must survive the load.

        `room_prices` is unique on package_details, so two options sharing a
        label would collapse into a single row and lose the cheaper rate.
        """
        record = {
            **BOOKING_RECORD,
            "rooms": [{
                "roomType": "Phòng Deluxe",
                "id": 26547603,
                "options": [
                    {"price": 86.09, "currency": "US$", "persons": 2, "freeCancellation": False,
                     "cancellationType": "non_refundable", "hasGeniusDiscount": True,
                     "id": "26547603_121937085_0_1_0"},
                    {"price": 95.66, "currency": "US$", "persons": 2, "freeCancellation": False,
                     "cancellationType": "non_refundable", "hasGeniusDiscount": True,
                     "id": "26547603_219117722_0_1_0"},
                ],
            }],
        }
        prices = booking_to_canonical(record)["rooms"][0]["prices"]
        self.assertEqual(len({price["package_details"] for price in prices}), 2)

    def test_booking_room_images_follow_associated_room_ids(self):
        rooms = booking_to_canonical(BOOKING_RECORD)["rooms"]
        self.assertEqual(rooms[1]["images"], ["https://cf.bstatic.com/room.jpg"])

    def test_agoda_candidate_shape(self):
        candidate = agoda_to_canonical(AGODA_RECORD)
        self.assertEqual(candidate["source_id"], "545120")
        self.assertEqual(candidate["destination_key"], "ho-chi-minh")
        self.assertEqual(candidate["accommodation_type"], "hotel")
        self.assertEqual(candidate["area_name"], "Quận 1")
        self.assertEqual(candidate["check_in_time"], "14:00")

    def test_agoda_language_values_are_not_stored_as_amenities(self):
        candidate = agoda_to_canonical(AGODA_RECORD)
        self.assertIn("WiFi miễn phí", candidate["amenities"])
        self.assertNotIn("tiếng Việt", candidate["amenities"])
        self.assertNotIn("Tiếng Anh", candidate["amenities"])

    def test_agoda_sold_out_room_is_kept_without_a_price(self):
        rooms = agoda_to_canonical(AGODA_RECORD)["rooms"]
        self.assertEqual(len(rooms), 2)
        self.assertEqual(len(rooms[0]["prices"]), 1)
        self.assertEqual(rooms[1]["prices"], [])
        self.assertEqual(rooms[0]["max_adults"], 2)


class ValidationTests(unittest.TestCase):
    def test_hotel_without_a_known_city_is_rejected(self):
        candidate = booking_to_canonical({**BOOKING_RECORD, "address": {"city": "Bangkok", "full": "x"}})
        kept, rejects = validate_clean_hotel_candidates([candidate])
        self.assertEqual(kept, [])
        self.assertTrue(rejects[0]["reason"].startswith("missing_required:destination_key"))

    def test_bad_price_drops_the_offer_not_the_hotel(self):
        candidate = agoda_to_canonical(AGODA_RECORD)
        candidate["rooms"][0]["prices"][0]["price"] = 500  # below the VND floor
        kept, rejects = validate_clean_hotel_candidates([candidate])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["rooms"][0]["prices"], [])
        self.assertEqual(kept[0]["crawl_profile"], "metadata")
        self.assertEqual(rejects[0]["reason"], "vnd_price_out_of_range")

    def test_unsupported_currency_is_rejected_rather_than_guessed(self):
        candidate = booking_to_canonical(BOOKING_RECORD)
        candidate["rooms"][0]["prices"][0]["currency"] = None
        _, rejects = validate_clean_hotel_candidates([candidate])
        self.assertEqual(rejects[0]["reason"], "currency_unsupported")

    def test_destination_keys_are_collected_from_candidates(self):
        candidates = [booking_to_canonical(BOOKING_RECORD), agoda_to_canonical(AGODA_RECORD)]
        self.assertEqual(destination_keys_from_candidates(candidates), ["ho-chi-minh", "hue"])


class DeduplicationTests(unittest.TestCase):
    DESTINATIONS = {"hue": "dest-hue", "ho-chi-minh": "dest-hcm"}

    def _normalized(self, candidates):
        kept, _ = validate_clean_hotel_candidates(candidates)
        return normalize_hotel_candidates(kept, self.DESTINATIONS)

    def test_name_normalization_drops_generic_words_and_parentheses(self):
        self.assertEqual(normalize_property_name("Vy Da Hostel (VyDa Backpacker Hostel)"), "vy da")
        self.assertEqual(normalize_property_name("Alba Hotel"), "alba")

    def test_same_property_on_both_otas_merges_into_one_hotel(self):
        booking = booking_to_canonical(BOOKING_RECORD)
        agoda_twin = agoda_to_canonical({
            **AGODA_RECORD,
            "hotel_name": "Alba",
            "city": "Huế",
            "coordinates": "16.461707,107.590100",
            "star_rating": 4,
        })
        merged, review = deduplicate_hotels(self._normalized([booking, agoda_twin]))

        self.assertEqual(len(merged), 1)
        self.assertEqual(review, [])
        record = merged[0]
        self.assertEqual(record["merged_sources"], ["agoda", "booking"])
        self.assertEqual(record["name"], "Alba Hotel")          # Booking wins the name
        self.assertEqual(record["star_rating"], 4)              # Agoda wins the star rating
        self.assertEqual(record["area_name"], "Quận 1")         # only Agoda has it
        self.assertEqual(len(record["source_urls"]), 2)
        self.assertEqual(len(record["source_ids"]), 2)
        # Per-source ratings stay separate; they are never averaged.
        self.assertEqual(record["ratings_by_source"]["booking"]["review_count"], 572)
        self.assertEqual(record["ratings_by_source"]["agoda"]["review_count"], 3832)

    def test_same_chain_across_otas_goes_to_review_instead_of_merging(self):
        agoda_side = agoda_to_canonical({
            **AGODA_RECORD,
            "hotel_id": 55765781,
            "hotel_name": "Grandma Lu's Saigon Signature",
            "coordinates": "10.776000,106.700000",
        })
        booking_side = booking_to_canonical({
            **BOOKING_RECORD,
            "hotelId": 37272417,
            "name": "Grandma Lu's Saigon Japan Town",
            "rooms": [],
            "address": {"full": "18 Thái Văn Lung", "city": "Hồ Chí Minh"},
            "location": {"lat": "10.776200", "lng": "106.700100"},  # ~25 m away
        })
        merged, review = deduplicate_hotels(self._normalized([agoda_side, booking_side]))

        self.assertEqual(len(merged), 2)
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["kind"], "cross_source")
        self.assertLess(review[0]["distance_meters"], 80)

    def test_two_listings_on_one_ota_never_merge_automatically(self):
        """Neighbouring units in one building are separate inventory."""
        first = booking_to_canonical({
            **BOOKING_RECORD,
            "hotelId": 12074518,
            "name": "The Rixx Cozy Apartment at Ben Thanh Tower",
            "rooms": [],
            "location": {"lat": "16.461707", "lng": "107.590100"},
        })
        second = booking_to_canonical({
            **BOOKING_RECORD,
            "hotelId": 8662336,
            "name": "The Rixx Cozy Apartment at Ben Thanh Tower",
            "rooms": [],
            "location": {"lat": "16.461730", "lng": "107.590120"},  # ~3 m away
        })
        merged, review = deduplicate_hotels(self._normalized([first, second]))

        self.assertEqual(len(merged), 2)
        self.assertEqual(review[0]["kind"], "double_listing")

    def test_subset_names_do_not_merge_across_otas(self):
        """"Nicecy" and "Nicecy Ben Thanh" are different hotels of one chain."""
        booking_side = booking_to_canonical({
            **BOOKING_RECORD,
            "hotelId": 111,
            "name": "The Hotel Nicecy",
            "rooms": [],
            "location": {"lat": "16.461707", "lng": "107.590100"},
        })
        agoda_side = agoda_to_canonical({
            **AGODA_RECORD,
            "hotel_id": 222,
            "hotel_name": "Nicecy Ben Thanh Hotel",
            "city": "Huế",
            "coordinates": "16.461730,107.590120",
        })
        merged, _ = deduplicate_hotels(self._normalized([booking_side, agoda_side]))
        self.assertEqual(len(merged), 2)

    def test_identical_record_from_two_files_still_merges(self):
        first = booking_to_canonical(BOOKING_RECORD)
        second = booking_to_canonical(BOOKING_RECORD)
        merged, _ = deduplicate_hotels(self._normalized([first, second]))
        self.assertEqual(len(merged), 1)

    def test_reingesting_the_same_record_is_idempotent(self):
        first = deduplicate_hotels(self._normalized([booking_to_canonical(BOOKING_RECORD)]))[0]
        second = deduplicate_hotels(self._normalized([booking_to_canonical(BOOKING_RECORD)]))[0]
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(
            [room["id"] for room in first[0]["rooms"]],
            [room["id"] for room in second[0]["rooms"]],
        )
        self.assertEqual(
            [price["id"] for room in first[0]["rooms"] for price in room["prices"]],
            [price["id"] for room in second[0]["rooms"] for price in room["prices"]],
        )

    def test_room_and_price_keys_are_rebound_to_the_merged_hotel(self):
        booking = booking_to_canonical(BOOKING_RECORD)
        agoda_twin = agoda_to_canonical({
            **AGODA_RECORD,
            "hotel_name": "Alba",
            "city": "Huế",
            "coordinates": "16.461707,107.590100",
        })
        merged, _ = deduplicate_hotels(self._normalized([booking, agoda_twin]))
        record = merged[0]
        self.assertTrue(all(room["hotel_id"] == record["id"] for room in record["rooms"]))
        self.assertTrue(all(
            price["room_id"] == room["id"]
            for room in record["rooms"]
            for price in room["prices"]
        ))

    def test_token_set_ratio_is_order_insensitive(self):
        self.assertEqual(token_set_ratio("alba hue", "hue alba"), 100.0)
        self.assertLess(token_set_ratio("alba", "white lotus"), 50.0)


class QualityReportTests(unittest.TestCase):
    def test_report_counts_sources_currencies_and_synthetic_rooms(self):
        candidates = [booking_to_canonical(BOOKING_RECORD), agoda_to_canonical(AGODA_RECORD)]
        kept, rejects = validate_clean_hotel_candidates(candidates)
        normalized = normalize_hotel_candidates(kept, {"hue": "dest-hue", "ho-chi-minh": "dest-hcm"})
        merged, review = deduplicate_hotels(normalized)
        report = summarize_hotel_quality(merged, len(candidates), len(rejects), len(review))

        self.assertEqual(report["loaded_hotels"], 2)
        self.assertEqual(report["loaded_rooms"], 4)
        self.assertEqual(report["loaded_room_prices"], 3)
        self.assertEqual(report["currency_counts"], {"USD": 2, "VND": 1})
        self.assertEqual(report["source_counts"], {"agoda": 1, "booking": 1})
        self.assertEqual(report["synthetic_room_ids"], 1)
        self.assertEqual(report["coordinate_coverage_percent"], 100.0)


if __name__ == "__main__":
    unittest.main()
