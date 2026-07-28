import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, Mock, patch


PIPELINE_DIR = Path(__file__).resolve().parents[1] / "dags" / "data_pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

from attraction_utils import (  # noqa: E402
    deduplicate_attractions,
    is_coordinate_allowed,
    normalize_text,
    parse_coordinates,
    sanitize_attraction_name,
    select_diverse_attractions,
)
from destination_geo import crawler_user_agent  # noqa: E402
from destination_geo import resolve_location_context  # noqa: E402
from dag_common import optional_location_coords_param_kwargs  # noqa: E402
from grounded_description import (  # noqa: E402
    _is_trusted_search_source_url,
    _is_grounded_description_valid,
    _parse_ollama_description,
    _trusted_search_result_urls,
    _validated_web_source,
    _validated_wikipedia_source,
    enrich_description_from_sources,
)
from google_maps_pipeline import (  # noqa: E402
    _coordinates_from_google_maps_url,
    _card_description,
    _candidate_from_google_card,
    _candidate_from_google_maps_place_page,
    _google_ai_description_from_block_text,
    _google_ai_search_query,
    _is_geographically_valid_nearby_maps_result,
    _google_maps_shared_place_url,
    _is_supported_official_content_url,
    _is_usable_attraction_description,
    _json_ld_description_candidates,
    _fact_based_description,
    _google_maps_enrichment_urls,
    _google_maps_official_website,
    _trim_incomplete_description,
    _is_safe_official_site_url,
    _is_google_maps_place_url,
    _large_google_image_url,
    _load_google_maps_detail,
    _merge_google_maps_detail,
    _merge_official_site_detail,
    _normalize_google_maps_detail,
    _normalize_google_maps_destination,
    _parse_google_maps_hours,
    _google_maps_detail_from_page,
    collect_google_maps_attractions,
    enrich_google_maps_records,
    normalize_google_maps_candidate,
    normalize_google_maps_candidates,
    resolve_google_maps_nearby_candidates,
)
from hotel_nearby_pipeline import (  # noqa: E402
    _batches_by_hotel,
    canonical_booking_hotel_url,
    crawl_hotel_surroundings,
    extract_agoda_surrounding_names,
    extract_booking_surrounding_names,
    fetch_hotel_sources,
    filter_existing_attraction_names,
    is_within_hotel_radius,
    resolve_hotel_surrounding_seeds,
)
from ota_pipeline import (  # noqa: E402
    _agoda_browser_context_options,
    _canonical_agoda_product_url,
    collect_ota_attractions,
    geofilter_ota_candidates,
    parse_agoda_html,
    parse_booking_html,
)
from osm_pipeline import (  # noqa: E402
    collect_osm_attractions,
    fetch_osm_attractions,
    get_or_create_destination,
    load_attractions_to_db,
    transform_to_attraction,
)
from pipeline_stages import deduplicate_and_select, summarize_quality  # noqa: E402


class AttractionNameTests(unittest.TestCase):
    def test_name_keeps_vietnamese_english_and_normal_punctuation(self):
        self.assertEqual(
            sanitize_attraction_name(
                "Huyền Hương Cơm Bắc, Cơm Niêu Restaurant "
                "후엔흐엉 북부밥 및 나짱 뚝배기밥"
            ),
            "Huyền Hương Cơm Bắc, Cơm Niêu Restaurant",
        )

    def test_name_removes_other_scripts_and_symbols_without_empty_punctuation(self):
        self.assertEqual(
            sanitize_attraction_name("海洋博物館 Museum (한글) 🌊 - Nha Trang"),
            "Museum - Nha Trang",
        )

    def test_name_keeps_balanced_parentheses_at_the_name_boundary(self):
        name = "La Viet Coffee (Nha Trang - 8 Le Loi)"

        self.assertEqual(sanitize_attraction_name(name), name)

    @patch("osm_pipeline.psycopg2")
    def test_database_loader_sanitizes_names_before_upsert(self, psycopg2_mock):
        connection = psycopg2_mock.connect.return_value
        cursor = connection.cursor.return_value
        record = {
            "id": "0ac540c9-3ec1-5b4e-9938-a978aa566268",
            "name": "Huyền Hương Restaurant 후엔흐엉",
        }

        load_attractions_to_db([record], {"dbname": "test"})

        loaded_records = cursor.executemany.call_args.args[1]
        self.assertEqual(loaded_records[0]["name"], "Huyền Hương Restaurant")
        self.assertEqual(record["name"], "Huyền Hương Restaurant 후엔흐엉")


class PipelineStageTests(unittest.TestCase):
    def test_deduplicate_stage_selects_canonical_records_and_quality_reports_coverage(self):
        records = [
            {
                "id": "booking-museum",
                "destination_id": "destination-id",
                "name": "Nha Trang Ocean Museum Admission",
                "description": "Short description",
                "category": "Museums & culture",
                "source": "booking",
                "source_id": "booking-1",
                "is_tour": False,
                "latitude": 12.2070,
                "longitude": 109.2140,
                "coordinates": "12.207,109.214",
                "images": [],
            },
            {
                "id": "agoda-museum",
                "destination_id": "destination-id",
                "name": "Nha Trang Ocean Museum Ticket",
                "description": "A complete museum description.",
                "category": "Museums & culture",
                "source": "agoda",
                "source_id": "agoda-1",
                "is_tour": False,
                "latitude": 12.2071,
                "longitude": 109.2141,
                "coordinates": "12.2071,109.2141",
                "images": ["https://example.com/museum.jpg"],
            },
        ]

        selected = deduplicate_and_select(records, item_limit=10)
        report = summarize_quality(selected, extracted_count=len(records))

        self.assertEqual(len(selected), 1)
        self.assertEqual(report["extracted_records"], 2)
        self.assertEqual(report["selected_records"], 1)
        self.assertEqual(report["schema_valid_records"], 1)
        self.assertEqual(report["description_coverage_percent"], 100.0)
        self.assertEqual(report["image_coverage_percent"], 100.0)


