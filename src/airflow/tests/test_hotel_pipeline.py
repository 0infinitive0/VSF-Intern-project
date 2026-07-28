import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "dags" / "data_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from hotel_pipeline import (  # noqa: E402
    AUTO_APPROVED,
    PENDING_REVIEW,
    DedupeStats,
    LoadStats,
    PhysicalMatchStats,
    ValidationStats,
    assign_physical_hotel_groups,
    build_hotel_embedding_text,
    build_hotel_payload,
    build_grounding_facts,
    compute_amenity_keys,
    compute_price_tier,
    coordinate_distance_m,
    dedupe_hotels,
    group_physical_hotels,
    normalize_accommodation_type,
    normalize_city,
    normalize_country,
    normalize_hotel,
    normalize_name_key,
    normalize_text_list,
    parse_coordinates,
    parse_max_guests,
    parse_room_size_sqm,
    quality_check_hotels,
    score_physical_hotel_pair,
    validate_hotels,
)


def _raw_agoda_hotel(**overrides):
    base = {
        "hotel_id": 111,
        "hotel_name": "Test Agoda Hotel",
        "accommodation_type": "khách sạn",
        "city": "TP. Hồ Chí Minh",
        "country": "Việt Nam",
        "coordinates": "10.77,106.70",
        "star_rating": 4,
        "amenities": ["Wifi"],
        "amenity_groups": None,
        "highlights": None,
        "awards": None,
        "warnings": [],
        "price": 500000,
        "currency": "VND",
        "check_in": "2026-08-01",
        "check_out": "2026-08-02",
        "property_url": "https://www.agoda.com/test/hotel/x.html",
        "scraped_at": "2026-07-22T10:00:00+00:00",
        "rooms_available": True,
        "all_images": [],
        "rooms": [
            {
                "room_id": 999,
                "name": "Deluxe",
                "bed": "1 giường đôi",
                "size": "25 m²",
                "max_occupancy": "Tối đa 2 người lớn",
                "amenity_groups": {"Tiện nghi": ["Điều hòa"]},
                "sold_out": False,
                "price_per_night": 500000,
                "currency": "VND",
                "images": [],
            }
        ],
        "source_platform": "agoda",
    }
    base.update(overrides)
    return base


class ReferenceDataTests(unittest.TestCase):
    def test_country_alias_resolves_to_iso_code(self):
        self.assertEqual(normalize_country("Việt Nam"), "VN")
        self.assertEqual(normalize_country("vietnam"), "VN")

    def test_city_alias_resolves_to_canonical_name(self):
        self.assertEqual(normalize_city("TP. Hồ Chí Minh"), "Hồ Chí Minh")
        self.assertEqual(normalize_city("ho chi minh"), "Hồ Chí Minh")

    def test_accommodation_type_differs_by_source_platform(self):
        self.assertEqual(normalize_accommodation_type("khách sạn", "agoda"), "hotel")
        self.assertEqual(normalize_accommodation_type("apartment", "booking"), "apartment")


class NormalizeParsingTests(unittest.TestCase):
    def test_room_size_extracted_from_free_text(self):
        self.assertEqual(parse_room_size_sqm("25 m²"), 25.0)
        self.assertIsNone(parse_room_size_sqm(None))

    def test_max_guests_differs_by_source_semantics(self):
        # Agoda: text counts adults only.
        self.assertEqual(parse_max_guests("Tối đa 2 người lớn", "agoda"), 2)
        # Booking: plain total-guest number.
        self.assertEqual(parse_max_guests("4", "booking"), 4)
        self.assertIsNone(parse_max_guests(None, "agoda"))


class ValidateHotelsTests(unittest.TestCase):
    def test_missing_hotel_id_is_rejected_not_crashed(self):
        records = [_raw_agoda_hotel(hotel_id=None)]
        validated, stats = validate_hotels(records)
        self.assertEqual(validated, [])
        self.assertEqual(stats.rejected, 1)
        self.assertEqual(stats.valid, 0)

    def test_missing_hotel_name_is_rejected(self):
        records = [_raw_agoda_hotel(hotel_name="")]
        _, stats = validate_hotels(records)
        self.assertEqual(stats.rejected, 1)

    def test_valid_record_passes(self):
        records = [_raw_agoda_hotel()]
        validated, stats = validate_hotels(records)
        self.assertEqual(stats.valid, 1)
        self.assertEqual(len(validated), 1)

    def test_star_rating_out_of_range_is_rejected_before_load(self):
        # hotels.star_rating has a DB CHECK (0-5); must be caught here, not at
        # load time, since load runs the whole batch in one transaction.
        records = [_raw_agoda_hotel(star_rating=7.5)]
        validated, stats = validate_hotels(records)
        self.assertEqual(validated, [])
        self.assertEqual(stats.rejected, 1)

    def test_room_missing_name_is_rejected_before_load(self):
        # rooms.name is NOT NULL; must be caught here for the same reason.
        raw = _raw_agoda_hotel()
        raw["rooms"][0]["name"] = None
        validated, stats = validate_hotels([raw])
        self.assertEqual(validated, [])
        self.assertEqual(stats.rejected, 1)


