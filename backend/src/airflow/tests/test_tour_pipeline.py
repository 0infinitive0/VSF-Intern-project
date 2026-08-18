import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "dags" / "data_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from tour_pipeline import (  # noqa: E402
    DedupeStats,
    LoadStats,
    ValidationStats,
    dedupe_tours,
    extract_tours,
    load_tours_to_db,
    normalize_tour,
    normalize_tour_category,
    normalize_tours,
    parse_iso8601_duration_minutes,
    quality_check_tours,
    validate_tours,
)


def _raw_booking_tour(**overrides):
    # Trimmed real Apify actor output shape — see
    # V_OTA/dataset_craw-data-tour-booking_2026-07-27_08-39-49-122.json.
    base = {
        "tour_id": "PRo2nc0TvHBe",
        "name": "Ninh Binh: Hoa Lu, Tam Coc & Mua Cave Day Trip from Hanoi",
        "description": "You will visit the ancient Hoa Lu capital...",
        "tour_url": "https://www.booking.com/attractions/vn/pro2nc0tvhbe.html",
        "city_name": "Hà Nội",
        "country": "Viêt Nam",
        "duration_label": "Thời gian: 10 giờ",
        "duration_iso": "PT10H",
        "itinerary": {"description": None, "duration_iso": "PT10H", "stops": []},
        "taxonomy_type": "Tours",
        "review_score": 4.5,
        "review_count": 586,
        "category_scores": {"facilitiesRating": 4.4, "easyToAccess": 4.5},
        "has_free_cancellation": True,
        "price": 43,
        "currency": "USD",
        "whats_included": ["Tour guide", "Hotel pickup and drop-off"],
        "not_included": ["Beverages", "Gratuities"],
        "highlights": ["service_animals_allowed", "guest_pickup"],
        "restrictions": [],
        "accessibility": ["Accessible to pushchairs/prams"],
        "image_url": "https://r-xx.bstatic.com/xdata/images/xphoto/max1200/134504627.jpg",
        "image_count": 19,
        "all_images": ["https://r-xx.bstatic.com/xdata/images/xphoto/max1200/134504627.jpg"],
        "additional_info": "Not recommended for travelers with spinal injuries",
        "is_bookable": True,
        "scraped_at": "2026-07-27T08:39:44.708495+00:00",
        "source_platform": "booking",
    }
    base.update(overrides)
    return base


class ReferenceDataTests(unittest.TestCase):
    def test_known_taxonomy_maps_to_canonical_category(self):
        self.assertEqual(normalize_tour_category("Tours"), "Tours")
        self.assertEqual(normalize_tour_category("tour du lịch"), "Tours")

    def test_unknown_taxonomy_falls_back_to_stripped_raw(self):
        self.assertEqual(normalize_tour_category(" Food Tours "), "Food Tours")

    def test_empty_returns_none(self):
        self.assertIsNone(normalize_tour_category(None))
        self.assertIsNone(normalize_tour_category(""))


class ExtractToursTests(unittest.TestCase):
    def test_tags_source_platform_and_normalizes_nfc(self):
        records = extract_tours([{"tour_id": "1", "city_name": "Hà Nội"}], "booking")
        self.assertEqual(records[0]["source_platform"], "booking")
        # NFD "Hà" (base + combining grave) must come back NFC-composed.
        self.assertEqual(records[0]["city_name"], "Hà Nội")

    def test_unknown_source_platform_raises(self):
        with self.assertRaises(ValueError):
            extract_tours([{"tour_id": "1"}], "agoda")


class ParseIso8601DurationTests(unittest.TestCase):
    def test_hours_only(self):
        self.assertEqual(parse_iso8601_duration_minutes("PT10H"), 600)

    def test_minutes_only(self):
        self.assertEqual(parse_iso8601_duration_minutes("PT50M"), 50)

    def test_hours_and_minutes(self):
        self.assertEqual(parse_iso8601_duration_minutes("PT2H30M"), 150)

    def test_none_or_empty_returns_none(self):
        self.assertIsNone(parse_iso8601_duration_minutes(None))
        self.assertIsNone(parse_iso8601_duration_minutes(""))

    def test_unparseable_returns_none(self):
        self.assertIsNone(parse_iso8601_duration_minutes("10 hours"))


class ValidateToursTests(unittest.TestCase):
    def test_missing_tour_id_is_rejected_not_crashed(self):
        records = [_raw_booking_tour(tour_id=None)]
        validated, stats = validate_tours(records)
        self.assertEqual(validated, [])
        self.assertEqual(stats.rejected, 1)

    def test_missing_name_is_rejected(self):
        records = [_raw_booking_tour(name="")]
        _, stats = validate_tours(records)
        self.assertEqual(stats.rejected, 1)

    def test_non_numeric_price_is_rejected(self):
        records = [_raw_booking_tour(price="free")]
        _, stats = validate_tours(records)
        self.assertEqual(stats.rejected, 1)

    def test_valid_record_passes(self):
        validated, stats = validate_tours([_raw_booking_tour()])
        self.assertEqual(stats.valid, 1)
        self.assertEqual(len(validated), 1)