class HotelNearbyPipelineTests(unittest.TestCase):
    def test_existing_attraction_names_are_filtered_after_name_normalization(self):
        records = [
            {"name": "Bảo tàng Cổ vật Cung đình"},
            {"name": "Công viên Lê Lợi"},
        ]

        retained = filter_existing_attraction_names(
            records,
            {"bảo tàng cổ vật cung đình"},
        )

        self.assertEqual(retained, [{"name": "Công viên Lê Lợi"}])

    def test_hotel_batches_keep_all_surroundings_for_the_same_hotel_together(self):
        records = [
            {"hotel_id": "hotel-a", "name": "A1"},
            {"hotel_id": "hotel-a", "name": "A2"},
            {"hotel_id": "hotel-b", "name": "B1"},
            {"hotel_id": "hotel-c", "name": "C1"},
        ]

        batches = _batches_by_hotel(records, worker_count=2)
        hotel_a_batches = [
            batch for batch in batches
            if any(record["hotel_id"] == "hotel-a" for record in batch)
        ]

        self.assertEqual(len(hotel_a_batches), 1)
        self.assertEqual(
            [
                record["name"] for record in hotel_a_batches[0]
                if record["hotel_id"] == "hotel-a"
            ],
            ["A1", "A2"],
        )
        self.assertEqual(len(batches), 2)
        self.assertEqual(sum(len(batch) for batch in batches), len(records))

    @patch("hotel_nearby_pipeline._crawl_hotel_surroundings_batch")
    def test_hotel_crawler_uses_a_bounded_parallel_batch_for_each_hotel_group(self, crawl_batch):
        hotels = [
            {"hotel_id": "hotel-a", "name": "Hotel A"},
            {"hotel_id": "hotel-b", "name": "Hotel B"},
        ]
        crawl_batch.side_effect = lambda batch, _limit: list(batch)

        result = crawl_hotel_surroundings(hotels, nearby_limit_per_hotel=8, worker_count=2)

        self.assertEqual(result, hotels)
        self.assertEqual(crawl_batch.call_count, 2)

    @patch("hotel_nearby_pipeline.resolve_google_maps_nearby_candidates")
    def test_hotel_maps_resolver_processes_hotel_groups_in_parallel_batches(self, resolve_maps):
        seeds = [
            {"hotel_id": "hotel-a", "name": "A1"},
            {"hotel_id": "hotel-a", "name": "A2"},
            {"hotel_id": "hotel-b", "name": "B1"},
        ]
        resolve_maps.side_effect = lambda batch, *_args: list(batch)

        result = resolve_hotel_surrounding_seeds(
            seeds,
            {"mode": "radius", "latitude": 16.4, "longitude": 107.5},
            hotel_radius_meters=5_000,
            destination_name="Huế",
            worker_count=2,
        )

        self.assertEqual(result, seeds)
        self.assertEqual(resolve_maps.call_count, 2)

    def test_booking_hotel_url_uses_canonical_vietnam_path_without_tracking_query(self):
        self.assertEqual(
            canonical_booking_hotel_url(
                "https://www.booking.com/hotel/vn/an-tam.en-gb.html?"
                "lang=en-gb&force_referer=http%3A%2F%2Flocalhost%3A8082%2F"
            ),
            "https://www.booking.com/hotel/vn/an-tam.en-gb.html?lang=vi",
        )
        self.assertEqual(
            canonical_booking_hotel_url(
                "https://www.booking.com/hotel/example.html?lang=en-gb"
            ),
            "https://www.booking.com/hotel/vn/example.html?lang=vi",
        )

    def test_booking_surroundings_parser_keeps_named_places_in_its_nearby_section(self):
        html = """
        <section><h2>Property surroundings</h2>
          <ul><li>Chợ Đầm</li><li>Tháp Bà Ponagar</li><li>500 m</li></ul>
        </section>
        <section><h2>House rules</h2><p>Check-in is from 14:00.</p></section>
        """

        self.assertEqual(
            extract_booking_surrounding_names(html, "Khách sạn mẫu"),
            ["Chợ Đầm", "Tháp Bà Ponagar"],
        )

    def test_agoda_surroundings_parser_uses_its_landmarks_section(self):
        html = """
        <section><h2>Popular landmarks</h2>
          <ul><li>Nhà thờ Đá Nha Trang</li><li>Bãi biển Trần Phú</li></ul>
        </section>
        <section><h2>Rooms</h2><p>Deluxe room</p></section>
        """

        self.assertEqual(
            extract_agoda_surrounding_names(html, "Khách sạn mẫu"),
            ["Nhà thờ Đá Nha Trang", "Bãi biển Trần Phú"],
        )

    def test_booking_surroundings_excludes_public_transport_and_airports(self):
        html = """
        <section><h2>Hotel surroundings</h2>
          <h3>What's nearby</h3><ul><li>Fine Arts Museum</li></ul>
          <h3>Top attractions</h3><ul><li>Ho Chi Minh City Museum</li></ul>
          <h3>Public transport</h3><ul><li>Saigon Railway Station</li></ul>
          <h3>Closest airports</h3><ul><li>Tan Son Nhat International Airport</li></ul>
        </section>
        """

        self.assertEqual(
            extract_booking_surrounding_names(html, "Mays Hotel- Ben Thanh"),
            ["Fine Arts Museum", "Ho Chi Minh City Museum"],
        )

    def test_booking_surroundings_removes_distances_and_ui_labels(self):
        html = """
        <section><h2>Hotel surroundings</h2>
          <h3>What's nearby</h3>
          <ul>
            <li>Excellent location - show map</li>
            <li>Museum of Royal Antiquities 550 yd</li>
            <li>Forbidden Purple City 0.7 mi</li>
            <li>Truong Tien Bridge 1,050 yd</li>
            <li>Tử Cấm Thành 1,2 km</li>
          </ul>
        </section>
        """

        self.assertEqual(
            extract_booking_surrounding_names(html, "Hotel in Hue"),
            [
                "Museum of Royal Antiquities",
                "Forbidden Purple City",
                "Truong Tien Bridge",
                "Tử Cấm Thành",
            ],
        )

    def test_booking_surroundings_supports_vietnamese_hotel_surroundings_heading(self):
        html = """
        <section><h2>Xung quanh khách sạn</h2>
          <ul><li>Bảo tàng Mỹ thuật Thành phố Hồ Chí Minh</li></ul>
        </section>
        """

        self.assertEqual(
            extract_booking_surrounding_names(html, "Mays Hotel- Ben Thanh"),
            ["Bảo tàng Mỹ thuật Thành phố Hồ Chí Minh"],
        )

    def test_booking_surroundings_supports_vietnamese_category_headings(self):
        html = """
        <section><h2>Xung quanh khách sạn</h2>
          <h3>Xung quanh có gì?</h3><ul><li>Bảo tàng Mỹ thuật</li></ul>
          <h3>Địa điểm tham quan hàng đầu</h3><ul><li>Bảo tàng Thành phố Hồ Chí Minh</li></ul>
          <h3>Phương tiện công cộng</h3><ul><li>Ga Hòa Hưng</li></ul>
          <h3>Các sân bay gần nhất</h3><ul><li>Sân bay Quốc tế Tân Sơn Nhất</li></ul>
        </section>
        """

        self.assertEqual(
            extract_booking_surrounding_names(html, "Mays Hotel- Ben Thanh"),
            ["Bảo tàng Mỹ thuật", "Bảo tàng Thành phố Hồ Chí Minh"],
        )

    def test_hotel_radius_rejects_same_named_result_that_is_too_far_away(self):
        self.assertTrue(is_within_hotel_radius(12.245, 109.194, 12.247, 109.195, 1_000))
        self.assertFalse(is_within_hotel_radius(12.245, 109.194, 12.300, 109.250, 1_000))

    @patch("hotel_nearby_pipeline.psycopg2")
    def test_hotel_source_query_limits_to_one_hotel_when_id_is_provided(self, psycopg2_mock):
        cursor = psycopg2_mock.connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        fetch_hotel_sources("destination-id", hotel_id="hotel-id")

        query, arguments = cursor.execute.call_args.args
        self.assertIn("id::text = %s", query)
        self.assertNotIn("LIMIT", query)
        self.assertEqual(arguments, ("destination-id", "hotel-id"))

    @patch("hotel_nearby_pipeline.psycopg2")
    def test_hotel_source_query_uses_all_destination_hotels_when_id_is_empty(self, psycopg2_mock):
        cursor = psycopg2_mock.connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        fetch_hotel_sources("destination-id")

        query, arguments = cursor.execute.call_args.args
        self.assertNotIn("id::text = %s", query)
        self.assertNotIn("LIMIT", query)
        self.assertEqual(arguments, ("destination-id",))

    @patch("hotel_nearby_pipeline.psycopg2")
    def test_hotel_sources_returns_one_entry_per_ota_listing(self, psycopg2_mock):
        cursor = psycopg2_mock.connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            ("hotel-agoda", "Same Physical Hotel", "10.7627,106.6603", "agoda",
             "https://www.agoda.com/same-hotel/hotel/ho-chi-minh-city-vn.html"),
            ("hotel-booking", "Same Physical Hotel", "10.7627,106.6603", "booking",
             "https://www.booking.com/hotel/vn/same-hotel.vi.html"),
        ]

        results = fetch_hotel_sources("destination-id")

        self.assertEqual(len(results), 2)
        self.assertEqual(
            [entry["source"] for entry in results],
            ["agoda", "booking"],
        )
        self.assertEqual(
            results[0]["source_url"],
            "https://www.agoda.com/same-hotel/hotel/ho-chi-minh-city-vn.html",
        )
        self.assertEqual(results[0]["hotel_id"], "hotel-agoda")
        self.assertEqual(results[0]["hotel_latitude"], 10.7627)
        self.assertEqual(results[0]["hotel_longitude"], 106.6603)

    @patch("hotel_nearby_pipeline.psycopg2")
    def test_hotel_sources_skip_rows_missing_platform_or_coordinates(self, psycopg2_mock):
        cursor = psycopg2_mock.connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            ("no-coords", "Missing Coordinates", "", "agoda", "https://www.agoda.com/x/hotel/y.html"),
            ("no-platform", "Missing Platform", "10.0,106.0", "", "https://www.agoda.com/x/hotel/y.html"),
        ]

        results = fetch_hotel_sources("destination-id")

        self.assertEqual(results, [])


class GeographyTests(unittest.TestCase):
    def test_nominatim_user_agent_does_not_use_placeholder_contact(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(crawler_user_agent(), "VSFAttractionCrawler/1.0")

    def test_nominatim_user_agent_uses_configured_contact(self):
        with patch.dict(
            "os.environ",
            {"VSF_CRAWLER_CONTACT": "crawler@example.org"},
            clear=True,
        ):
            self.assertEqual(
                crawler_user_agent(),
                "VSFAttractionCrawler/1.0 (crawler@example.org)",
            )

    def test_coordinates_are_authoritative_when_provided(self):
        context = {
            "mode": "radius",
            "latitude": 12.245071,
            "longitude": 109.194317,
            "radius_meters": 2_000,
        }

        self.assertTrue(is_coordinate_allowed(12.2500, 109.1900, context))
        self.assertFalse(is_coordinate_allowed(12.3000, 109.2500, context))

    def test_name_only_mode_uses_region_polygon(self):
        context = {
            "mode": "boundary",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [109.0, 12.0],
                        [109.4, 12.0],
                        [109.4, 12.4],
                        [109.0, 12.4],
                        [109.0, 12.0],
                    ]
                ],
            },
        }

        self.assertTrue(is_coordinate_allowed(12.2, 109.2, context))
        self.assertFalse(is_coordinate_allowed(12.5, 109.2, context))


    def test_coordinate_parser_rejects_invalid_values(self):
        self.assertEqual(parse_coordinates("12.25,109.19"), (12.25, 109.19))
        with self.assertRaises(ValueError):
            parse_coordinates("95,109")

    def test_vietnamese_destination_normalization_preserves_d(self):
        self.assertEqual(normalize_text("Đà Nẵng"), "da nang")

    @patch("destination_geo.scrape_google_maps_destination", return_value=None)
    @patch("destination_geo._nominatim_get")
    def test_name_only_resolution_ignores_non_administrative_polygons(
        self,
        nominatim_mock,
        google_maps_mock,
    ):
        polygon = {
            "type": "Polygon",
            "coordinates": [[[109.0, 12.0], [109.1, 12.0], [109.1, 12.1], [109.0, 12.0]]],
        }
        nominatim_mock.return_value = [
            {
                "lat": "12.2",
                "lon": "109.2",
                "category": "tourism",
                "type": "attraction",
                "addresstype": "attraction",
                "geojson": polygon,
                "address": {"country_code": "vn"},
                "display_name": "A similarly named attraction",
            },
            {
                "lat": "12.25",
                "lon": "109.19",
                "category": "boundary",
                "type": "administrative",
                "addresstype": "city",
                "geojson": polygon,
                "address": {"country_code": "vn"},
                "display_name": "Nha Trang, Khanh Hoa, Vietnam",
            },
        ]

        context = resolve_location_context("Nha Trang")

        self.assertEqual(context["display_name"], "Nha Trang, Khanh Hoa, Vietnam")

    @patch("destination_geo.scrape_google_maps_destination", return_value=None)
    @patch("destination_geo._nominatim_get")
    def test_name_only_resolution_accepts_historic_city_boundary(
        self,
        nominatim_mock,
        google_maps_mock,
    ):
        city_polygon = {
            "type": "MultiPolygon",
            "coordinates": [[[[109.0, 12.0], [109.4, 12.0], [109.4, 12.4], [109.0, 12.0]]]],
        }
        ward_polygon = {
            "type": "Polygon",
            "coordinates": [[[109.1, 12.1], [109.2, 12.1], [109.2, 12.2], [109.1, 12.1]]],
        }
        nominatim_mock.return_value = [
            {
                "lat": "12.24",
                "lon": "109.19",
                "category": "boundary",
                "type": "historic",
                "addresstype": "historic",
                "geojson": city_polygon,
                "address": {"country_code": "vn"},
                "display_name": "Thanh pho Nha Trang, Khanh Hoa, Vietnam",
            },
            {
                "lat": "12.23",
                "lon": "109.20",
                "category": "boundary",
                "type": "administrative",
                "addresstype": "suburb",
                "geojson": ward_polygon,
                "address": {"country_code": "vn"},
                "display_name": "Phuong Nha Trang, Khanh Hoa, Vietnam",
            },
        ]

        context = resolve_location_context("Nha Trang")

        self.assertEqual(
            context["display_name"],
            "Thanh pho Nha Trang, Khanh Hoa, Vietnam",
        )

    @patch("destination_geo.scrape_google_maps_destination")
    @patch("destination_geo._nominatim_get")
    def test_name_only_resolution_uses_google_center_inside_osm_boundary(
        self,
        nominatim_mock,
        google_maps_mock,
    ):
        polygon = {
            "type": "Polygon",
            "coordinates": [[
                [109.0, 12.0],
                [109.4, 12.0],
                [109.4, 12.4],
                [109.0, 12.4],
                [109.0, 12.0],
            ]],
        }
        nominatim_mock.return_value = [{
            "lat": "12.2500",
            "lon": "109.1900",
            "category": "boundary",
            "type": "administrative",
            "addresstype": "city",
            "geojson": polygon,
            "address": {
                "city": "ThÃ nh phá»‘ Nha Trang",
                "state": "Tá»‰nh KhÃ¡nh HÃ²a",
                "country_code": "vn",
            },
            "display_name": "Nha Trang, Khanh Hoa, Vietnam",
        }]
        google_maps_mock.return_value = {
            "name": "Nha Trang",
            "address": "Nha Trang, Khanh Hoa",
            "latitude": 12.245071,
            "longitude": 109.194317,
            "url": "https://www.google.com/maps/place/Nha+Trang/",
            "source": "google_maps_poc",
        }

        context = resolve_location_context("Nha Trang")

        self.assertEqual(context["mode"], "boundary")
        self.assertIs(context["geometry"], polygon)
        self.assertEqual(context["latitude"], 12.245071)
        self.assertEqual(context["longitude"], 109.194317)
        self.assertEqual(context["destination_coordinates"], "12.245071,109.194317")
        self.assertEqual(context["coordinate_source"], "google_maps_poc")

    @patch("destination_geo.scrape_google_maps_destination")
    @patch("destination_geo._nominatim_get")
    def test_name_only_resolution_rejects_google_center_outside_osm_boundary(
        self,
        nominatim_mock,
        google_maps_mock,
    ):
        polygon = {
            "type": "Polygon",
            "coordinates": [[
                [109.0, 12.0],
                [109.4, 12.0],
                [109.4, 12.4],
                [109.0, 12.4],
                [109.0, 12.0],
            ]],
        }
        nominatim_mock.return_value = [{
            "lat": "12.2500",
            "lon": "109.1900",
            "category": "boundary",
            "type": "administrative",
            "addresstype": "city",
            "geojson": polygon,
            "address": {"country_code": "vn"},
            "display_name": "Nha Trang, Khanh Hoa, Vietnam",
        }]
        google_maps_mock.return_value = {
            "name": "Wrong result",
            "latitude": 10.7769,
            "longitude": 106.7009,
            "source": "google_maps_poc",
        }

        context = resolve_location_context("Nha Trang")

        self.assertEqual(context["latitude"], 12.25)
        self.assertEqual(context["longitude"], 109.19)
        self.assertEqual(context["coordinate_source"], "openstreetmap")