class NormalizeHotelTests(unittest.TestCase):
    def test_normalize_hotel_maps_to_canonical_flat_shape(self):
        raw = _raw_agoda_hotel()
        record = normalize_hotel(raw)

        self.assertEqual(record["source_platform"], "agoda")
        self.assertEqual(record["source_hotel_id"], 111)
        self.assertEqual(record["destination_name"], "Hồ Chí Minh")
        self.assertEqual(record["country"], "VN")
        self.assertEqual(record["accommodation_type"], "hotel")
        self.assertEqual(record["price_check_in_date"], date(2026, 8, 1))
        self.assertEqual(
            record["scraped_at"],
            datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(record["rooms"]), 1)
        self.assertEqual(record["rooms"][0]["source_room_id"], 999)
        self.assertEqual(record["rooms"][0]["max_guests"], 2)
        self.assertEqual(record["rooms"][0]["room_size_sqm"], 25.0)
        self.assertEqual(len(record["rooms"][0]["prices"]), 1)
        self.assertEqual(record["rooms"][0]["prices"][0]["price"], 500000)

    def test_booking_rooms_available_int_is_coerced_to_bool(self):
        raw = _raw_agoda_hotel(source_platform="booking", rooms_available=3)
        record = normalize_hotel(raw)
        self.assertIs(record["rooms_available"], True)

        raw_zero = _raw_agoda_hotel(source_platform="booking", rooms_available=0)
        record_zero = normalize_hotel(raw_zero)
        self.assertIs(record_zero["rooms_available"], False)


class NameKeyTests(unittest.TestCase):
    def test_strips_stopwords_and_ascii_folds_diacritics(self):
        self.assertEqual(normalize_name_key("Khách Sạn The Grand Hotel"), "grand")

    def test_different_spelling_same_key(self):
        self.assertEqual(normalize_name_key("Vinpearl Resort Nha Trang"), normalize_name_key("Vinpearl Nha Trang Resort"))

    def test_empty_or_stopword_only_returns_none(self):
        self.assertIsNone(normalize_name_key(""))
        self.assertIsNone(normalize_name_key(None))
        self.assertIsNone(normalize_name_key("The Hotel"))


class ParseCoordinatesTests(unittest.TestCase):
    def test_valid_pair_parses_to_floats(self):
        self.assertEqual(parse_coordinates("10.762622, 106.660172"), (10.762622, 106.660172))

    def test_missing_returns_none_pair(self):
        self.assertEqual(parse_coordinates(None), (None, None))
        self.assertEqual(parse_coordinates(""), (None, None))

    def test_malformed_returns_none_pair(self):
        self.assertEqual(parse_coordinates("not-a-coordinate"), (None, None))

    def test_out_of_range_returns_none_pair(self):
        self.assertEqual(parse_coordinates("999,999"), (None, None))


class NormalizeTextListTests(unittest.TestCase):
    def test_dedupes_preserving_first_seen_order(self):
        self.assertEqual(normalize_text_list(["Wifi", "Pool", "Wifi", " Pool "]), ["Wifi", "Pool"])

    def test_drops_empty_and_none_entries(self):
        self.assertEqual(normalize_text_list(["", None, "Wifi"]), ["Wifi"])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(normalize_text_list(None), [])


class PriceTierTests(unittest.TestCase):
    def test_budget_band(self):
        self.assertEqual(compute_price_tier(500_000, "VND"), "budget")

    def test_mid_range_band(self):
        self.assertEqual(compute_price_tier(1_500_000, "VND"), "mid_range")

    def test_luxury_band(self):
        self.assertEqual(compute_price_tier(5_000_000, "VND"), "luxury")

    def test_non_vnd_currency_returns_none(self):
        self.assertIsNone(compute_price_tier(1_500_000, "USD"))

    def test_missing_price_returns_none(self):
        self.assertIsNone(compute_price_tier(None, "VND"))


