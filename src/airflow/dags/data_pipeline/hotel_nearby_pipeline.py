"""Source-specific hotel-surroundings extraction for the public Maps POC."""

import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urlparse, urlunparse

try:
    import psycopg2
except ImportError:  # Allows parser tests to run outside the Airflow image.
    psycopg2 = None

from attraction_utils import is_coordinate_allowed, normalize_text, parse_coordinates, sanitize_attraction_name
from dag_common import DB_KWARGS
from google_maps_pipeline import resolve_google_maps_nearby_candidates


BOOKING_HOSTS = ("booking.com",)
AGODA_HOSTS = ("agoda.com",)
BLOCKING_MARKERS = ("verify you are human", "unusual traffic", "access denied", "captcha")
SURROUNDINGS_UI_MARKERS = (
    "show map",
    "guests loved walking around",
    "great location",
)
TRAILING_DISTANCE_PATTERN = re.compile(
    r"\s+\d+(?:[.,]\d+)?\s*"
    r"(?:m|km|mi|yd|mile(?:s)?|yard(?:s)?)\s*$",
    re.IGNORECASE,
)


class _SurroundingsParser(HTMLParser):
    """Keep list/link labels together with the nearest section heading."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_heading = ""
        self.entries: List[Tuple[str, str]] = []
        self._captures: List[Dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, str]]) -> None:
        if tag in {"h2", "h3", "h4"}:
            self._captures.append({"tag": tag, "kind": "heading", "parts": []})
        elif tag in {"li", "a"}:
            self._captures.append(
                {
                    "tag": tag,
                    "kind": "entry",
                    "heading": self.current_heading,
                    "parts": [],
                }
            )

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            for capture in self._captures:
                capture["parts"].append(value)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._captures) - 1, -1, -1):
            capture = self._captures[index]
            if capture["tag"] != tag:
                continue
            self._captures.pop(index)
            value = " ".join(capture["parts"]).strip()
            if capture["kind"] == "heading" and value:
                self.current_heading = value
            elif capture["kind"] == "entry" and value:
                self.entries.append((str(capture["heading"]), value))
            return


def _matches_host(url: str, hosts: Sequence[str]) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return any(hostname == host or hostname.endswith(f".{host}") for host in hosts)


def hotel_source_name(url: str) -> str:
    if _matches_host(url, BOOKING_HOSTS):
        return "booking"
    if _matches_host(url, AGODA_HOSTS):
        return "agoda"
    return ""


def canonical_booking_hotel_url(url: str) -> str | None:
    """Add Booking's Vietnam path and Vietnamese locale, omitting volatile parameters."""
    if not _matches_host(url, BOOKING_HOSTS):
        return None
    parsed = urlparse(url)
    if parsed.path.startswith("/hotel/vn/"):
        path = parsed.path
    elif parsed.path.startswith("/hotel/"):
        hotel_slug = parsed.path.removeprefix("/hotel/").lstrip("/")
        if not hotel_slug or "/" in hotel_slug:
            return None
        path = f"/hotel/vn/{hotel_slug}"
    else:
        return None
    return urlunparse(("https", "www.booking.com", path, "", "lang=vi", ""))


def _surrounding_names(
    html: str,
    hotel_name: str,
    heading_markers: Sequence[str],
    excluded_heading_markers: Sequence[str] = (),
) -> List[str]:
    parser = _SurroundingsParser()
    parser.feed(html or "")
    hotel_key = normalize_text(hotel_name)
    names: List[str] = []
    seen = set()
    markers = tuple(normalize_text(marker) for marker in heading_markers)
    excluded_markers = tuple(
        normalize_text(marker) for marker in excluded_heading_markers
    )
    for heading, value in parser.entries:
        normalized_heading = normalize_text(heading)
        if (
            any(marker in normalized_heading for marker in excluded_markers)
            or not any(marker in normalized_heading for marker in markers)
        ):
            continue
        name = sanitize_attraction_name(
            TRAILING_DISTANCE_PATTERN.sub("", value).strip()
        )
        normalized = normalize_text(name)
        if (
            not name
            or normalized == hotel_key
            or len(name) < 3
            or any(marker in normalized for marker in SURROUNDINGS_UI_MARKERS)
            or re.fullmatch(r"\d+(?:[.,]\d+)?\s*(?:m|km)", normalized)
            or normalized in seen
        ):
            continue
        seen.add(normalized)
        names.append(name)
    return names


def extract_booking_surrounding_names(html: str, hotel_name: str) -> List[str]:
    """Parse Booking's property-surroundings section without generated CSS selectors."""
    return _surrounding_names(
        html,
        hotel_name,
        (
            "property surroundings",
            "hotel surroundings",
            "xung quanh khách sạn",
            "what's nearby",
            "whats nearby",
            "top attractions",
            "restaurants & cafes",
            "natural beauty",
            "xung quanh có gì",
            "địa điểm tham quan hàng đầu",
            "nhà hàng & quán cà phê",
            "cảnh đẹp thiên nhiên",
        ),
        (
            "public transport",
            "closest airports",
            "airport",
            "phương tiện công cộng",
            "các sân bay gần nhất",
            "sân bay",
        ),
    )