class GoogleMapsPipelineTests(unittest.TestCase):
    def test_trusted_grounding_urls_allow_editorial_sources_not_social_or_private_hosts(self):
        self.assertTrue(
            _is_trusted_search_source_url(
                "https://svhtt.khanhhoa.gov.vn/di-tich-lich-su"
            )
        )
        self.assertTrue(
            _is_trusted_search_source_url(
                "https://laodong.vn/du-lich/khu-tuong-niem-123.html"
            )
        )
        self.assertTrue(
            _is_trusted_search_source_url(
                "https://vi.wikivoyage.org/wiki/Nha_Trang"
            )
        )
        self.assertFalse(
            _is_trusted_search_source_url(
                "https://instagram.com/example-attraction"
            )
        )
        self.assertFalse(
            _is_trusted_search_source_url(
                "https://127.0.0.1/internal-description"
            )
        )
        self.assertFalse(
            _is_trusted_search_source_url(
                "http://laodong.vn/unencrypted"
            )
        )

    def test_google_search_links_are_unwrapped_and_filtered_to_trusted_sources(self):
        urls = _trusted_search_result_urls(
            [
                (
                    "https://www.google.com/url?"
                    "url=https%3A%2F%2Fsvhtt.khanhhoa.gov.vn%2Fdi-tich"
                ),
                "https://laodong.vn/du-lich/khu-tuong-niem-123.html",
                "https://example.com/seo-page",
                "https://facebook.com/untrusted-profile",
            ]
        )

        self.assertEqual(
            urls,
            [
                "https://svhtt.khanhhoa.gov.vn/di-tich",
                "https://laodong.vn/du-lich/khu-tuong-niem-123.html",
            ],
        )

    def test_external_grounding_source_requires_matching_name_and_destination(self):
        source = _validated_web_source(
            attraction_name="Khu Tưởng niệm Chủ tịch Hồ Chí Minh",
            destination_name="Nha Trang",
            source_url="https://svhtt.khanhhoa.gov.vn/khu-tuong-niem",
            heading="Khu Tưởng niệm Chủ tịch Hồ Chí Minh",
            paragraphs=[
                (
                    "Khu Tưởng niệm Chủ tịch Hồ Chí Minh tại thành phố Nha Trang "
                    "là không gian trưng bày, lưu giữ tư liệu và hình ảnh về "
                    "cuộc đời, sự nghiệp của Chủ tịch Hồ Chí Minh."
                )
            ],
        )

        self.assertEqual(source["source_type"], "trusted_web")
        self.assertIn("thành phố Nha Trang", source["text"])
        self.assertIsNone(
            _validated_web_source(
                attraction_name="Khu Tưởng niệm Chủ tịch Hồ Chí Minh",
                destination_name="Nha Trang",
                source_url="https://laodong.vn/du-lich/bao-tang-ha-noi.html",
                heading="Bảo tàng Hà Nội",
                paragraphs=[
                    (
                        "Bảo tàng Hà Nội giới thiệu lịch sử Thủ đô và nhiều "
                        "bộ sưu tập hiện vật có giá trị."
                    )
                ],
            )
        )

    @patch("builtins.print")
    @patch(
        "grounded_description._ollama_grounded_description",
        return_value={
            "description": "Mô tả có căn cứ từ nguồn báo chí.",
            "source_url": "https://laodong.vn/du-lich/khu-tuong-niem.html",
            "source_type": "trusted_web",
            "model": "llama3:latest",
        },
    )
    @patch(
        "grounded_description._load_trusted_search_source",
        return_value={
            "source_type": "trusted_web",
            "source_url": "https://laodong.vn/du-lich/khu-tuong-niem.html",
            "text": (
                "Khu Tưởng niệm Chủ tịch Hồ Chí Minh tại Nha Trang lưu giữ "
                "nhiều tư liệu và hình ảnh lịch sử."
            ),
        },
    )
    @patch("grounded_description._load_wikipedia_source", return_value=None)
    def test_grounded_description_uses_trusted_web_when_wikipedia_has_no_match(
        self,
        _wikipedia_mock,
        trusted_search_mock,
        ollama_mock,
        _print_mock,
    ):
        result = enrich_description_from_sources(
            Mock(),
            {"name": "Khu Tưởng niệm Chủ tịch Hồ Chí Minh"},
            "Nha Trang",
        )

        self.assertEqual(result["source_type"], "trusted_web")
        trusted_search_mock.assert_called_once()
        self.assertEqual(
            ollama_mock.call_args.args[2]["source_url"],
            "https://laodong.vn/du-lich/khu-tuong-niem.html",
        )

    def test_wikipedia_source_requires_matching_attraction_and_destination(self):
        source = _validated_wikipedia_source(
            attraction_name="Lăng Tự Đức",
            destination_name="Huế",
            source_url="https://vi.wikipedia.org/wiki/L%C4%83ng_T%E1%BB%B1_%C4%90%E1%BB%A9c",
            heading="Lăng Tự Đức",
            paragraphs=[
                (
                    "Lăng Tự Đức là một quần thể di tích kiến trúc tọa lạc "
                    "tại phường Thủy Xuân, thành phố Huế."
                )
            ],
        )

        self.assertEqual(source["source_type"], "wikipedia_web")
        self.assertIn("thành phố Huế", source["text"])

    def test_wikipedia_source_rejects_a_different_place(self):
        source = _validated_wikipedia_source(
            attraction_name="Lăng Tự Đức",
            destination_name="Huế",
            source_url="https://vi.wikipedia.org/wiki/L%C4%83ng_Minh_M%E1%BA%A1ng",
            heading="Lăng Minh Mạng",
            paragraphs=[
                (
                    "Lăng Minh Mạng là một quần thể kiến trúc tại thành phố "
                    "Huế và không phải Lăng Tự Đức."
                )
            ],
        )

        self.assertIsNone(source)

    def test_grounded_description_rejects_numbers_absent_from_source(self):
        source_text = (
            "Lăng Tự Đức là quần thể di tích kiến trúc tại thành phố Huế. "
            "Công trình có phong cảnh sơn thủy và nhiều hạng mục lịch sử."
        )
        description = (
            "Lăng Tự Đức là một quần thể di tích kiến trúc tại thành phố Huế, "
            "nổi bật với bố cục hài hòa cùng cảnh quan sơn thủy. Không gian di "
            "tích gồm nhiều công trình lịch sử gắn với triều Nguyễn và phản ánh "
            "giá trị kiến trúc cung đình của cố đô."
        )

        self.assertTrue(
            _is_grounded_description_valid(
                description,
                "Lăng Tự Đức",
                "Huế",
                source_text,
            )
        )
        self.assertFalse(
            _is_grounded_description_valid(
                f"{description} Công trình được xây dựng lại vào năm 2099.",
                "Lăng Tự Đức",
                "Huế",
                source_text,
            )
        )

    def test_ollama_json_parser_returns_only_the_description(self):
        response = {
            "message": {
                "content": (
                    '{"description":"Lăng Tự Đức là một quần thể di tích '
                    'kiến trúc nổi tiếng tại thành phố Huế."}'
                )
            }
        }

        self.assertEqual(
            _parse_ollama_description(response),
            "Lăng Tự Đức là một quần thể di tích kiến trúc nổi tiếng tại thành phố Huế.",
        )

    def test_google_ai_search_query_uses_name_destination_and_vietnamese_intent(self):
        query = _google_ai_search_query(
            "Địa điểm chiến thắng Đầm Dơi - Cái Nước - Chà Là",
            "Cà Mau",
        )

        self.assertEqual(
            query,
            '"Địa điểm chiến thắng Đầm Dơi - Cái Nước - Chà Là" '
            '"Cà Mau" giới thiệu lịch sử địa điểm tham quan',
        )

    def test_google_ai_description_parser_returns_the_overview_lead_paragraph(self):
        description = (
            "Địa điểm chiến thắng Đầm Dơi - Cái Nước - Chà Là tọa lạc tại "
            "xã Trần Phán, tỉnh Cà Mau và là di tích lịch sử cấp quốc gia ghi "
            "dấu những chiến công trong thời kỳ kháng chiến."
        )
        block_text = (
            "Thông tin tổng quan do AI tạo\n"
            f"{description}\n"
            "Laodong.vn\n"
            "+2\n"
            "Lịch sử chiến thắng\n"
            "Giá trị lịch sử\n"
            "Hiện thêm"
        )

        self.assertEqual(
            _google_ai_description_from_block_text(block_text),
            description,
        )

    def test_instagram_profile_metadata_is_not_a_usable_attraction_description(self):
        description = (
            "2,310 người theo dõi, 0 đang theo dõi, 262 bài viết – "
            "Ăn thôi Nhà Hàng (@anthoi.vietnam) trên Instagram: "
            '"Michelin Bib Gourmand 2024"'
        )

        self.assertFalse(_is_usable_attraction_description(description))

    def test_social_profile_is_not_an_official_content_source(self):
        self.assertFalse(
            _is_supported_official_content_url(
                "https://www.instagram.com/anthoi.vietnam/"
            )
        )
        self.assertTrue(
            _is_supported_official_content_url(
                "https://museum.example.vn/about"
            )
        )

    def test_maps_merge_does_not_replace_editorial_text_with_a_generic_label(self):
        editorial = (
            "The museum presents historical collections and permanent exhibitions "
            "about the development of the city."
        )

        result = _merge_google_maps_detail(
            {"description": editorial, "images": []},
            {"description": "Trạm xe buýt", "images": []},
        )

        self.assertEqual(result["description"], editorial)

    def test_official_json_ld_supplies_attraction_description(self):
        description = (
            "This museum preserves royal objects and presents the history of the "
            "Nguyen dynasty through permanent exhibitions."
        )
        payload = (
            '{"@context":"https://schema.org","@graph":['
            '{"@type":"Museum","name":"Royal Museum",'
            f'"description":"{description}"}}]}}'
        )

        self.assertEqual(_json_ld_description_candidates([payload]), [description])

    def test_nearby_resolver_retries_a_valid_place_after_an_initial_maps_shell(self):
        page = Mock()
        articles = Mock()
        articles.count.return_value = 0
        page.locator.return_value = articles
        context = Mock()
        context.new_page.return_value = page
        browser = Mock()
        browser.new_context.return_value = context
        playwright = Mock()
        playwright.chromium.launch.return_value = browser
        playwright_context = MagicMock()
        playwright_context.__enter__.return_value = playwright

        sync_api_module = ModuleType("playwright.sync_api")
        sync_api_module.sync_playwright = Mock(return_value=playwright_context)
        seed = {
            "name": "Bảo tàng Museum of Royal Antiquities",
            "category": "Museums & culture",
            "hotel_latitude": 16.4712,
            "hotel_longitude": 107.5853,
        }
        canonical_candidate = {
            **seed,
            "name": "Bảo tàng Cổ vật Cung đình",
            "source_id": "google-maps-museum",
            "latitude": 16.471343,
            "longitude": 107.58208,
        }
        location_context = {
            "mode": "radius",
            "latitude": 16.4712,
            "longitude": 107.5853,
            "radius_meters": 5_000,
        }

        with (
            patch.dict(
                sys.modules,
                {
                    "playwright": ModuleType("playwright"),
                    "playwright.sync_api": sync_api_module,
                },
            ),
            patch("google_maps_pipeline._accept_google_consent"),
            patch("google_maps_pipeline._raise_if_google_blocked"),
            patch(
                "google_maps_pipeline._candidate_from_google_maps_place_page",
                side_effect=[None, canonical_candidate],
            ),
            patch("google_maps_pipeline.time.sleep"),
            patch("builtins.print"),
        ):
            result = resolve_google_maps_nearby_candidates(
                [seed],
                location_context,
                hotel_radius_meters=5_000,
                destination_name="Huế",
            )

        self.assertEqual(result, [canonical_candidate])
        self.assertEqual(page.goto.call_count, 2)

    def test_nearby_maps_result_can_use_a_different_canonical_name(self):
        context = {
            "mode": "radius",
            "latitude": 16.4712,
            "longitude": 107.5853,
            "radius_meters": 5_000,
        }
        seed = {"hotel_latitude": 16.4712, "hotel_longitude": 107.5853}

        self.assertTrue(
            _is_geographically_valid_nearby_maps_result(
                {**seed, "name": "Hue Historic Citadel", "latitude": 16.47694, "longitude": 107.5739587},
                context,
                5_000,
            )
        )
        self.assertFalse(
            _is_geographically_valid_nearby_maps_result(
                {**seed, "name": "Far-away Citadel", "latitude": 16.60, "longitude": 107.80},
                context,
                5_000,
            )
        )

    def test_google_maps_share_dialog_returns_generated_canonical_place_link(self):
        share_button = Mock()
        share_button.count.return_value = 1
        inputs = Mock()
        inputs.count.return_value = 2
        inputs.nth.side_effect = [
            Mock(input_value=Mock(return_value="https://maps.app.goo.gl/place-link")),
            Mock(input_value=Mock(return_value="Kinh thành Huế")),
        ]
        page = Mock()
        page.get_by_role.return_value = share_button
        page.locator.return_value = inputs

        self.assertEqual(
            _google_maps_shared_place_url(page),
            "https://maps.app.goo.gl/place-link",
        )
        share_button.first.click.assert_called_once()

    def test_direct_maps_place_accepts_translated_name_before_geographic_validation(self):
        heading = Mock()
        heading.count.return_value = 1
        heading.first.inner_text.return_value = "Đại Nội Huế"
        images = Mock()
        images.count.return_value = 0
        page = Mock()
        page.url = (
            "https://www.google.com/maps/place/Dai-Noi-Hue/"
            "data=!3d16.469!4d107.579"
        )
        page.locator.side_effect = [heading, images]

        result = _candidate_from_google_maps_place_page(
            page,
            {
                "name": "Tử Cấm Thành",
                "hotel_latitude": 16.471,
                "hotel_longitude": 107.585,
            },
        )

        self.assertEqual(result["name"], "Đại Nội Huế")
        self.assertEqual(result["latitude"], 16.469)

    def test_official_description_trims_incomplete_trailing_phrase(self):
        self.assertEqual(
            _trim_incomplete_description(
                "A complete description of the attraction. A truncated phrase,"
            ),
            "A complete description of the attraction.",
        )

    def test_official_site_url_requires_public_https_domain(self):
        self.assertTrue(_is_safe_official_site_url("https://museum.example.vn/about"))
        self.assertFalse(_is_safe_official_site_url("http://museum.example.vn"))
        self.assertFalse(_is_safe_official_site_url("https://localhost/info"))
        self.assertFalse(_is_safe_official_site_url("https://127.0.0.1/info"))

    def test_official_site_detail_upgrades_sparse_maps_content(self):
        result = _merge_official_site_detail(
            {
                "description": "A short Maps snippet.",
                "images": ["https://lh3.googleusercontent.com/place=w408-h306-k-no"],
            },
            {
                "description": (
                    "A detailed official description of the attraction, its history, "
                    "and the visitor experience."
                ),
                "images": ["https://museum.example.vn/images/exterior.jpg"],
            },
        )

        self.assertTrue(result["description"].startswith("A detailed official"))
        self.assertEqual(
            result["images"],
            [
                "https://museum.example.vn/images/exterior.jpg",
                "https://lh3.googleusercontent.com/place=w1200-h900-k-no",
            ],
        )

    def test_google_maps_official_website_reads_authority_link(self):
        authority_link = Mock()
        authority_link.count.return_value = 1
        authority_link.first.get_attribute.return_value = "https://museum.example.vn/"
        page = Mock()
        page.locator.return_value = authority_link

        self.assertEqual(
            _google_maps_official_website(page),
            "https://museum.example.vn/",
        )

    def test_google_maps_card_description_ignores_sponsored_labels(self):
        self.assertIsNone(
            _card_description(
                ["Over extracteD coffee", "Được tài trợ"],
                "Over extracteD coffee",
            )
        )

    def test_google_maps_poc_card_skips_description_but_keeps_metadata(self):
        place_url = (
            "https://www.google.com/maps/place/Thap-Ba/"
            "data=!4m7!3m6!1s0xabc:0xdef!8m2!3d12.2653665!4d109.1953678"
        )
        place_link = Mock()
        place_link.get_attribute.side_effect = lambda attribute: {
            "href": place_url,
            "aria-label": "Tháp Bà Ponagar",
        }.get(attribute)
        links = Mock()
        links.count.return_value = 1
        links.nth.return_value = place_link

        rating_node = Mock()
        rating_node.get_attribute.return_value = "4,7 sao"
        rating_nodes = Mock()
        rating_nodes.count.return_value = 1
        rating_nodes.nth.return_value = rating_node

        image_node = Mock()
        image_node.get_attribute.return_value = (
            "https://lh3.googleusercontent.com/place-photo=w114-h86-k-no"
        )
        images = Mock()
        images.count.return_value = 1
        images.nth.return_value = image_node

        article = Mock()
        article.locator.side_effect = [links, rating_nodes, images]
        article.inner_text.return_value = (
            "Tháp Bà Ponagar\n"
            "Một quần thể kiến trúc Chăm cổ tại Nha Trang."
        )

        candidate = _candidate_from_google_card(
            article,
            "Museums & culture",
            include_description=False,
        )

        self.assertEqual(candidate["name"], "Tháp Bà Ponagar")
        self.assertEqual(candidate["rating"], 4.7)
        self.assertEqual(candidate["latitude"], 12.2653665)
        self.assertEqual(candidate["longitude"], 109.1953678)
        self.assertEqual(
            candidate["image"],
            "https://lh3.googleusercontent.com/place-photo=w114-h86-k-no",
        )
        self.assertIsNone(candidate["description"])
        article.inner_text.assert_not_called()

    def test_google_maps_url_coordinates_support_rendered_place_links(self):
        url = (
            "https://www.google.com/maps/place/Thap-Ba/"
            "data=!4m7!3m6!1s0xabc:0xdef!8m2!3d12.2653665!4d109.1953678"
        )

        self.assertEqual(
            _coordinates_from_google_maps_url(url),
            (12.2653665, 109.1953678),
        )

    def test_google_maps_destination_normalization_extracts_center(self):
        result = _normalize_google_maps_destination(
            "Nha Trang",
            "Nha Trang",
            "Nha Trang, Khanh Hoa, Vietnam",
            "https://www.google.com/maps/place/Nha+Trang/"
            "data=!4m6!3m5!8m2!3d12.245071!4d109.194317",
        )

        self.assertEqual(result["name"], "Nha Trang")
        self.assertEqual(result["address"], "Nha Trang, Khanh Hoa, Vietnam")
        self.assertEqual(result["latitude"], 12.245071)
        self.assertEqual(result["longitude"], 109.194317)
        self.assertEqual(result["source"], "google_maps_poc")

    def test_google_maps_detail_keeps_editorial_text_and_large_photos(self):
        detail = _normalize_google_maps_detail(
            [
                "",
                "Các hiện vật gồm bộ xương cá voi, mô hình tàu thuyền "
                "và thủy cung có nhiều loài vật.",
            ],
            [
                {
                    "src": "https://lh3.googleusercontent.com/avatar=w80-h92-p-k-no",
                    "width": 80,
                    "height": 92,
                },
                {
                    "src": "https://lh3.googleusercontent.com/place=w408-h306-k-no",
                    "width": 408,
                    "height": 306,
                },
                {
                    "src": "https://example.com/not-google.jpg",
                    "width": 1200,
                    "height": 800,
                },
                {
                    "src": "https://evilgoogleusercontent.com/tracker=w1200-h800-k-no",
                    "width": 1200,
                    "height": 800,
                },
            ],
        )

        self.assertTrue(detail["description"].startswith("Các hiện vật"))
        self.assertEqual(
            detail["images"],
            ["https://lh3.googleusercontent.com/place=w1200-h900-k-no"],
        )

    def test_google_maps_image_urls_are_resized_without_changing_aspect_ratio(self):
        self.assertEqual(
            _large_google_image_url(
                "https://lh3.googleusercontent.com/portrait=w86-h114-k-no"
            ),
            "https://lh3.googleusercontent.com/portrait=w905-h1200-k-no",
        )

    def test_google_maps_detail_merge_prefers_detail_and_deduplicates_photo_sizes(self):
        record = {
            "description": None,
            "images": [
                "https://lh3.googleusercontent.com/place=w114-h86-k-no",
                "https://lh3.googleusercontent.com/second=w114-h86-k-no",
            ],
        }
        detail = {
            "description": "A reliable editorial description.",
            "images": ["https://lh3.googleusercontent.com/place=w408-h306-k-no"],
        }

        result = _merge_google_maps_detail(record, detail)

        self.assertEqual(result["description"], detail["description"])
        self.assertEqual(
            result["images"],
            [
                "https://lh3.googleusercontent.com/place=w1200-h900-k-no",
                "https://lh3.googleusercontent.com/second=w1200-h905-k-no",
            ],
        )

    def test_google_maps_hours_extracts_one_clear_daily_range(self):
        self.assertEqual(
            _parse_google_maps_hours(
                ["Thứ Tư,07:30 đến 21:30, Sao chép giờ mở cửa"]
            ),
            {"opening_time": "07:30:00", "closing_time": "21:30:00"},
        )

    def test_google_maps_hours_ignores_split_or_unrelated_ranges(self):
        self.assertEqual(
            _parse_google_maps_hours(
                [
                    "Thứ Tư,07:00 đến 11:00, 17:00 đến 22:00, "
                    "Sao chép giờ mở cửa",
                    "Lịch sự kiện,08:00 đến 10:00",
                ]
            ),
            {"opening_time": None, "closing_time": None},
        )

    def test_google_maps_detail_merge_adds_clear_opening_hours(self):
        result = _merge_google_maps_detail(
            {"description": None, "images": []},
            {
                "description": None,
                "images": [],
                "opening_time": "07:30:00",
                "closing_time": "21:30:00",
            },
        )

        self.assertEqual(result["opening_time"], "07:30:00")
        self.assertEqual(result["closing_time"], "21:30:00")

    def test_google_maps_detail_reads_hours_from_accessibility_button(self):
        description_locator = Mock()
        description_locator.all_inner_texts.return_value = []
        image_locator = Mock()
        image_locator.evaluate_all.return_value = []
        category_locator = Mock()
        category_locator.all_inner_texts.return_value = ["Công viên"]
        authority_locator = Mock()
        authority_locator.count.return_value = 1
        authority_locator.first.get_attribute.return_value = "https://park.example.vn/"
        hours_locator = Mock()
        hours_locator.count.return_value = 1
        hours_locator.nth.return_value.get_attribute.return_value = (
            "Thứ Tư,07:30 đến 21:30, Sao chép giờ mở cửa"
        )
        page = Mock()
        page.locator.side_effect = [
            description_locator,
            image_locator,
            category_locator,
            authority_locator,
            hours_locator,
        ]

        result = _google_maps_detail_from_page(page)

        self.assertEqual(result["opening_time"], "07:30:00")
        self.assertEqual(result["closing_time"], "21:30:00")
        self.assertEqual(result["official_website"], "https://park.example.vn/")

    def test_google_maps_enrichment_logs_record_progress(self):
        sync_api_module = ModuleType("playwright.sync_api")
        sync_playwright = MagicMock()
        sync_api_module.sync_playwright = sync_playwright
        playwright_module = ModuleType("playwright")
        playwright_module.sync_api = sync_api_module
        browser = Mock()
        context = Mock()
        browser.new_context.return_value = context
        context.new_page.return_value = Mock()
        sync_playwright.return_value.__enter__.return_value.chromium.launch.return_value = browser

        with (
            patch.dict(
                sys.modules,
                {"playwright": playwright_module, "playwright.sync_api": sync_api_module},
            ),
            patch(
                "google_maps_pipeline._load_google_maps_detail",
                return_value={"description": "A description", "images": []},
            ),
            patch("google_maps_pipeline.time.sleep"),
            patch("builtins.print") as print_mock,
        ):
            enrich_google_maps_records(
                [
                    {"source_id": "one", "name": "Place One", "images": []},
                    {"source_id": "two", "name": "Place Two", "images": []},
                ],
                [
                    {"source_id": "one", "url": ""},
                    {"source_id": "two", "url": ""},
                ],
                "Nha Trang",
            )

        messages = [str(call.args[0]) for call in print_mock.call_args_list]
        self.assertIn(
            "[google-maps-poc] Normalize enrichment: processing 1/2.",
            messages,
        )
        self.assertIn(
            "[google-maps-poc] Normalize enrichment: completed 2/2.",
            messages,
        )

    def test_google_maps_enrichment_uses_grounded_description_before_fallback(self):
        sync_api_module = ModuleType("playwright.sync_api")
        sync_playwright = MagicMock()
        sync_api_module.sync_playwright = sync_playwright
        playwright_module = ModuleType("playwright")
        playwright_module.sync_api = sync_api_module
        browser = Mock()
        context = Mock()
        browser.new_context.return_value = context
        context.new_page.return_value = Mock()
        sync_playwright.return_value.__enter__.return_value.chromium.launch.return_value = browser
        generated_description = (
            "Lăng Tự Đức là một quần thể di tích kiến trúc tại thành phố Huế, "
            "nổi bật với bố cục hài hòa cùng cảnh quan sơn thủy. Không gian di "
            "tích gồm nhiều công trình lịch sử gắn với triều Nguyễn và phản ánh "
            "giá trị kiến trúc cung đình của cố đô."
        )

        with (
            patch.dict(
                sys.modules,
                {"playwright": playwright_module, "playwright.sync_api": sync_api_module},
            ),
            patch(
                "google_maps_pipeline._load_google_maps_detail",
                return_value={"description": None, "images": []},
            ),
            patch(
                "google_maps_pipeline.enrich_description_from_sources",
                return_value={
                    "description": generated_description,
                    "source_url": (
                        "https://vi.wikipedia.org/wiki/"
                        "L%C4%83ng_T%E1%BB%B1_%C4%90%E1%BB%A9c"
                    ),
                },
            ),
            patch("google_maps_pipeline.time.sleep"),
        ):
            result = enrich_google_maps_records(
                [{"source_id": "tuduc", "name": "Lăng Tự Đức", "images": []}],
                [{"source_id": "tuduc", "url": ""}],
                "Huế",
            )

        self.assertEqual(result[0]["description"], generated_description)

    def test_google_maps_poc_enrichment_uses_one_successful_maps_lookup(self):
        sync_api_module = ModuleType("playwright.sync_api")
        sync_playwright = MagicMock()
        sync_api_module.sync_playwright = sync_playwright
        playwright_module = ModuleType("playwright")
        playwright_module.sync_api = sync_api_module
        browser = Mock()
        context = Mock()
        browser.new_context.return_value = context
        context.new_page.return_value = Mock()
        sync_playwright.return_value.__enter__.return_value.chromium.launch.return_value = browser
        exact_url = "https://www.google.com/maps/place/lang-tu-duc"

        with (
            patch.dict(
                sys.modules,
                {"playwright": playwright_module, "playwright.sync_api": sync_api_module},
            ),
            patch(
                "google_maps_pipeline._load_google_maps_detail",
                return_value={
                    "description": None,
                    "images": [],
                    "place_category": "Di tích lịch sử",
                },
            ) as load_detail_mock,
            patch(
                "google_maps_pipeline.enrich_description_from_sources",
                return_value=None,
            ),
            patch("google_maps_pipeline.time.sleep"),
        ):
            result = enrich_google_maps_records(
                [
                    {
                        "source_id": "tuduc",
                        "name": "Lăng Tự Đức",
                        "latitude": 16.4326,
                        "longitude": 107.5665,
                        "images": [],
                    }
                ],
                [{"source_id": "tuduc", "url": exact_url}],
                "Huế",
                fast_poc_mode=True,
            )

        load_detail_mock.assert_called_once_with(context.new_page.return_value, exact_url)
        self.assertEqual(
            result[0]["description"],
            "Lăng Tự Đức là di tích lịch sử tại Huế.",
        )

    def test_google_maps_detail_navigation_accepts_only_google_place_urls(self):
        self.assertTrue(
            _is_google_maps_place_url(
                "https://www.google.com/maps/place/Bao-Tang/data=!4m1!3d12!4d109"
            )
        )
        self.assertFalse(_is_google_maps_place_url("http://www.google.com/maps/place/test"))
        self.assertFalse(_is_google_maps_place_url("https://example.com/maps/place/test"))

    @patch(
        "google_maps_pipeline._google_maps_detail_from_page",
        return_value={"description": "Place description", "images": []},
    )
    @patch("google_maps_pipeline._raise_if_google_blocked")
    @patch("google_maps_pipeline._accept_google_consent")
    def test_google_maps_detail_accepts_heading_attached_but_not_visible(
        self,
        _consent_mock,
        _blocked_mock,
        detail_mock,
    ):
        page = Mock()
        page.url = "https://www.google.com/maps/place/test"

        def require_attached_heading(_selector, **kwargs):
            if kwargs.get("state") != "attached":
                raise TimeoutError("heading is attached but hidden")

        page.wait_for_selector.side_effect = require_attached_heading

        result = _load_google_maps_detail(
            page,
            "https://www.google.com/maps/place/test",
        )

        self.assertEqual(result["description"], "Place description")
        detail_mock.assert_called_once_with(page)

    def test_google_maps_description_fallback_uses_actual_place_type(self):
        self.assertEqual(
            _fact_based_description(
                {"name": "Công viên Tuệ Tĩnh"},
                "Nha Trang",
                "Công viên",
            ),
            "Công viên Tuệ Tĩnh là công viên tại Nha Trang.",
        )

    def test_google_maps_description_fallback_remains_factual_without_place_type(self):
        self.assertEqual(
            _fact_based_description(
                {"name": "Quảng trường Thần Thoại"},
                "Nha Trang",
            ),
            "Quảng trường Thần Thoại là một địa điểm tại Nha Trang.",
        )