class AmenityKeysTests(unittest.TestCase):
    def test_ascii_folds_and_dedupes(self):
        self.assertEqual(compute_amenity_keys(["Hồ bơi", "Wifi", "Hồ bơi"]), ["ho_boi", "wifi"])

    def test_caps_at_limit(self):
        amenities = [f"Amenity {i}" for i in range(30)]
        self.assertEqual(len(compute_amenity_keys(amenities, cap=20)), 20)


class BuildHotelEmbeddingTextTests(unittest.TestCase):
    def test_snapshot_for_full_agoda_record(self):
        record = normalize_hotel(_raw_agoda_hotel())
        text = build_hotel_embedding_text(record)
        self.assertEqual(
            text,
            "Hotel: Test Agoda Hotel\n"
            "Destination: Hồ Chí Minh\n"
            "Type: hotel; Stars: 4\n"
            "Amenities: Wifi",
        )

    def test_excludes_volatile_fields(self):
        record = normalize_hotel(_raw_agoda_hotel())
        text = build_hotel_embedding_text(record)
        self.assertNotIn("500000", text)
        self.assertNotIn("agoda.com", text)
        self.assertNotIn("2026-07-22", text)

    def test_missing_description_omits_line_not_crashes(self):
        record = normalize_hotel(_raw_agoda_hotel(source_platform="booking", description=None))
        text = build_hotel_embedding_text(record)
        self.assertNotIn("Description:", text)


class BuildHotelPayloadTests(unittest.TestCase):
    def test_payload_excludes_large_raw_json_fields(self):
        record = normalize_hotel(_raw_agoda_hotel())
        payload = build_hotel_payload(record)
        for noisy_key in ("amenity_groups", "category_scores", "nearby_attractions", "nearby_essentials"):
            self.assertNotIn(noisy_key, payload)

    def test_payload_has_stable_filter_ids(self):
        record = normalize_hotel(_raw_agoda_hotel())
        payload = build_hotel_payload(record)
        self.assertEqual(payload["source_platform"], "agoda")
        self.assertEqual(payload["source_hotel_id"], 111)
        self.assertEqual(payload["price_tier"], "budget")
        self.assertEqual(payload["lat"], 10.77)
        self.assertEqual(payload["lon"], 106.70)


class BuildGroundingFactsTests(unittest.TestCase):
    def test_grounding_facts_cite_exact_source(self):
        record = normalize_hotel(_raw_agoda_hotel())
        facts = build_grounding_facts(record)
        self.assertEqual(facts["source_url"], "https://www.agoda.com/test/hotel/x.html")
        self.assertEqual(facts["lowest_price"], 500000)
        self.assertEqual(facts["scraped_at"], datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc))


class NormalizeHotelCanonicalRetrievalTests(unittest.TestCase):
    def test_canonical_and_retrieval_attached_without_breaking_db_fields(self):
        record = normalize_hotel(_raw_agoda_hotel())
        self.assertEqual(record["canonical"]["name_key"], normalize_name_key("Test Agoda Hotel"))
        self.assertIn("embedding_text", record["retrieval"])
        self.assertIn("payload", record["retrieval"])
        self.assertIn("grounding_facts", record["retrieval"])
        # Existing DB-facing fields are untouched by the additive canonical/retrieval keys.
        self.assertEqual(record["source_hotel_id"], 111)
        self.assertEqual(record["name"], "Test Agoda Hotel")


class QualityCheckVectorMetricsTests(unittest.TestCase):
    def test_report_includes_vector_rag_quality_section(self):
        hotels = [normalize_hotel(_raw_agoda_hotel())]
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path, metrics = quality_check_hotels(
                ValidationStats(total=1, valid=1),
                DedupeStats(),
                PhysicalMatchStats(),
                LoadStats(hotels_upserted=1, rooms_upserted=1, prices_upserted=1),
                hotels,
                tmpdir,
            )
            content = Path(report_path).read_text(encoding="utf-8")
        self.assertIn("## Vector/RAG quality", content)
        self.assertIn("Hotels missing coordinates: 0/1", content)
        self.assertIn("Hotels with empty embedding_text: 0/1", content)
        self.assertEqual(metrics["total"], 1)
        self.assertEqual(metrics["missing_coordinates"], 0)


