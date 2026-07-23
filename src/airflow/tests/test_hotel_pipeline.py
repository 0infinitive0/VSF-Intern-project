import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "dags" / "data_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from hotel_pipeline import (  # noqa: E402
    dedupe_hotels,
    normalize_accommodation_type,
    normalize_city,
    normalize_country,
    normalize_hotel,
    parse_max_guests,
    parse_room_size_sqm,
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