class DestinationDatabaseTests(unittest.TestCase):
    def test_existing_destination_coordinates_are_updated(self):
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = ("destination-id",)

        with patch("osm_pipeline.psycopg2", Mock()) as psycopg2_mock:
            psycopg2_mock.connect.return_value = connection
            result = get_or_create_destination(
                "Nha Trang",
                "12.245071,109.194317",
                {"dbname": "test"},
            )

        self.assertEqual(result, "destination-id")
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertIn("UPDATE destinations", cursor.execute.call_args_list[1].args[0])
        self.assertEqual(
            cursor.execute.call_args_list[1].args[1][1],
            "Mi\u1ec1n Trung (Central Vietnam)",
        )
        connection.commit.assert_called_once_with()

    def test_google_maps_attraction_requires_vietnamese_name(self):
        context = {
            "mode": "radius",
            "latitude": 12.24,
            "longitude": 109.19,
            "radius_meters": 20_000,
        }
        candidate = {
            "source_id": "0xabc:0xdef",
            "name": "Robinson Beach Nha Trang",
            "category": "Nature & outdoor",
            "latitude": 12.24,
            "longitude": 109.19,
        }

        self.assertIsNone(
            normalize_google_maps_candidate(candidate, "destination-id", context)
        )

    def test_google_maps_candidate_uses_vietnamese_name_and_geofilter(self):
        context = {
            "mode": "radius",
            "latitude": 12.24,
            "longitude": 109.19,
            "radius_meters": 20_000,
        }
        candidate = {
            "source_id": "0xabc:0xdef",
            "name": "Tháp Bà Ponagar",
            "category": "Museums & culture",
            "latitude": 12.2653665,
            "longitude": 109.1953678,
            "rating": 4.5,
            "image": "https://lh3.googleusercontent.com/place-photo=w114-h86-k-no",
            "description": "Ngôi đền trên triền núi với đồ trưng bày",
        }

        result = normalize_google_maps_candidate(
            candidate,
            "destination-id",
            context,
        )

        self.assertEqual(result["name"], "Tháp Bà Ponagar")
        self.assertEqual(result["source"], "google_maps_poc")
        self.assertEqual(result["coordinates"], "12.2653665,109.1953678")
        self.assertEqual(
            result["images"],
            ["https://lh3.googleusercontent.com/place-photo=w1200-h905-k-no"],
        )

    def test_google_maps_candidate_cleans_name_before_enrichment(self):
        context = {
            "mode": "radius",
            "latitude": 12.24,
            "longitude": 109.19,
            "radius_meters": 20_000,
        }
        candidate = {
            "source_id": "restaurant-mixed-name",
            "name": (
                "Huyền Hương Cơm Bắc, Cơm Niêu Restaurant "
                "후엔흐엉 북부밥 및 나짱 뚝배기밥"
            ),
            "category": "Restaurants & cafes",
            "latitude": 12.23767,
            "longitude": 109.1899056,
        }

        result = normalize_google_maps_candidate(
            candidate,
            "destination-id",
            context,
        )

        self.assertEqual(
            result["name"],
            "Huyền Hương Cơm Bắc, Cơm Niêu Restaurant",
        )

    def test_google_maps_enrichment_searches_clean_name_before_exact_url(self):
        exact_url = "https://www.google.com/maps/place/huyen-huong"
        urls = _google_maps_enrichment_urls(
            {
                "name": "Huyền Hương Restaurant 후엔흐엉",
                "latitude": 12.23767,
                "longitude": 109.1899056,
            },
            exact_url,
            "Nha Trang",
        )

        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].startswith("https://www.google.com/maps/search/"))
        self.assertIn("Huy%E1%BB%81n%20H%C6%B0%C6%A1ng%20Restaurant", urls[0])
        self.assertNotIn("%ED%9B%84%EC%97%94", urls[0])
        self.assertEqual(urls[1], exact_url)

    def test_google_maps_poc_enrichment_prefers_exact_url_before_name_search(self):
        exact_url = "https://www.google.com/maps/place/huyen-huong"

        urls = _google_maps_enrichment_urls(
            {
                "name": "Huyền Hương Restaurant 후엔흉",
                "latitude": 12.23767,
                "longitude": 109.1899056,
            },
            exact_url,
            "Nha Trang",
            prefer_exact_place=True,
        )

        self.assertEqual(urls[0], exact_url)
        self.assertTrue(urls[1].startswith("https://www.google.com/maps/search/"))

    @patch(
        "google_maps_pipeline.enrich_google_maps_records",
        side_effect=lambda records, candidates, destination_name, **kwargs: records,
    )
    def test_google_maps_poc_normalization_drops_stale_card_description(
        self,
        enrich_mock,
    ):
        result = normalize_google_maps_candidates(
            [
                {
                    "source_id": "place-1",
                    "name": "Tháp Bà Ponagar",
                    "description": (
                        "Card text that looks long enough to pass the general "
                        "description quality filter but is not editorial content."
                    ),
                    "category": "Museums & culture",
                    "latitude": 12.2653665,
                    "longitude": 109.1953678,
                    "rating": 4.7,
                    "image": (
                        "https://lh3.googleusercontent.com/"
                        "place-photo=w114-h86-k-no"
                    ),
                }
            ],
            "destination-id",
            "Nha Trang",
            1,
            fast_poc_mode=True,
        )

        self.assertIsNone(result[0]["description"])
        self.assertEqual(result[0]["rating"], 4.7)
        self.assertEqual(len(result[0]["images"]), 1)
        self.assertTrue(enrich_mock.call_args.kwargs["fast_poc_mode"])

    def test_google_maps_candidate_rejects_outside_destination(self):
        context = {
            "mode": "radius",
            "latitude": 12.24,
            "longitude": 109.19,
            "radius_meters": 1_000,
        }
        candidate = {
            "source_id": "outside",
            "name": "Đảo Hòn Tằm",
            "category": "Nature & outdoor",
            "latitude": 12.1789019,
            "longitude": 109.245158,
        }

        self.assertIsNone(
            normalize_google_maps_candidate(candidate, "destination-id", context)
        )

    @patch(
        "google_maps_pipeline.enrich_google_maps_records",
        side_effect=lambda records, candidates, destination_name, **kwargs: records,
    )
    @patch("google_maps_pipeline.scrape_google_maps_candidates")
    def test_google_maps_collection_keeps_restaurants_without_vietnamese_diacritics(
        self,
        scrape_mock,
        enrich_mock,
    ):
        scrape_mock.return_value = [
            {
                "source_id": "restaurant-1",
                "name": "Lanterns",
                "category": "Restaurants & cafes",
                "latitude": 12.24,
                "longitude": 109.19,
            }
        ]
        context = {
            "mode": "radius",
            "latitude": 12.24,
            "longitude": 109.19,
            "radius_meters": 20_000,
        }

        result = collect_google_maps_attractions(
            "Nha Trang",
            context,
            "destination-id",
            1,
        )

        self.assertEqual([item["name"] for item in result], ["Lanterns"])
        self.assertEqual(len(enrich_mock.call_args.args[0]), 1)

    @patch(
        "google_maps_pipeline.enrich_google_maps_records",
        side_effect=lambda records, candidates, destination_name, **kwargs: records,
    )
    @patch("google_maps_pipeline.scrape_google_maps_candidates")
    def test_google_maps_collection_enriches_only_selected_records(
        self,
        scrape_mock,
        enrich_mock,
    ):
        names = ["Nhà hàng Biển Xanh", "Quán Tre", "Bếp Nhà", "Cơm Niêu"]
        scrape_mock.return_value = [
            {
                "source_id": f"place-{index}",
                "name": names[index],
                "category": "Restaurants & cafes",
                "latitude": 12.24 + index / 100,
                "longitude": 109.19,
                "url": f"https://www.google.com/maps/place/restaurant-{index}",
            }
            for index in range(4)
        ]
        context = {
            "mode": "radius",
            "latitude": 12.24,
            "longitude": 109.19,
            "radius_meters": 20_000,
        }

        result = collect_google_maps_attractions(
            "Nha Trang",
            context,
            "destination-id",
            2,
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(len(enrich_mock.call_args.args[0]), 2)
        self.assertEqual(len(enrich_mock.call_args.args[1]), 4)
        self.assertEqual(enrich_mock.call_args.args[2], "Nha Trang")


class AirflowDiscoveryTests(unittest.TestCase):
    def test_hotel_nearby_dag_logs_lifecycle_events_for_every_pipeline_block(self):
        content = (PIPELINE_DIR / "hotel_nearby_dag.py").read_text(encoding="utf-8")

        for stage in (
            "data_source",
            "extract",
            "validate_clean",
            "normalize",
            "deduplicate",
            "load",
            "quality_check",
        ):
            self.assertIn(f"stage={stage} event=start", content)
            self.assertIn(f"stage={stage} event=complete", content)

    def test_hotel_nearby_dag_skips_database_load_when_no_records_are_produced(self):
        content = (PIPELINE_DIR / "hotel_nearby_dag.py").read_text(encoding="utf-8")

        self.assertIn('if not records:', content)
        self.assertIn('No valid hotel-nearby attractions to load', content)

    def test_location_coordinates_param_is_nullable_and_defaults_to_none(self):
        param_kwargs = optional_location_coords_param_kwargs()

        self.assertIsNone(param_kwargs["default"])
        self.assertEqual(param_kwargs["type"], ["null", "string"])

    def test_support_modules_are_excluded_from_dag_discovery(self):
        ignore_file = PIPELINE_DIR / ".airflowignore"
        patterns = {
            line.strip()
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertEqual(
            patterns,
            {
                "attraction_utils.py",
                "dag_common.py",
                "destination_geo.py",
                "osm_pipeline.py",
                "ota_pipeline.py",
                "google_maps_pipeline.py",
                "hotel_pipeline.py",
                "hotel_nearby_pipeline.py",
                "pipeline_stages.py",
            },
        )

    def test_pipeline_dags_disable_automatic_return_value_xcom(self):
        for dag_file in (
            "osm_dag.py",
            "ota_dag.py",
            "google_maps_dag.py",
            "combined_dag.py",
            "hotel_nearby_dag.py",
            "hotel_dag.py",
        ):
            content = (PIPELINE_DIR / dag_file).read_text(encoding="utf-8")
            self.assertIn('"do_xcom_push": False', content, dag_file)

    def test_hotel_loader_dag_orchestrates_pipeline_without_inline_stage_logic(self):
        content = (PIPELINE_DIR / "hotel_dag.py").read_text(encoding="utf-8")

        for task_id in (
            "extract",
            "validate",
            "normalize",
            "dedupe",
            "physical_match",
            "load_to_postgresql",
            "load_to_supabase",
            "quality_check",
            "sync_qdrant",
        ):
            self.assertIn(f'task_id="{task_id}"', content)

        for function_name in (
            "extract_hotels",
            "validate_hotels",
            "normalize_hotels",
            "dedupe_hotels",
            "assign_physical_hotel_groups",
            "load_hotels_to_db",
            "load_hotels_to_supabase_task",
            "quality_check_hotels",
            "upsert_hotels",
        ):
            self.assertIn(function_name, content)

        # Whitespace-insensitive check of the actual chain order (the source
        # wraps `>>` across multiple lines), not just substring presence.
        normalized_chain = " ".join(content.split())
        self.assertIn(
            "extract >> validate >> normalize >> dedupe >> physical_match "
            ">> load_to_postgresql >> load_to_supabase >> quality_check >> sync_qdrant",
            normalized_chain,
        )

        self.assertIn('dag_id="booking_agoda_hotel_loader_pipeline"', content)
        self.assertIn('"agoda_path": Param(', content)
        self.assertIn('"booking_path": Param(', content)
        self.assertIn('"/opt/airflow/data"', content)
        self.assertIn('"/opt/airflow/logs/reports"', content)


class OtaParserTests(unittest.TestCase):
    def test_agoda_uses_installed_browser_identity(self):
        options = _agoda_browser_context_options()

        self.assertEqual(options, {"locale": "en-GB"})
        self.assertNotIn("user_agent", options)

    def test_ota_collection_requires_explicit_opt_in(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OTA web scraping is disabled"):
                collect_ota_attractions(
                    destination_name="Nha Trang",
                    location_context={"mode": "radius"},
                    destination_id="destination-id",
                    item_limit=1,
                )

    def test_booking_parser_extracts_public_product_fields(self):
        html = """
        <html><head>
          <meta name="description" content="A guided cultural experience in Nha Trang.">
        </head><body>
          <h1>Nha Trang Museum Admission</h1>
          <div data-testid="attraction-reviews">
            <span aria-label="User reviews, 4.6 out of 5 stars from 27 reviews"></span>
          </div>
          <section><h2>About this activity</h2><p>A guided cultural experience in Nha Trang.</p></section>
          <section><h2>Duration</h2><p>2 hours 30 minutes</p></section>
          <section><h2>Location</h2><address>10 Tran Phu, Nha Trang, Vietnam</address></section>
          <div>Current price from US$12.50</div>
          <img src="https://cf.bstatic.com/xdata/images/xphoto/500x375/sample.jpg">
          <script>
            {"latitude":"12.2731916","locationType":"arrival","longitude":"109.1757778"}
            {"latitude":12.23850155,"longitude":109.19517517,"ufi":-3723998}
          </script>
        </body></html>
        """

        result = parse_booking_html(
            html,
            "https://www.booking.com/attractions/vn/prabc123-nha-trang-museum.en-gb.html",
        )

        self.assertEqual(result["source"], "booking")
        self.assertEqual(result["source_id"], "prabc123")
        self.assertEqual(result["name"], "Nha Trang Museum Admission")
        self.assertEqual(result["category"], "Museums & culture")
        self.assertEqual(result["estimated_duration_minutes"], 150)
        self.assertEqual(result["rating"], 4.6)
        self.assertEqual(result["review_count"], 27)
        self.assertEqual(result["ticket_price_adult"], 12.50)
        self.assertEqual(result["address"], "10 Tran Phu, Nha Trang, Vietnam")
        self.assertEqual(result["latitude"], 12.2731916)
        self.assertEqual(result["longitude"], 109.1757778)
        self.assertEqual(len(result["images"]), 1)

    def test_agoda_parser_extracts_rendered_product_fields(self):
        html = """
        <html><body>
          <h1>Thang Long Water Puppet Theater Ticket</h1>
          <div>4.3 stars rating</div><div>(427 reviews)</div>
          <section><h2>At a glance</h2><p>1 hour (approx.)</p></section>
          <section><h2>Product Overview</h2><p>Traditional Vietnamese water puppetry.</p></section>
          <section><h2>Location</h2><address>57B Dinh Tien Hoang, Hanoi, Vietnam</address></section>
          <div>Starts from USD 13.00</div>
          <img src="https://cdn6.agoda.net/images/activity.jpg">
        </body></html>
        """

        result = parse_agoda_html(
            html,
            "https://www.agoda.com/activities/detail/vn/hanoi/water-puppet-797853",
        )

        self.assertEqual(result["source"], "agoda")
        self.assertEqual(result["source_id"], "797853")
        self.assertEqual(result["category"], "Entertainment & tickets")
        self.assertEqual(result["estimated_duration_minutes"], 60)
        self.assertEqual(result["rating"], 4.3)
        self.assertEqual(result["review_count"], 427)
        self.assertEqual(result["ticket_price_adult"], 13.00)
        self.assertEqual(result["address"], "57B Dinh Tien Hoang, Hanoi, Vietnam")

    def test_agoda_parser_supports_current_activity_id_urls(self):
        html = """
        <html><body>
          <h1>Nha Trang Island Tour</h1>
          <section><h2>Location</h2><address>Nha Trang, Khanh Hoa, Vietnam</address></section>
        </body></html>
        """
        url = (
            "https://www.agoda.com/en-gb/activities/detail"
            "?activityId=1177850&cityId=2679"
        )

        result = parse_agoda_html(html, url)

        self.assertEqual(result["source_id"], "1177850")

    def test_agoda_current_product_link_keeps_required_query_parameters(self):
        result = _canonical_agoda_product_url(
            "/en-gb/activities/detail?activityId=1177850&cityId=2679&utm_source=test"
        )

        self.assertEqual(
            result,
            "https://www.agoda.com/en-gb/activities/detail?activityId=1177850&cityId=2679",
        )
        self.assertIsNone(_canonical_agoda_product_url("/en-gb/activities"))

    def test_agoda_parser_ignores_ratings_from_related_products(self):
        html = """
        <html><body>
          <h1>Quiet Nha Trang Museum Admission</h1>
          <div>Product Overview</div>
          <div>Explore a locally curated museum collection in central Nha Trang.</div>
          <div>Highlights</div>
          <div>While you're exploring Nha Trang</div>
          <div>Unrelated Airport Fast Track</div>
          <div>Star rating 4.9</div><div>(284 reviews)</div>
          <img src="https://cdn6.agoda.net/images/mobile/flag-us@2x.png">
        </body></html>
        """

        result = parse_agoda_html(
            html,
            "https://www.agoda.com/en-gb/activities/detail?activityId=42&cityId=2679",
        )

        self.assertEqual(
            result["description"],
            "Explore a locally curated museum collection in central Nha Trang.",
        )
        self.assertIsNone(result["rating"])
        self.assertIsNone(result["review_count"])
        self.assertEqual(result["images"], [])

    @patch("ota_pipeline.geocode_address", return_value=(12.2, 109.2))
    def test_fixed_place_without_address_is_geocoded_by_product_name(self, geocode_mock):
        candidates = [
            {
                "source": "agoda",
                "name": "Nha Trang Ocean Museum Admission",
                "address": "",
                "is_tour": False,
            }
        ]
        context = {
            "mode": "boundary",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[109.0, 12.0], [109.4, 12.0], [109.4, 12.4], [109.0, 12.4], [109.0, 12.0]]
                ],
            },
        }

        result = geofilter_ota_candidates(candidates, "Nha Trang", context)

        self.assertEqual(len(result), 1)
        geocode_mock.assert_called_once_with("Nha Trang Ocean Museum Admission", "Nha Trang")

    @patch("ota_pipeline.geocode_address")
    def test_source_coordinates_are_preferred_over_title_geocoding(self, geocode_mock):
        candidates = [
            {
                "source": "booking",
                "name": "I Resort Nha Trang Mud Bath Experience",
                "address": "Hot mineral springs I-Resort Nha Trang",
                "is_tour": False,
                "latitude": 12.2731916,
                "longitude": 109.1757778,
            }
        ]
        context = {
            "mode": "boundary",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[109.1, 12.2], [109.3, 12.2], [109.3, 12.4], [109.1, 12.4], [109.1, 12.2]]
                ],
            },
        }

        result = geofilter_ota_candidates(candidates, "Nha Trang", context)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["latitude"], 12.2731916)
        self.assertEqual(result[0]["longitude"], 109.1757778)
        geocode_mock.assert_not_called()

    @patch(
        "ota_pipeline.scrape_google_maps_coordinates",
        return_value={"Royal Salon Nha Trang": (12.2416878, 109.1914417)},
    )
    @patch("ota_pipeline.geocode_address", return_value=None)
    def test_fixed_place_uses_scraped_map_coordinates_after_geocoding_miss(
        self,
        geocode_mock,
        maps_mock,
    ):
        candidates = [
            {
                "source": "agoda",
                "name": "Royal Salon Nha Trang",
                "address": "",
                "is_tour": False,
                "latitude": None,
                "longitude": None,
            }
        ]
        context = {
            "mode": "boundary",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[109.1, 12.2], [109.3, 12.2], [109.3, 12.4], [109.1, 12.4], [109.1, 12.2]]
                ],
            },
        }

        result = geofilter_ota_candidates(candidates, "Nha Trang", context)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["latitude"], 12.2416878)
        self.assertEqual(result[0]["longitude"], 109.1914417)
        geocode_mock.assert_called_once_with("Royal Salon Nha Trang", "Nha Trang")
        maps_mock.assert_called_once_with(candidates, "Nha Trang")

    @patch("ota_pipeline.geocode_address")
    def test_tour_without_specific_location_is_rejected(self, geocode_mock):
        result = geofilter_ota_candidates(
            [{"source": "agoda", "name": "Nha Trang Day Tour", "address": "", "is_tour": True}],
            "Nha Trang",
            {"mode": "boundary", "geometry": {"type": "Polygon", "coordinates": []}},
        )

        self.assertEqual(result, [])
        geocode_mock.assert_not_called()

    @patch("ota_pipeline.geocode_address")
    def test_snorkeling_departure_coordinates_are_not_treated_as_attraction_location(
        self,
        geocode_mock,
    ):
        html = """
        <html><body>
          <h1>Nha Trang Half-Day Snorkeling Adventure with BBQ Onboard</h1>
          <h2>Location</h2>
          <div>Departure point</div>
          <div>Nha Trang Tourist Pier, Nha Trang, Vietnam</div>
          <script>
            {"latitude":"12.1996875","locationType":"departure","longitude":"109.2015625"}
          </script>
        </body></html>
        """
        candidate = parse_booking_html(
            html,
            "https://www.booking.com/attractions/vn/prsnorkel123-snorkeling.en-gb.html",
        )
        context = {
            "mode": "boundary",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[109.1, 12.1], [109.3, 12.1], [109.3, 12.3], [109.1, 12.3], [109.1, 12.1]]
                ],
            },
        }

        result = geofilter_ota_candidates([candidate], "Nha Trang", context)

        self.assertTrue(candidate["is_tour"])
        self.assertEqual(result, [])
        geocode_mock.assert_not_called()

    def test_booking_parser_ignores_unrelated_time_values(self):
        html = """
        <html><body>
          <h1>Ba Na Hills Evening Tour</h1>
          <p>Guests must be 18 years old and arrive 15 minutes before departure.</p>
          <h2>Location</h2>
          <div>Departure point</div>
          <div>Da Nang Downtown, 2/9 Street, Hai Chau, Da Nang, 550000</div>
          <h2>User ratings</h2>
        </body></html>
        """

        result = parse_booking_html(
            html,
            "https://www.booking.com/attractions/vn/prtour123-ba-na-hills.en-gb.html",
        )

        self.assertIsNone(result["estimated_duration_minutes"])
        self.assertEqual(result["location_kind"], "Departure point")
        self.assertEqual(
            result["address"],
            "Da Nang Downtown, 2/9 Street, Hai Chau, Da Nang, 550000",
        )