def _raw_grouping_hotel(**overrides):
    base = {
        "hotel_id": 1,
        "hotel_name": "Vinpearl Resort Nha Trang",
        "accommodation_type": "khách sạn",
        "city": "Nha Trang",
        "country": "Việt Nam",
        "coordinates": "12.238791,109.196749",
        "star_rating": 5,
        "amenities": ["Wifi", "Pool"],
        "amenity_groups": None,
        "highlights": None,
        "awards": None,
        "warnings": [],
        "price": 3000000,
        "currency": "VND",
        "check_in": "2026-08-01",
        "check_out": "2026-08-02",
        "property_url": "https://www.agoda.com/x",
        "scraped_at": "2026-07-22T10:00:00+00:00",
        "rooms_available": True,
        "all_images": ["http://x/1.jpg"],
        "address": "123 Tran Phu Street Nha Trang",
        "review_count": 100,
        "description": "Nice resort",
        "rooms": [],
        "source_platform": "agoda",
    }
    base.update(overrides)
    return base


class PhysicalHotelGroupingTests(unittest.TestCase):
    def test_same_physical_hotel_across_ota_auto_groups_but_both_rows_remain(self):
        agoda = normalize_hotel(_raw_grouping_hotel())
        booking = normalize_hotel(
            _raw_grouping_hotel(source_platform="booking", hotel_id=2, hotel_name="Vinpearl Resort & Spa Nha Trang")
        )

        hotels, stats = assign_physical_hotel_groups([agoda, booking])

        self.assertEqual(len(hotels), 2)  # DB rows are never merged
        self.assertEqual(agoda["canonical"]["group_review_status"], AUTO_APPROVED)
        self.assertEqual(booking["canonical"]["group_review_status"], AUTO_APPROVED)
        self.assertEqual(agoda["canonical"]["canonical_hotel_key"], booking["canonical"]["canonical_hotel_key"])
        self.assertEqual(stats.groups_created, 1)
        self.assertEqual(stats.groups_pending_review, 0)

    def test_dense_city_different_named_hotels_do_not_group(self):
        agoda = normalize_hotel(_raw_grouping_hotel())
        different = normalize_hotel(
            _raw_grouping_hotel(source_platform="booking", hotel_id=3, hotel_name="Muong Thanh Luxury Nha Trang")
        )

        hotels, stats = assign_physical_hotel_groups([agoda, different])

        self.assertIsNone(agoda["canonical"]["canonical_hotel_key"])
        self.assertIsNone(different["canonical"]["canonical_hotel_key"])
        self.assertEqual(agoda["canonical"]["group_review_status"], "ungrouped")
        self.assertEqual(stats.groups_created, 0)

    def test_coordinate_proximity_alone_cannot_create_a_duplicate(self):
        # Same coordinates, completely unrelated names -> never even become a
        # candidate pair (blocking requires a shared name token).
        agoda = normalize_hotel(_raw_grouping_hotel())
        unrelated = normalize_hotel(
            _raw_grouping_hotel(
                source_platform="booking", hotel_id=5, hotel_name="Best Western Premier Havana",
                coordinates="12.238791,109.196749",
            )
        )

        hotels, stats = assign_physical_hotel_groups([agoda, unrelated])

        self.assertEqual(stats.candidate_pairs, 0)
        self.assertIsNone(agoda["canonical"]["canonical_hotel_key"])
        self.assertIsNone(unrelated["canonical"]["canonical_hotel_key"])

    def test_uncertain_score_goes_to_pending_review_not_auto_grouped(self):
        agoda = normalize_hotel(_raw_grouping_hotel())
        uncertain = normalize_hotel(
            _raw_grouping_hotel(
                source_platform="booking", hotel_id=4, hotel_name="Vinpearl Resort Nha Trang",
                coordinates="12.239700,109.197600",  # ~137m away, exact-name override needs <=80m
                review_count=50, description=None, all_images=["http://x/2.jpg"],
            )
        )

        hotels, stats = assign_physical_hotel_groups([agoda, uncertain])

        self.assertEqual(len(hotels), 2)
        self.assertEqual(agoda["canonical"]["group_review_status"], PENDING_REVIEW)
        self.assertEqual(uncertain["canonical"]["group_review_status"], PENDING_REVIEW)
        self.assertIsNotNone(agoda["canonical"]["group_confidence"])
        self.assertGreaterEqual(agoda["canonical"]["group_confidence"], 0.72)
        self.assertLess(agoda["canonical"]["group_confidence"], 0.86)
        self.assertEqual(stats.groups_pending_review, 1)
        self.assertEqual(stats.auto_grouped_pairs, 0)

    def test_grouping_is_idempotent_across_identical_reruns(self):
        def build_batch():
            return [
                normalize_hotel(_raw_grouping_hotel()),
                normalize_hotel(
                    _raw_grouping_hotel(source_platform="booking", hotel_id=2, hotel_name="Vinpearl Resort & Spa Nha Trang")
                ),
            ]

        first_hotels, first_stats = assign_physical_hotel_groups(build_batch())
        second_hotels, second_stats = assign_physical_hotel_groups(build_batch())

        first_keys = [h["canonical"]["canonical_hotel_key"] for h in first_hotels]
        second_keys = [h["canonical"]["canonical_hotel_key"] for h in second_hotels]
        self.assertEqual(first_keys, second_keys)
        self.assertEqual(first_stats.groups_created, second_stats.groups_created)


