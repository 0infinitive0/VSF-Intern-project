import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_DIR = Path(__file__).resolve().parents[1] / "dags" / "data_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))
sys.path.insert(0, str(REPO_ROOT))

from hotel_pipeline import (  # noqa: E402
    AUTO_APPROVED,
    PENDING_REVIEW,
    assign_physical_hotel_groups,
    normalize_hotel,
)
from src.services.hotel_retrieval import render_hotel_search_results  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hotel_golden_corpus.json"


def _load_golden_corpus():
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


class GoldenCorpusDedupeGroupingTests(unittest.TestCase):
    """Real Agoda/Booking records (trimmed) — see fixtures/hotel_golden_corpus.json.
    Phase 4 success criteria: golden duplicate pairs group; golden non-duplicate
    near-miss pairs stay separate."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = _load_golden_corpus()

    def test_known_duplicate_pairs_from_real_data_auto_group(self):
        for agoda_raw, booking_raw in self.corpus["duplicate_pairs"]:
            with self.subTest(name=agoda_raw["hotel_name"]):
                agoda = normalize_hotel(agoda_raw)
                booking = normalize_hotel(booking_raw)

                hotels, stats = assign_physical_hotel_groups([agoda, booking])

                self.assertEqual(len(hotels), 2, "both OTA rows must survive")
                self.assertEqual(agoda["canonical"]["group_review_status"], AUTO_APPROVED)
                self.assertEqual(
                    agoda["canonical"]["canonical_hotel_key"],
                    booking["canonical"]["canonical_hotel_key"],
                )

    def test_known_non_duplicate_near_miss_stays_separate(self):
        # These two happen to both mention "Saigon" (a colloquial area name,
        # not the canonical destination_name "Hồ Chí Minh"), so blocking still
        # produces a candidate pair — but the name/address/star mismatch keeps
        # the score well under the 0.72 review floor, so they never group.
        raw_a, raw_b = self.corpus["non_duplicate_near_miss"]
        hotel_a = normalize_hotel(raw_a)
        hotel_b = normalize_hotel(raw_b)

        hotels, stats = assign_physical_hotel_groups([hotel_a, hotel_b])

        self.assertEqual(stats.groups_created, 0)
        self.assertIsNone(hotel_a["canonical"]["canonical_hotel_key"])
        self.assertIsNone(hotel_b["canonical"]["canonical_hotel_key"])


class EmbeddingTextGoldenSnapshotTests(unittest.TestCase):
    def test_embedding_text_is_non_empty_for_every_golden_hotel(self):
        corpus = _load_golden_corpus()
        raws = [h for pair in corpus["duplicate_pairs"] for h in pair] + corpus["non_duplicate_near_miss"]
        for raw in raws:
            with self.subTest(name=raw["hotel_name"]):
                hotel = normalize_hotel(raw)
                text = hotel["retrieval"]["embedding_text"]
                self.assertTrue(text.strip())
                self.assertTrue(text.startswith(f"Hotel: {hotel['name']}"))


class PayloadSizeGateTests(unittest.TestCase):
    def test_payload_for_golden_hotels_stays_small(self):
        # Payload gate (Phase 4): no large/raw JSON blobs leaking into the
        # Qdrant filter payload, even for real, richly-populated records.
        corpus = _load_golden_corpus()
        raws = [h for pair in corpus["duplicate_pairs"] for h in pair] + corpus["non_duplicate_near_miss"]
        for raw in raws:
            with self.subTest(name=raw["hotel_name"]):
                hotel = normalize_hotel(raw)
                payload_bytes = len(json.dumps(hotel["retrieval"]["payload"], default=str))
                self.assertLess(payload_bytes, 2000, "payload must stay small and filter-only")


class RetrievalShapeTests(unittest.TestCase):
    def test_auto_grouped_hotels_collapse_into_one_result_with_multiple_offers(self):
        corpus = _load_golden_corpus()
        agoda_raw, booking_raw = corpus["duplicate_pairs"][0]
        agoda = normalize_hotel(agoda_raw)
        booking = normalize_hotel(booking_raw)
        hotels, _ = assign_physical_hotel_groups([agoda, booking])

        results = render_hotel_search_results(hotels)

        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(len(result["offers"]), 2)
        self.assertEqual(
            {o["source_platform"] for o in result["offers"]},
            {"agoda", "booking"},
        )
        self.assertIn("grounding_facts", result)

    def test_grouped_member_with_missing_scraped_at_does_not_crash_tie_break(self):
        # Regression: the tie-breaker sort key must not compare a naive
        # datetime.min sentinel against an aware scraped_at (TypeError).
        base = {
            "hotel_id": 1, "hotel_name": "Vinpearl Resort Nha Trang", "accommodation_type": "khách sạn",
            "city": "Nha Trang", "country": "Việt Nam", "coordinates": "12.238791,109.196749",
            "star_rating": 5, "amenities": ["Wifi", "Pool"], "warnings": [], "price": 3000000,
            "currency": "VND", "check_in": "2026-08-01", "check_out": "2026-08-02",
            "rooms_available": True, "all_images": ["http://x/1.jpg"],
            "address": "123 Tran Phu Street Nha Trang", "review_count": 100, "description": "Nice",
            "rooms": [],
        }
        agoda = normalize_hotel(
            {**base, "source_platform": "agoda", "property_url": "https://agoda.com/x",
             "scraped_at": "2026-07-22T10:00:00+00:00"}
        )
        booking = normalize_hotel(
            {**base, "hotel_id": 2, "source_platform": "booking", "property_url": "https://booking.com/x",
             "scraped_at": None}
        )
        hotels, _ = assign_physical_hotel_groups([agoda, booking])
        self.assertEqual(agoda["canonical"]["group_review_status"], AUTO_APPROVED)

        results = render_hotel_search_results(hotels)  # must not raise TypeError

        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["offers"]), 2)

    def test_pending_review_group_renders_separately_not_merged(self):
        agoda = normalize_hotel(
            {
                "hotel_id": 1, "hotel_name": "Vinpearl Resort Nha Trang", "accommodation_type": "khách sạn",
                "city": "Nha Trang", "country": "Việt Nam", "coordinates": "12.238791,109.196749",
                "star_rating": 5, "amenities": ["Wifi", "Pool"], "warnings": [], "price": 3000000,
                "currency": "VND", "check_in": "2026-08-01", "check_out": "2026-08-02",
                "property_url": "https://agoda.com/x", "scraped_at": "2026-07-22T10:00:00+00:00",
                "rooms_available": True, "all_images": ["http://x/1.jpg"],
                "address": "123 Tran Phu Street Nha Trang", "review_count": 100, "description": "Nice",
                "rooms": [], "source_platform": "agoda",
            }
        )
        uncertain = normalize_hotel(
            {
                "hotel_id": 4, "hotel_name": "Vinpearl Resort Nha Trang", "accommodation_type": "khách sạn",
                "city": "Nha Trang", "country": "Việt Nam", "coordinates": "12.239700,109.197600",
                "star_rating": 5, "amenities": ["Wifi", "Pool"], "warnings": [], "price": 3000000,
                "currency": "VND", "check_in": "2026-08-01", "check_out": "2026-08-02",
                "property_url": "https://booking.com/x", "scraped_at": "2026-07-22T10:00:00+00:00",
                "rooms_available": True, "all_images": ["http://x/2.jpg"],
                "address": "123 Tran Phu Street Nha Trang", "review_count": 50, "description": None,
                "rooms": [], "source_platform": "booking",
            }
        )
        hotels, stats = assign_physical_hotel_groups([agoda, uncertain])
        self.assertEqual(agoda["canonical"]["group_review_status"], PENDING_REVIEW)

        results = render_hotel_search_results(hotels)

        self.assertEqual(len(results), 2, "pending-review pairs must not look merged to the AI/user")


class AutoApprovedConstantDriftTests(unittest.TestCase):
    def test_hotel_retrieval_auto_approved_matches_hotel_pipeline(self):
        # src/services/hotel_retrieval.py duplicates this value locally
        # (can't import hotel_pipeline.py — it's Airflow-only and pulls in
        # psycopg2 as an import side effect). This test is what catches the
        # two constants drifting apart if hotel_pipeline.py's value changes.
        from src.services.hotel_retrieval import AUTO_APPROVED as RENDERER_AUTO_APPROVED

        self.assertEqual(AUTO_APPROVED, RENDERER_AUTO_APPROVED)


if __name__ == "__main__":
    unittest.main()