class SelectionTests(unittest.TestCase):
    def test_cross_source_physical_duplicates_are_merged(self):
        candidates = [
            {
                "source": "booking",
                "source_id": "pr1",
                "name": "Nha Trang Ocean Museum Admission",
                "category": "Museums & culture",
                "is_tour": False,
                "latitude": 12.2070,
                "longitude": 109.2140,
                "description": "Short",
                "images": [],
                "review_count": 10,
            },
            {
                "source": "agoda",
                "source_id": "22",
                "name": "Nha Trang Ocean Museum Ticket",
                "category": "Museums & culture",
                "is_tour": False,
                "latitude": 12.2071,
                "longitude": 109.2141,
                "description": "A much more complete description",
                "images": ["https://example.com/museum.jpg"],
                "review_count": 30,
            },
        ]

        result = deduplicate_attractions(candidates)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["review_count"], 30)
        self.assertEqual(result[0]["images"], ["https://example.com/museum.jpg"])

    def test_nearby_physical_name_variants_are_merged(self):
        candidates = [
            {
                "source": "osm",
                "source_id": "1",
                "name": "Po Nagar Cham Towers",
                "category": "Museums & culture",
                "is_tour": False,
                "latitude": 12.2650,
                "longitude": 109.1950,
            },
            {
                "source": "booking",
                "source_id": "2",
                "name": "Po Nagar Towers Admission",
                "category": "Museums & culture",
                "is_tour": False,
                "latitude": 12.2651,
                "longitude": 109.1951,
            },
        ]

        result = deduplicate_attractions(candidates)

        self.assertEqual(len(result), 1)

    def test_diversity_selection_round_robins_categories(self):
        candidates = []
        for index in range(6):
            candidates.append(
                {
                    "name": f"Tour {index}",
                    "category": "Sightseeing tours",
                    "review_count": 100 - index,
                }
            )
        candidates.extend(
            [
                {"name": "Museum", "category": "Museums & culture", "review_count": 20},
                {"name": "Waterfall", "category": "Nature & outdoor", "review_count": 10},
            ]
        )

        selected = select_diverse_attractions(candidates, limit=4)

        self.assertEqual(len(selected), 4)
        self.assertIn("Museums & culture", {item["category"] for item in selected})
        self.assertIn("Nature & outdoor", {item["category"] for item in selected})
        self.assertLessEqual(
            sum(item["category"] == "Sightseeing tours" for item in selected),
            2,
        )

    def test_soft_category_cap_relaxes_evenly_to_fill_limit(self):
        candidates = []
        for index in range(10):
            candidates.append(
                {
                    "name": f"Other {index}",
                    "category": "Other activities",
                    "description": "high quality description " * 10,
                }
            )
            candidates.append(
                {
                    "name": f"Museum {index}",
                    "category": "Museums & culture",
                }
            )

        selected = select_diverse_attractions(candidates, limit=10)
        counts = {
            category: sum(item["category"] == category for item in selected)
            for category in {item["category"] for item in selected}
        }

        self.assertEqual(counts, {"Museums & culture": 5, "Other activities": 5})