class DedupeHotelsTests(unittest.TestCase):
    def test_same_natural_key_within_batch_keeps_newest_scraped_at(self):
        older = normalize_hotel(_raw_agoda_hotel(scraped_at="2026-07-20T10:00:00+00:00"))
        newer = normalize_hotel(_raw_agoda_hotel(scraped_at="2026-07-22T10:00:00+00:00"))

        deduped, stats = dedupe_hotels([older, newer])

        self.assertEqual(len(deduped), 1)
        self.assertEqual(stats.hotels_removed, 1)
        self.assertEqual(deduped[0]["scraped_at"], datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc))

    def test_same_physical_hotel_across_ota_sources_is_not_merged(self):
        agoda_hotel = normalize_hotel(_raw_agoda_hotel(source_platform="agoda", hotel_id=1))
        booking_hotel = normalize_hotel(_raw_agoda_hotel(source_platform="booking", hotel_id=1))

        deduped, stats = dedupe_hotels([agoda_hotel, booking_hotel])

        self.assertEqual(len(deduped), 2)
        self.assertEqual(stats.hotels_removed, 0)


class LoadHotelsToDbTests(unittest.TestCase):
    @patch("hotel_pipeline.get_or_create_destination")
    @patch("hotel_pipeline.psycopg2")
    def test_load_upserts_hotel_room_and_price_in_one_transaction(self, psycopg2_mock, get_or_create_mock):
        cursor = MagicMock()
        cursor.fetchone.side_effect = [("hotel-uuid",), ("room-uuid",)]
        psycopg2_mock.connect.return_value.cursor.return_value = cursor
        get_or_create_mock.return_value = "destination-uuid"

        from hotel_pipeline import load_hotels_to_db

        hotel = normalize_hotel(_raw_agoda_hotel())
        stats = load_hotels_to_db([hotel], {"host": "localhost"})

        self.assertEqual(stats.hotels_upserted, 1)
        self.assertEqual(stats.rooms_upserted, 1)
        self.assertEqual(stats.prices_upserted, 1)
        get_or_create_mock.assert_called_once_with("Hồ Chí Minh", "", {"host": "localhost"})
        psycopg2_mock.connect.return_value.commit.assert_called_once()

        insert_calls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("INSERT INTO hotels" in q for q in insert_calls))
        self.assertTrue(any("INSERT INTO rooms" in q for q in insert_calls))
        self.assertTrue(any("INSERT INTO room_prices" in q for q in insert_calls))
        self.assertTrue(any("ON CONFLICT (source_platform, source_hotel_id)" in q for q in insert_calls))

    @patch("hotel_pipeline.get_or_create_destination")
    @patch("hotel_pipeline.psycopg2")
    def test_load_rolls_back_and_reraises_on_error(self, psycopg2_mock, get_or_create_mock):
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("boom")
        psycopg2_mock.connect.return_value.cursor.return_value = cursor
        get_or_create_mock.return_value = "destination-uuid"

        from hotel_pipeline import load_hotels_to_db

        hotel = normalize_hotel(_raw_agoda_hotel())
        with self.assertRaises(RuntimeError):
            load_hotels_to_db([hotel], {"host": "localhost"})

        psycopg2_mock.connect.return_value.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