def extract_agoda_surrounding_names(html: str, hotel_name: str) -> List[str]:
    """Parse Agoda's nearby-landmarks section without sharing Booking's layout rules."""
    return _surrounding_names(
        html,
        hotel_name,
        ("popular landmarks", "nearby attractions", "nearby landmarks", "what's nearby", "whats nearby"),
        ("public transport", "closest airports", "airport"),
    )


def _classify_nearby_name(name: str) -> str:
    normalized = normalize_text(name)
    if any(term in normalized for term in ("bảo tàng", "museum", "di tích", "heritage")):
        return "Museums & culture"
    if any(term in normalized for term in ("bãi biển", "beach", "đảo", "island", "công viên", "park", "thác", "waterfall")):
        return "Nature & outdoor"
    if any(term in normalized for term in ("chợ", "market", "nhà hát", "theater", "theatre", "vui chơi")):
        return "Entertainment & tickets"
    return "Other activities"


def _coordinates_from_hotel(value: Any) -> Tuple[float, float] | None:
    try:
        return parse_coordinates(str(value or ""))
    except (TypeError, ValueError):
        return None


def fetch_hotel_sources(
    destination_id: str,
    hotel_id: str = "",
) -> List[Dict[str, Any]]:
    """Load one selected hotel or all positioned destination hotels with OTA URLs."""
    if psycopg2 is None:
        raise RuntimeError("PostgreSQL driver is unavailable in this environment.")
    query = """
        SELECT id::text, name, coordinates, source_urls
        FROM hotels
        WHERE destination_id = %s
          AND coordinates IS NOT NULL
          AND source_urls IS NOT NULL
    """
    arguments: List[Any] = [destination_id]
    if hotel_id:
        query += " AND id::text = %s"
        arguments.append(hotel_id)
    query += " ORDER BY updated_at DESC NULLS LAST, id"
    connection = psycopg2.connect(**DB_KWARGS)
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, tuple(arguments))
            rows = cursor.fetchall()
    finally:
        connection.close()

    hotels: List[Dict[str, Any]] = []
    for hotel_id, name, coordinates, source_urls in rows:
        point = _coordinates_from_hotel(coordinates)
        if not point:
            continue
        for url in source_urls or []:
            source = hotel_source_name(str(url))
            if source:
                source_url = (
                    canonical_booking_hotel_url(str(url))
                    if source == "booking"
                    else str(url)
                )
                if not source_url:
                    continue
                hotels.append(
                    {
                        "hotel_id": hotel_id,
                        "hotel_name": name,
                        "hotel_latitude": point[0],
                        "hotel_longitude": point[1],
                        "source": source,
                        "source_url": source_url,
                    }
                )
                break
    return hotels


def _attraction_name_key(value: Any) -> str:
    return normalize_text(sanitize_attraction_name(str(value or "")))


def fetch_existing_attraction_name_keys(destination_id: str) -> set[str]:
    """Return normalized names already stored for this destination."""
    if psycopg2 is None:
        raise RuntimeError("PostgreSQL driver is unavailable in this environment.")
    connection = psycopg2.connect(**DB_KWARGS)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT name
                FROM attractions
                WHERE destination_id = %s
                  AND name IS NOT NULL
                """,
                (destination_id,),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()
    return {
        name_key
        for (name,) in rows
        if (name_key := _attraction_name_key(name))
    }


def filter_existing_attraction_names(
    records: Iterable[Dict[str, Any]],
    existing_name_keys: set[str],
) -> List[Dict[str, Any]]:
    """Exclude records whose cleaned name is already stored for the destination."""
    normalized_existing_names = {
        name_key
        for name in existing_name_keys
        if (name_key := _attraction_name_key(name))
    }
    return [
        record
        for record in records
        if _attraction_name_key(record.get("name")) not in normalized_existing_names
    ]


def _scrape_page_html(page: Any, source_url: str) -> str:
    page.goto(source_url, wait_until="domcontentloaded", timeout=60_000)
    if hotel_source_name(source_url) == "booking":
        try:
            surroundings_heading = page.get_by_text(
                re.compile(r"Hotel surroundings|Xung quanh khách sạn", re.IGNORECASE)
            )
            if surroundings_heading.count():
                surroundings_heading.first.scroll_into_view_if_needed()
            page.wait_for_function(
                """() => [...document.querySelectorAll('h2, h3, h4')]
                    .some(element => /what'?s nearby|top attractions|xung quanh có gì|địa điểm tham quan hàng đầu/i
                    .test(element.innerText))""",
                timeout=20_000,
            )
        except Exception:
            pass
    html = ""
    for _ in range(3):
        page.wait_for_timeout(2_000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
            html = page.content()
            break
        except Exception:
            continue
    if not html:
        raise RuntimeError("Hotel page did not settle before its HTML could be read.")
    if any(marker in html.lower() for marker in BLOCKING_MARKERS):
        raise RuntimeError(f"{hotel_source_name(source_url)} blocked the public hotel-page scrape.")
    return html


def _batches_by_hotel(
    records: Iterable[Dict[str, Any]],
    worker_count: int,
) -> List[List[Dict[str, Any]]]:
    """Split independent hotels across bounded workers without splitting their records."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for index, record in enumerate(records):
        hotel_key = str(record.get("hotel_id") or f"record-{index}")
        grouped.setdefault(hotel_key, []).append(record)
    groups = list(grouped.values())
    if not groups:
        return []
    batch_count = min(max(int(worker_count or 1), 1), len(groups))
    batches: List[List[Dict[str, Any]]] = [[] for _ in range(batch_count)]
    for index, group in enumerate(groups):
        batches[index % batch_count].extend(group)
    return batches