class OsmTransformTests(unittest.TestCase):
    @patch("osm_pipeline.time.sleep")
    @patch("osm_pipeline.fetch_wikidata_details", return_value={})
    @patch("osm_pipeline.fetch_wikipedia_details", return_value={})
    @patch("osm_pipeline.fetch_osm_attractions")
    def test_osm_collection_requires_vietnamese_attraction_names_and_rejects_aircraft(
        self,
        fetch_mock,
        wikipedia_mock,
        wikidata_mock,
        sleep_mock,
    ):
        fetch_mock.return_value = [
            {
                "id": 13508160125,
                "type": "node",
                "lat": 12.2343077,
                "lon": 109.1932702,
                "tags": {
                    "name": "Bell UH-1 Iroquois",
                    "name:vi": "Trực thăng Bell UH-1 Iroquois",
                    "historic": "aircraft",
                    "aircraft:type": "helicopter",
                },
            },
            {
                "id": 2,
                "type": "node",
                "lat": 12.24,
                "lon": 109.19,
                "tags": {"name": "English-only Museum", "tourism": "museum"},
            },
            {
                "id": 3,
                "type": "node",
                "lat": 12.25,
                "lon": 109.20,
                "tags": {
                    "name": "Po Nagar Cham Towers",
                    "name:vi": "Tháp Bà Po Nagar",
                    "tourism": "attraction",
                },
            },
            {
                "id": 4,
                "type": "node",
                "lat": 12.23,
                "lon": 109.20,
                "tags": {"name": "Lanterns", "amenity": "restaurant"},
            },
        ]
        context = {
            "mode": "radius",
            "latitude": 12.2,
            "longitude": 109.2,
            "radius_meters": 20_000,
        }

        result = collect_osm_attractions("Nha Trang", context, "destination-id", 4)

        self.assertEqual(
            {item["name"] for item in result},
            {"Tháp Bà Po Nagar", "Lanterns"},
        )

    def test_overpass_query_filters_vietnamese_attractions_and_aircraft(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"elements": []}
        post_mock = Mock(return_value=response)

        with patch("osm_pipeline.requests", Mock(post=post_mock)):
            fetch_osm_attractions("12.2,109.2", radius_meters=20_000, limit=20)

        query = post_mock.call_args.kwargs["data"].decode("utf-8")
        self.assertIn('["name:vi"]', query)
        self.assertIn('["historic"!~"aircraft|airplane"]', query)
        self.assertIn(
            'nwr["amenity"~"restaurant|cafe|bar"]["name"]',
            query,
        )

    def test_osm_tags_are_authoritative_for_category(self):
        cases = (
            ({"name": "Lantern", "amenity": "restaurant"}, "Restaurants & cafes"),
            ({"name": "Alexandre", "tourism": "museum"}, "Museums & culture"),
            ({"name": "Safari Land", "tourism": "zoo"}, "Entertainment & tickets"),
            ({"name": "Hon Ba", "natural": "peak"}, "Nature & outdoor"),
        )
        for tags, expected_category in cases:
            with self.subTest(tags=tags):
                result = transform_to_attraction(
                    {"id": 1, "type": "node", "lat": 12.2, "lon": 109.2, "tags": tags},
                    {},
                    "destination-id",
                    {},
                )
                self.assertEqual(result["category"], expected_category)

    def test_osm_relation_retains_center_coordinates(self):
        result = transform_to_attraction(
            {
                "id": 99,
                "type": "relation",
                "center": {"lat": 12.25, "lon": 109.19},
                "tags": {"name": "Protected Garden", "leisure": "garden"},
            },
            {},
            "destination-id",
            {},
        )

        self.assertEqual(result["coordinates"], "12.25,109.19")
        self.assertEqual(result["latitude"], 12.25)
        self.assertEqual(result["longitude"], 109.19)

    def test_osm_source_id_keeps_element_type_namespace(self):
        node = transform_to_attraction(
            {
                "id": 7,
                "type": "node",
                "lat": 12.2,
                "lon": 109.2,
                "tags": {"name": "North Garden", "leisure": "garden"},
            },
            {},
            "destination-id",
            {},
        )
        way = transform_to_attraction(
            {
                "id": 7,
                "type": "way",
                "center": {"lat": 12.3, "lon": 109.3},
                "tags": {"name": "South Garden", "leisure": "garden"},
            },
            {},
            "destination-id",
            {},
        )

        self.assertEqual(node["source_id"], "node:7")
        self.assertEqual(way["source_id"], "way:7")
        self.assertEqual(len(deduplicate_attractions([node, way])), 2)

    @patch("osm_pipeline.time.sleep")
    @patch("osm_pipeline.fetch_wikidata_details", return_value={})
    @patch("osm_pipeline.fetch_wikipedia_details", return_value={})
    @patch("osm_pipeline.fetch_osm_attractions")
    def test_osm_collection_deduplicates_and_keeps_food_candidates(
        self,
        fetch_mock,
        wikipedia_mock,
        wikidata_mock,
        sleep_mock,
    ):
        fetch_mock.return_value = [
            {
                "id": 1,
                "type": "node",
                "lat": 12.2000,
                "lon": 109.2000,
                "tags": {
                    "name": "Twin View",
                    "name:vi": "Điểm ngắm đôi",
                    "tourism": "viewpoint",
                },
            },
            {
                "id": 2,
                "type": "way",
                "center": {"lat": 12.2001, "lon": 109.2001},
                "tags": {
                    "name": "Twin View",
                    "name:vi": "Điểm ngắm đôi",
                    "tourism": "viewpoint",
                },
            },
            {
                "id": 3,
                "type": "node",
                "lat": 12.2100,
                "lon": 109.2100,
                "tags": {
                    "name": "Silver",
                    "name:vi": "Thác Bạc",
                    "natural": "waterfall",
                },
            },
            {
                "id": 4,
                "type": "node",
                "lat": 12.2200,
                "lon": 109.2200,
                "tags": {"name": "Lantern", "amenity": "restaurant"},
            },
        ]
        context = {
            "mode": "radius",
            "latitude": 12.2,
            "longitude": 109.2,
            "radius_meters": 20_000,
        }

        result = collect_osm_attractions("Nha Trang", context, "destination-id", 4)

        self.assertEqual(len(result), 3)
        self.assertEqual(
            {item["name"] for item in result},
            {"Điểm ngắm đôi", "Thác Bạc", "Lantern"},
        )
        self.assertIn("Restaurants & cafes", {item["category"] for item in result})

    @patch("osm_pipeline.time.sleep")
    @patch("osm_pipeline.fetch_wikidata_details", return_value={})
    @patch("osm_pipeline.fetch_wikipedia_details", return_value={})
    @patch("osm_pipeline.fetch_osm_attractions")
    def test_osm_collection_does_not_stop_before_food_output(
        self,
        fetch_mock,
        wikipedia_mock,
        wikidata_mock,
        sleep_mock,
    ):
        attractions = [
            {
                "id": index,
                "type": "node",
                "lat": 12.20 + index / 10_000,
                "lon": 109.20,
                "tags": {
                    "name": f"Sight {index}",
                    "name:vi": f"Điểm tham quan {index}",
                    "tourism": "attraction",
                },
            }
            for index in range(1, 7)
        ]
        food = [
            {
                "id": 100 + index,
                "type": "node",
                "lat": 12.21 + index / 10_000,
                "lon": 109.21,
                "tags": {"name": f"Kitchen {index}", "amenity": "restaurant"},
            }
            for index in range(2)
        ]
        fetch_mock.return_value = attractions + food
        context = {
            "mode": "radius",
            "latitude": 12.2,
            "longitude": 109.2,
            "radius_meters": 20_000,
        }

        result = collect_osm_attractions("Nha Trang", context, "destination-id", 2)

        self.assertIn("Restaurants & cafes", {item["category"] for item in result})

    @patch("osm_pipeline.time.sleep")
    def test_overpass_attraction_query_retries_after_gateway_timeout(
        self,
        sleep_mock,
    ):
        failed_response = Mock()
        failed_response.raise_for_status.side_effect = RuntimeError("504 Gateway Timeout")
        successful_response = Mock()
        successful_response.raise_for_status.return_value = None
        successful_response.json.return_value = {
            "elements": [
                {"id": element_id, "type": "node"}
                for element_id in range(1, 6)
            ]
        }
        post_mock = Mock(side_effect=[failed_response, successful_response])

        with patch("osm_pipeline.requests", Mock(post=post_mock)):
            result = fetch_osm_attractions("12.2,109.2", radius_meters=20_000, limit=20)

        self.assertEqual({item["id"] for item in result}, {1, 2, 3, 4, 5})
        self.assertEqual(post_mock.call_count, 2)
        sleep_mock.assert_called_once()

    def test_osm_transform_does_not_invent_ratings(self):
        element = {
            "id": 123,
            "type": "node",
            "lat": 12.2,
            "lon": 109.2,
            "tags": {"name": "Local History Museum", "tourism": "museum"},
        }

        result = transform_to_attraction(element, {}, "destination-id", {})

        self.assertIsNone(result["rating"])
        self.assertIsNone(result["review_count"])
        self.assertEqual(result["category"], "Museums & culture")
        self.assertEqual(result["source"], "osm")
        self.assertEqual(result["source_id"], "node:123")
        self.assertEqual(result["latitude"], 12.2)
        self.assertEqual(result["longitude"], 109.2)


if __name__ == "__main__":
    unittest.main()