class NormalizeTourTests(unittest.TestCase):
    def test_normalize_tour_maps_to_canonical_flat_shape(self):
        record = normalize_tour(_raw_booking_tour())

        self.assertEqual(record["source_platform"], "booking")
        self.assertEqual(record["source_id"], "PRo2nc0TvHBe")
        self.assertEqual(record["category"], "Tours")
        self.assertEqual(record["duration_minutes"], 600)
        self.assertEqual(record["price"], 43)
        self.assertEqual(record["rating"], 4.5)
        self.assertEqual(record["images"], ["https://r-xx.bstatic.com/xdata/images/xphoto/max1200/134504627.jpg"])
        self.assertEqual(record["itinerary_details"], _raw_booking_tour()["itinerary"])
        # No alias configured for "Hà Nội" -> falls back to the raw string (VSF's
        # normalize_city, unlike V_OTA's, does not return None on an unknown city).
        self.assertEqual(record["destination_name"], "Hà Nội")

    def test_normalize_tours_processes_a_batch(self):
        records = normalize_tours([_raw_booking_tour(), _raw_booking_tour(tour_id="other")])
        self.assertEqual(len(records), 2)


class DedupeToursTests(unittest.TestCase):
    def test_same_key_newest_scraped_at_wins(self):
        older = normalize_tour(_raw_booking_tour(scraped_at="2026-07-27T08:00:00+00:00", price=40))
        newer = normalize_tour(_raw_booking_tour(scraped_at="2026-07-27T09:00:00+00:00", price=45))
        deduped, stats = dedupe_tours([older, newer])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(stats.tours_removed, 1)
        self.assertEqual(deduped[0]["price"], 45)

    def test_different_keys_are_not_deduped(self):
        a = normalize_tour(_raw_booking_tour(tour_id="a"))
        b = normalize_tour(_raw_booking_tour(tour_id="b"))
        deduped, stats = dedupe_tours([a, b])
        self.assertEqual(len(deduped), 2)
        self.assertEqual(stats.tours_removed, 0)


class LoadToursToDbTests(unittest.TestCase):
    @patch("tour_pipeline.get_or_create_destination")
    @patch("tour_pipeline.psycopg2")
    def test_load_upserts_and_commits(self, psycopg2_mock, get_or_create_mock):
        cursor = MagicMock()
        cursor.fetchone.return_value = ["tour-uuid"]
        psycopg2_mock.connect.return_value.cursor.return_value = cursor
        get_or_create_mock.return_value = "destination-uuid"

        tour = normalize_tour(_raw_booking_tour())
        stats = load_tours_to_db([tour], {"host": "localhost"})

        self.assertEqual(stats.tours_upserted, 1)
        get_or_create_mock.assert_called_once_with("Hà Nội", "", {"host": "localhost"})
        psycopg2_mock.connect.return_value.commit.assert_called_once()

        insert_calls = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("INSERT INTO tours" in q for q in insert_calls))
        self.assertTrue(any("ON CONFLICT (source_platform, source_id)" in q for q in insert_calls))

    @patch("tour_pipeline.get_or_create_destination")
    @patch("tour_pipeline.psycopg2")
    def test_load_rolls_back_and_reraises_on_error(self, psycopg2_mock, get_or_create_mock):
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("boom")
        psycopg2_mock.connect.return_value.cursor.return_value = cursor
        get_or_create_mock.return_value = "destination-uuid"

        tour = normalize_tour(_raw_booking_tour())
        with self.assertRaises(RuntimeError):
            load_tours_to_db([tour], {"host": "localhost"})

        psycopg2_mock.connect.return_value.rollback.assert_called_once()


class QualityCheckToursTests(unittest.TestCase):
    def test_writes_report_and_flags_missing_destination(self):
        tour = normalize_tour(_raw_booking_tour(city_name=None, price=0))
        with tempfile.TemporaryDirectory() as tmp:
            report_path = quality_check_tours(
                ValidationStats(total=1, valid=1),
                DedupeStats(),
                LoadStats(tours_upserted=1),
                [tour],
                tmp,
            )
            content = Path(report_path).read_text(encoding="utf-8")
        self.assertIn("could not resolve a destination", content)
        self.assertIn("price <= 0", content)


if __name__ == "__main__":
    unittest.main()