def _crawl_hotel_surroundings_batch(
    hotels: Iterable[Dict[str, Any]],
    nearby_limit_per_hotel: int,
) -> List[Dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Hotel surroundings scraping requires Playwright and Chromium in the Airflow image.") from exc

    seeds: List[Dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="en-GB")
        try:
            for hotel in hotels:
                page = context.new_page()
                try:
                    html = _scrape_page_html(page, hotel["source_url"])
                    parser = (
                        extract_booking_surrounding_names
                        if hotel["source"] == "booking"
                        else extract_agoda_surrounding_names
                    )
                    for name in parser(html, hotel["hotel_name"])[:nearby_limit_per_hotel]:
                        seeds.append({**hotel, "name": name, "category": _classify_nearby_name(name)})
                except Exception as exc:
                    print(f"[hotel-nearby] Skipped {hotel['source']} hotel {hotel['hotel_id']}: {exc}")
                finally:
                    page.close()
                time.sleep(0.75)
        finally:
            context.close()
            browser.close()
    return seeds


def crawl_hotel_surroundings(
    hotels: Iterable[Dict[str, Any]],
    nearby_limit_per_hotel: int,
    worker_count: int = 1,
) -> List[Dict[str, Any]]:
    """Use source-specific parsers in independent, bounded hotel batches."""
    batches = _batches_by_hotel(hotels, worker_count)
    if not batches:
        return []
    if len(batches) == 1:
        return _crawl_hotel_surroundings_batch(
            batches[0],
            nearby_limit_per_hotel,
        )
    results: List[List[Dict[str, Any]]] = [[] for _ in batches]
    with ThreadPoolExecutor(max_workers=len(batches), thread_name_prefix="hotel-crawl") as executor:
        futures = {
            executor.submit(_crawl_hotel_surroundings_batch, batch, nearby_limit_per_hotel): index
            for index, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [seed for batch in results for seed in batch]


def validate_hotel_surrounding_seeds(
    seeds: Iterable[Dict[str, Any]],
    location_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Reject malformed seeds and hotels outside the requested destination first."""
    accepted: List[Dict[str, Any]] = []
    for seed in seeds:
        name = sanitize_attraction_name(seed.get("name", ""))
        try:
            latitude = float(seed["hotel_latitude"])
            longitude = float(seed["hotel_longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not name or not is_coordinate_allowed(latitude, longitude, location_context):
            continue
        accepted.append({**seed, "name": name, "hotel_latitude": latitude, "hotel_longitude": longitude})
    return accepted


def is_within_hotel_radius(
    hotel_latitude: float,
    hotel_longitude: float,
    place_latitude: float,
    place_longitude: float,
    radius_meters: int,
) -> bool:
    """Return whether a resolved place is close enough to its source hotel."""
    earth_radius_meters = 6_371_000
    latitude_delta = math.radians(place_latitude - hotel_latitude)
    longitude_delta = math.radians(place_longitude - hotel_longitude)
    a = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(hotel_latitude))
        * math.cos(math.radians(place_latitude))
        * math.sin(longitude_delta / 2) ** 2
    )
    distance = 2 * earth_radius_meters * math.asin(math.sqrt(a))
    return distance <= radius_meters


def resolve_hotel_surrounding_seeds(
    seeds: Iterable[Dict[str, Any]],
    location_context: Dict[str, Any],
    hotel_radius_meters: int,
    destination_name: str = "",
    worker_count: int = 1,
) -> List[Dict[str, Any]]:
    batches = _batches_by_hotel(seeds, worker_count)
    if not batches:
        return []
    if len(batches) == 1:
        return resolve_google_maps_nearby_candidates(
            batches[0],
            location_context,
            hotel_radius_meters,
            destination_name,
        )
    results: List[List[Dict[str, Any]]] = [[] for _ in batches]
    with ThreadPoolExecutor(max_workers=len(batches), thread_name_prefix="maps-resolve") as executor:
        futures = {
            executor.submit(
                resolve_google_maps_nearby_candidates,
                batch,
                location_context,
                hotel_radius_meters,
                destination_name,
            ): index
            for index, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [candidate for batch in results for candidate in batch]
