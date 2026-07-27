import ipaddress
import json
import math
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

from attraction_utils import (
    deduplicate_attractions,
    is_coordinate_allowed,
    sanitize_attraction_name,
    select_diverse_attractions,
    stable_attraction_id,
)
from grounded_description import enrich_description_from_sources


_MAPS_CACHE_FILE = "data/google_maps_cache.jsonl"
_MAPS_CACHE_LOCK = threading.Lock()

def _load_maps_cache() -> Dict[str, Any]:
    cache = {}
    if os.path.exists(_MAPS_CACHE_FILE):
        with open(_MAPS_CACHE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    cache[entry["seed_name"]] = entry["result"]
                except Exception:
                    pass
    return cache

def _append_to_maps_cache(seed_name: str, result: Optional[Dict[str, Any]]):
    with _MAPS_CACHE_LOCK:
        os.makedirs(os.path.dirname(_MAPS_CACHE_FILE), exist_ok=True)
        with open(_MAPS_CACHE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"seed_name": seed_name, "result": result}, ensure_ascii=False) + "\n")


VIETNAMESE_CHARACTERS = set(
    "ăâđêôơưĂÂĐÊÔƠƯ"
    "àáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễ"
    "ìíịỉĩòóọỏõồốộổỗờớợởỡ"
    "ùúụủũừứựửữỳýỵỷỹ"
    "ÀÁẠẢÃẰẮẶẲẴẦẤẬẨẪÈÉẸẺẼỀẾỆỂỄ"
    "ÌÍỊỈĨÒÓỌỎÕỒỐỘỔỖỜỚỢỞỠ"
    "ÙÚỤỦŨỪỨỰỬỮỲÝỴỶỸ"
)
GOOGLE_IMAGE_HOSTS = ("googleusercontent.com", "ggpht.com")
SOCIAL_PROFILE_HOSTS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
)
SOCIAL_DESCRIPTION_MARKERS = (
    "người theo dõi",
    "đang theo dõi",
    "bài viết",
    "trên instagram",
    "followers",
    "following",
    "posts on instagram",
)
OFFICIAL_DESCRIPTION_SCHEMA_TYPES = {
    "landmarksorhistoricalbuildings",
    "localbusiness",
    "museum",
    "organization",
    "park",
    "place",
    "restaurant",
    "touristattraction",
    "touristdestination",
}
GOOGLE_MAPS_SEARCHES = (
    ("bảo tàng và di tích tại {destination}", "Museums & culture"),
    ("công viên và địa điểm thiên nhiên tại {destination}", "Nature & outdoor"),
    ("khu vui chơi tại {destination}", "Entertainment & tickets"),
    ("địa điểm du lịch tại {destination}", "Other activities"),
    ("nhà hàng tại {destination}", "Restaurants & cafes"),
    ("quán cà phê tại {destination}", "Restaurants & cafes"),
)


def _coordinates_from_google_maps_url(url: str) -> Optional[Tuple[float, float]]:
    if not url:
        return None
    data_match = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", url)
    viewport_match = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", url)
    match = data_match or viewport_match
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def _normalize_google_maps_destination(
    requested_name: str,
    resolved_name: str,
    address: str,
    url: str,
) -> Optional[Dict[str, Any]]:
    coordinates = _coordinates_from_google_maps_url(url)
    if not coordinates:
        return None
    return {
        "name": (resolved_name or requested_name).strip(),
        "address": (address or "").strip(),
        "latitude": coordinates[0],
        "longitude": coordinates[1],
        "url": url,
        "source": "google_maps_poc",
    }


def _has_vietnamese_name(name: str) -> bool:
    return bool(name and any(character in VIETNAMESE_CHARACTERS for character in name))


def _google_maps_source_id(url: str) -> str:
    match = re.search(r"!1s([^!/?]+)", url or "")
    return match.group(1) if match else (url or "")


def _parse_rating(label: str) -> Optional[float]:
    match = re.search(r"(\d+(?:[.,]\d+)?)", label or "")
    return float(match.group(1).replace(",", ".")) if match else None


def _card_description(lines: List[str], name: str) -> Optional[str]:
    for line in lines:
        if line == name or re.fullmatch(r"\d+(?:[.,]\d+)?", line):
            continue
        normalized = line.lower()
        if (
            "·" in line
            or "mở cửa" in normalized
            or "đóng cửa" in normalized
            or any(
                marker in normalized
                for marker in ("được tài trợ", "sponsored", "quảng cáo", "advertisement")
            )
        ):
            continue
        if len(line) >= 12:
            return line
    return None


def _is_restaurant_category(category: str) -> bool:
    return category == "Restaurants & cafes"


def _valid_google_image(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        hostname == host or hostname.endswith(f".{host}")
        for host in GOOGLE_IMAGE_HOSTS
    )


def _is_google_maps_place_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in {
            "google.com",
            "maps.google.com",
            "www.google.com",
        }
        and parsed.path.startswith("/maps/place/")
    )


def _is_safe_official_site_url(url: str) -> bool:
    """Allow only public HTTPS domain URLs discovered in a Maps authority link."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or "." not in hostname
        or hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
    ):
        return False
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return False


def _is_supported_official_content_url(url: str) -> bool:
    """Reject social-profile pages while retaining public first-party websites."""
    if not _is_safe_official_site_url(url):
        return False
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return not any(
        hostname == social_host or hostname.endswith(f".{social_host}")
        for social_host in SOCIAL_PROFILE_HOSTS
    )


def _is_usable_attraction_description(value: Any) -> bool:
    """Accept editorial text, not Maps labels, phone numbers, or social bios."""
    description = " ".join(str(value or "").split()).strip()
    if not 30 <= len(description) <= 1_000:
        return False
    lowered = description.casefold()
    if any(marker in lowered for marker in SOCIAL_DESCRIPTION_MARKERS):
        return False
    if "instagram" in lowered or re.fullmatch(r"\+?[\d\s().-]{7,}", description):
        return False
    return sum(character.isalpha() for character in description) >= 20


def _same_site_host(first_url: str, second_url: str) -> bool:
    first_host = (urlparse(first_url).hostname or "").lower().removeprefix("www.")
    second_host = (urlparse(second_url).hostname or "").lower().removeprefix("www.")
    return bool(first_host and first_host == second_host)


def _needs_official_site_enrichment(record: Dict[str, Any]) -> bool:
    return (
        not _is_usable_attraction_description(record.get("description"))
        or len(str(record.get("description") or "").strip()) < 80
        or len(record.get("images") or []) < 2
    )


def _trim_incomplete_description(description: str) -> str:
    description = " ".join(str(description or "").split())
    if not description.endswith((",", ";", ":", "-", "–")):
        return description
    last_sentence = max(
        description.rfind("."),
        description.rfind("!"),
        description.rfind("?"),
    )
    return description[: last_sentence + 1] if last_sentence >= 40 else description


def _merge_official_site_detail(
    record: Dict[str, Any],
    detail: Dict[str, Any],
) -> Dict[str, Any]:
    """Prefer a meaningfully richer official description and retain all valid images."""
    merged = dict(record)
    official_description = str(detail.get("description") or "").strip()
    current_description = str(record.get("description") or "").strip()
    if (
        _is_usable_attraction_description(official_description)
        and len(official_description) >= 80
        and len(official_description) > len(current_description)
    ):
        merged["description"] = official_description
    images: List[str] = []
    identities = set()
    for source in (detail.get("images") or []) + (record.get("images") or []):
        source = _large_google_image_url(str(source))
        if not _is_safe_official_site_url(source):
            continue
        identity = _google_image_identity(source)
        if identity in identities:
            continue
        identities.add(identity)
        images.append(source)
    merged["images"] = images[:5]
    return merged


def _google_maps_enrichment_urls(
    record: Dict[str, Any],
    candidate_url: str,
    destination_name: str,
    prefer_exact_place: bool = False,
) -> List[str]:
    """Build detail URLs, optionally preferring an already-resolved exact place."""
    name = sanitize_attraction_name(record.get("name", ""))
    destination = sanitize_attraction_name(destination_name)
    urls: List[str] = []
    exact_place_url = (
        candidate_url if _is_google_maps_place_url(candidate_url) else ""
    )
    if prefer_exact_place and exact_place_url:
        urls.append(exact_place_url)
    if name:
        query = quote(f"{name}, {destination}" if destination else name)
        latitude = record.get("latitude")
        longitude = record.get("longitude")
        center = (
            f"/@{latitude},{longitude},15z"
            if latitude is not None and longitude is not None
            else ""
        )
        urls.append(
            f"https://www.google.com/maps/search/{query}{center}?hl=vi"
        )
    if exact_place_url and exact_place_url not in urls:
        urls.append(exact_place_url)
    return urls


def _google_maps_official_website(page: Any) -> Optional[str]:
    authority_link = page.locator('a[data-item-id="authority"]')
    if not authority_link.count():
        return None
    website_url = authority_link.first.get_attribute("href") or ""
    return website_url if _is_safe_official_site_url(website_url) else None


def _google_image_dimensions(url: str) -> Tuple[int, int]:
    match = re.search(r"=w(\d+)-h(\d+)", url or "")
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def _large_google_image_url(url: str) -> str:
    match = re.search(r"=w(\d+)-h(\d+)([^?]*)$", url or "")
    if not match:
        return url
    width = int(match.group(1))
    height = int(match.group(2))
    if not width or not height:
        return url
    if width >= height:
        target_width = 1_200
        target_height = max(1, round(height * target_width / width))
    else:
        target_height = 1_200
        target_width = max(1, round(width * target_height / height))
    return (
        f"{url[:match.start()]}=w{target_width}-h{target_height}"
        f"{match.group(3)}"
    )


def _normalize_google_maps_detail(
    description_candidates: List[str],
    image_nodes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    description = next(
        (
            text.strip()
            for text in description_candidates
            if _is_usable_attraction_description(text)
        ),
        None,
    )
    images: List[str] = []
    for node in image_nodes:
        source = str(node.get("src") or "")
        if not _valid_google_image(source):
            continue
        width = int(node.get("width") or 0)
        height = int(node.get("height") or 0)
        if not width or not height:
            width, height = _google_image_dimensions(source)
        if width < 300 or height < 200:
            continue
        source = _large_google_image_url(source)
        if source not in images:
            images.append(source)
    return {"description": description, "images": images[:5]}


def _parse_google_maps_hours(labels: List[str]) -> Dict[str, Optional[str]]:
    """Return a single public daily opening range from Maps accessibility labels."""
    empty_hours = {"opening_time": None, "closing_time": None}
    time_range = re.compile(
        r"(?<!\d)(\d{1,2}):(\d{2})\s*(?:đến|to|–|-)\s*"
        r"(\d{1,2}):(\d{2})(?!\d)",
        re.IGNORECASE,
    )
    for label in labels:
        label = " ".join(str(label or "").split())
        normalized = label.lower()
        if "giờ mở cửa" not in normalized and "opening hours" not in normalized:
            continue
        if re.search(r"(?:mở cửa|open)\s*24\s*(?:giờ|hours?)", normalized):
            return {"opening_time": "00:00:00", "closing_time": "23:59:59"}
        ranges = time_range.findall(label)
        if len(ranges) != 1:
            continue
        opening_hour, opening_minute, closing_hour, closing_minute = ranges[0]
        if any(
            int(hour) > 23 or int(minute) > 59
            for hour, minute in (
                (opening_hour, opening_minute),
                (closing_hour, closing_minute),
            )
        ):
            continue
        return {
            "opening_time": f"{int(opening_hour):02d}:{opening_minute}:00",
            "closing_time": f"{int(closing_hour):02d}:{closing_minute}:00",
        }
    return empty_hours


def _google_image_identity(url: str) -> str:
    return re.sub(r"=w\d+-h\d+[^?]*$", "", url or "")


def _merge_google_maps_detail(
    record: Dict[str, Any],
    detail: Dict[str, Any],
) -> Dict[str, Any]:
    merged = dict(record)
    if _is_usable_attraction_description(detail.get("description")):
        merged["description"] = detail["description"]
    images: List[str] = []
    identities = set()
    for source in (detail.get("images") or []) + (record.get("images") or []):
        source = _large_google_image_url(str(source))
        identity = _google_image_identity(source)
        if not identity or identity in identities:
            continue
        identities.add(identity)
        images.append(source)
    merged["images"] = images[:5]
    for field in ("opening_time", "closing_time", "rating", "review_count"):
        if detail.get(field):
            merged[field] = detail[field]
    return merged


def _fact_based_description(
    record: Dict[str, Any],
    destination_name: str,
    place_category: str = "",
) -> str:
    name = str(record.get("name") or "Địa điểm").strip()
    destination = destination_name.strip() or "Việt Nam"
    category = " ".join(str(place_category or "").split()).strip(" .")
    if 2 <= len(category) <= 80:
        category = f"{category[:1].lower()}{category[1:]}"
        return f"{name} là {category} tại {destination}."
    return f"{name} là một địa điểm tại {destination}."


def validate_clean_google_maps_candidates(
    candidates: List[Dict[str, Any]],
    location_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Keep geographically valid public Maps cards with clean display names."""
    accepted = []
    for candidate in candidates:
        name = sanitize_attraction_name(candidate.get("name", ""))
        category = str(candidate.get("category") or "Other activities")
        if not name:
            continue
        if not _is_restaurant_category(category) and not _has_vietnamese_name(name):
            continue
        latitude = candidate.get("latitude")
        longitude = candidate.get("longitude")
        if latitude is None or longitude is None:
            coordinates = _coordinates_from_google_maps_url(
                str(candidate.get("url") or "")
            )
            if not coordinates:
                continue
            latitude, longitude = coordinates
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            continue
        if not is_coordinate_allowed(latitude, longitude, location_context):
            continue
        accepted.append({
            **candidate,
            "name": name,
            "category": category,
            "latitude": latitude,
            "longitude": longitude,
        })
    return accepted


def _google_maps_candidate_to_record(
    candidate: Dict[str, Any],
    destination_id: str,
) -> Dict[str, Any]:
    name = str(candidate["name"])
    category = str(candidate.get("category") or "Other activities")
    latitude = float(candidate["latitude"])
    longitude = float(candidate["longitude"])
    source_id = str(candidate.get("source_id") or candidate.get("url") or name)
    images = [
        _large_google_image_url(str(url))
        for url in (candidate.get("images") or [candidate.get("image")])
        if _valid_google_image(str(url or ""))
    ]
    record = {
        "destination_id": destination_id,
        "name": name,
        "description": candidate.get("description") or None,
        "category": category,
        "is_tour": False,
        "estimated_duration_minutes": None,
        "opening_time": None,
        "closing_time": None,
        "departure_schedule": None,
        "ticket_price_adult": None,
        "ticket_price_child": None,
        "rating": candidate.get("rating"),
        "review_count": candidate.get("review_count"),
        "coordinates": f"{latitude},{longitude}",
        "images": list(dict.fromkeys(images))[:5],
        "source": "google_maps_poc",
        "source_id": source_id,
        "latitude": latitude,
        "longitude": longitude,
    }
    record["id"] = stable_attraction_id(record)
    return record


def normalize_google_maps_candidate(
    candidate: Dict[str, Any],
    destination_id: str,
    location_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    cleaned_candidates = validate_clean_google_maps_candidates(
        [candidate],
        location_context,
    )
    if not cleaned_candidates:
        return None
    return _google_maps_candidate_to_record(cleaned_candidates[0], destination_id)


def normalize_google_maps_candidates(
    candidates: List[Dict[str, Any]],
    destination_id: str,
    destination_name: str,
    enrichment_limit: int,
    fast_poc_mode: bool = False,
) -> List[Dict[str, Any]]:
    """Map clean cards to the canonical schema, then enrich their details."""
    normalization_candidates = (
        [
            {
                **candidate,
                "description": None,
            }
            for candidate in candidates
        ]
        if fast_poc_mode
        else candidates
    )
    records = [
        _google_maps_candidate_to_record(candidate, destination_id)
        for candidate in normalization_candidates
    ]
    enrichment_pool = select_diverse_attractions(
        deduplicate_attractions(records),
        enrichment_limit,
    )
    return enrich_google_maps_records(
        enrichment_pool,
        normalization_candidates,
        destination_name,
        fast_poc_mode=fast_poc_mode,
    )


def _select_google_maps_records(
    candidates: List[Dict[str, Any]],
    destination_id: str,
    location_context: Dict[str, Any],
    item_limit: int,
) -> List[Dict[str, Any]]:
    normalized = [
        record
        for candidate in candidates
        if (record := normalize_google_maps_candidate(
            candidate,
            destination_id,
            location_context,
        ))
    ]
    return select_diverse_attractions(deduplicate_attractions(normalized), item_limit)


def _accept_google_consent(page: Any) -> None:
    for label in ("Chấp nhận tất cả", "Accept all"):
        button = page.get_by_role("button", name=label)
        if button.count():
            button.first.click(timeout=3_000)
            page.wait_for_timeout(500)
            return


def _raise_if_google_blocked(page: Any) -> None:
    title = (page.title() or "").lower()
    url = (page.url or "").lower()
    body = (page.locator("body").inner_text(timeout=5_000) or "").lower()
    blocked_markers = ("unusual traffic", "lưu lượng truy cập bất thường", "captcha")
    if "/sorry/" in url or any(marker in title or marker in body for marker in blocked_markers):
        raise RuntimeError("Google Maps blocked the POC browser scrape with an access challenge.")


def _google_ai_search_query(attraction_name: str, destination_name: str) -> str:
    cleaned_name = sanitize_attraction_name(attraction_name).strip()
    cleaned_destination = " ".join(str(destination_name or "").split()).strip()
    return (
        f'"{cleaned_name}" "{cleaned_destination}" '
        "giới thiệu lịch sử địa điểm tham quan"
    )


def _google_ai_description_from_block_text(block_text: str) -> Optional[str]:
    lines = [
        " ".join(line.split()).strip()
        for line in str(block_text or "").splitlines()
        if line.strip()
    ]
    overview_markers = (
        "thông tin tổng quan do ai tạo",
        "ai overview",
    )
    stop_markers = (
        "đặc điểm nổi bật",
        "hiện thêm",
        "show more",
        "sources",
        "nguồn",
    )
    start_index = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if any(marker in line.casefold() for marker in overview_markers)
        ),
        0,
    )
    description_lines: List[str] = []
    overview_lines = lines[start_index:]
    for index, line in enumerate(overview_lines):
        lowered = line.casefold()
        if any(lowered.startswith(marker) for marker in stop_markers):
            break
        next_line = (
            overview_lines[index + 1].casefold()
            if index + 1 < len(overview_lines)
            else ""
        )
        if re.fullmatch(r"\+\d+", next_line):
            break
        if re.search(
            r"(?:\+\d+|và \d+ nguồn(?: khác)?|and \d+ (?:other )?sources?)$",
            lowered,
        ):
            break
        description_lines.append(line)
    description = _trim_incomplete_description(" ".join(description_lines))
    if len(description) > 1_000:
        description = description[:1_000].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return description if _is_usable_attraction_description(description) else None


def _google_ai_overview_from_page(page: Any) -> Dict[str, Any]:
    marker = page.get_by_text(
        re.compile(r"Thông tin tổng quan do AI tạo|AI Overview", re.IGNORECASE)
    )
    if not marker.count():
        return {"description": None, "citations": []}
    marker = marker.first
    block = marker.evaluate(
        """
        element => {
          let current = element;
          let fallback = null;
          for (let depth = 0; current && depth < 10; depth += 1) {
            const text = (current.innerText || "").trim();
            if (!fallback && text.length >= 180 && text.length <= 6000) {
              fallback = current;
            }
            if (
              text.length >= 100 &&
              text.length <= 6000 &&
              /Hiện thêm|Show more/i.test(text)
            ) {
              fallback = current;
              break;
            }
            current = current.parentElement;
          }
          if (!fallback) {
            return {text: "", citations: []};
          }
          const citations = Array.from(fallback.querySelectorAll("a[href]"))
            .map(link => link.href)
            .filter(href => href && /^https?:/i.test(href));
          return {
            text: (fallback.innerText || "").trim(),
            citations: [...new Set(citations)],
          };
        }
        """
    )
    if not isinstance(block, dict):
        return {"description": None, "citations": []}
    return {
        "description": _google_ai_description_from_block_text(block.get("text", "")),
        "citations": block.get("citations") or [],
    }


def fetch_google_ai_overview_description(
    attraction_name: str,
    destination_name: str,
) -> Dict[str, Any]:
    """Run one rendered Google Search query and return its visible AI Overview."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Google AI Overview POC requires Playwright and Chromium."
        ) from exc

    query = _google_ai_search_query(attraction_name, destination_name)
    search_url = f"https://www.google.com/search?q={quote(query)}&hl=vi&gl=vn"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        try:
            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            _accept_google_consent(page)
            try:
                page.get_by_text(
                    re.compile(
                        r"Thông tin tổng quan do AI tạo|AI Overview",
                        re.IGNORECASE,
                    )
                ).first.wait_for(state="visible", timeout=15_000)
            except Exception:
                page.wait_for_timeout(1_000)
            _raise_if_google_blocked(page)
            overview = _google_ai_overview_from_page(page)
            return {
                "source": "google_ai_overview",
                "query": query,
                "search_url": page.url or search_url,
                "description": overview.get("description"),
                "citations": overview.get("citations") or [],
            }
        finally:
            context.close()
            browser.close()


def scrape_google_maps_destination(destination_name: str) -> Optional[Dict[str, Any]]:
    """Resolve a destination center from rendered Google Maps, without its API."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Google Maps POC scraping requires Playwright and Chromium in the Airflow image."
        ) from exc

    query = quote(f"{destination_name}, Vietnam")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        try:
            page.goto(
                f"https://www.google.com/maps/search/{query}?hl=vi",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            _accept_google_consent(page)
            try:
                page.wait_for_url(re.compile(r".*/maps/place/.*"), timeout=10_000)
            except Exception:
                page.wait_for_timeout(1_000)
            _raise_if_google_blocked(page)

            resolved_name = ""
            heading = page.locator("h1")
            if heading.count():
                resolved_name = (heading.first.inner_text(timeout=3_000) or "").strip()

            address = ""
            address_node = page.locator('[data-item-id="address"]')
            if address_node.count():
                node = address_node.first
                address = (
                    node.get_attribute("aria-label")
                    or node.inner_text(timeout=3_000)
                    or ""
                ).strip()

            result = _normalize_google_maps_destination(
                destination_name,
                resolved_name,
                address,
                page.url,
            )
            if result:
                return result

            place_links = page.locator('a[href*="/maps/place/"]')
            for index in range(min(place_links.count(), 10)):
                link = place_links.nth(index)
                result = _normalize_google_maps_destination(
                    destination_name,
                    link.get_attribute("aria-label") or "",
                    "",
                    link.get_attribute("href") or "",
                )
                if result:
                    return result
            return None
        finally:
            context.close()
            browser.close()


def _scroll_results(page: Any, target: int) -> None:
    feed = page.locator('[role="feed"]')
    if not feed.count():
        return
    previous_count = -1
    unchanged_rounds = 0
    for _ in range(10):
        current_count = page.locator('[role="article"]').count()
        if current_count >= target or unchanged_rounds >= 2:
            break
        feed.evaluate("element => { element.scrollTop = element.scrollHeight; }")
        page.wait_for_timeout(500)
        unchanged_rounds = unchanged_rounds + 1 if current_count == previous_count else 0
        previous_count = current_count


def _candidate_from_google_card(
    article: Any,
    fallback_category: str,
    include_description: bool = True,
) -> Optional[Dict[str, Any]]:
    links = article.locator("a")
    place_link = None
    for index in range(links.count()):
        href = links.nth(index).get_attribute("href") or ""
        if "/maps/place/" in href:
            place_link = links.nth(index)
            break
    if place_link is None:
        return None

    url = place_link.get_attribute("href") or ""
    name = (place_link.get_attribute("aria-label") or "").strip()
    coordinates = _coordinates_from_google_maps_url(url)
    if not name or not coordinates:
        return None

    rating = None
    rating_nodes = article.locator('[role="img"]')
    for index in range(rating_nodes.count()):
        label = rating_nodes.nth(index).get_attribute("aria-label") or ""
        if "sao" in label.lower() or "star" in label.lower():
            rating = _parse_rating(label)
            break

    image = None
    images = article.locator("img")
    for index in range(images.count()):
        source = images.nth(index).get_attribute("src") or ""
        if _valid_google_image(source):
            image = source
            break

    description = None
    if include_description:
        lines = [
            line.strip()
            for line in article.inner_text().splitlines()
            if line.strip()
        ]
        description = _card_description(lines, name)
    return {
        "source_id": _google_maps_source_id(url),
        "name": name,
        "category": fallback_category,
        "latitude": coordinates[0],
        "longitude": coordinates[1],
        "rating": rating,
        "review_count": None,
        "description": description,
        "image": image,
        "url": url,
    }


def scrape_google_maps_candidates(
    destination_name: str,
    location_context: Dict[str, Any],
    candidate_limit: int,
) -> List[Dict[str, Any]]:
    """POC browser scraper for rendered Google Maps search cards; uses no Maps API."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Google Maps POC scraping requires Playwright and Chromium in the Airflow image."
        ) from exc

    center = f"{location_context['latitude']},{location_context['longitude']}"
    target_per_query = max(4, (candidate_limit // len(GOOGLE_MAPS_SEARCHES)) + 3)
    candidates: Dict[str, Dict[str, Any]] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        try:
            for query_template, category in GOOGLE_MAPS_SEARCHES:
                query = query_template.format(destination=destination_name)
                url = (
                    f"https://www.google.com/maps/search/{quote(query)}/"
                    f"@{center},13z?hl=vi"
                )
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                _accept_google_consent(page)
                try:
                    page.wait_for_selector(
                        '[role="article"]',
                        state="attached",
                        timeout=8_000,
                    )
                except Exception:
                    pass
                _raise_if_google_blocked(page)
                _scroll_results(page, target_per_query)
                articles = page.locator('[role="article"]')
                for index in range(min(articles.count(), target_per_query)):
                    try:
                        candidate = _candidate_from_google_card(
                            articles.nth(index),
                            category,
                            include_description=False,
                        )
                    except Exception as exc:
                        print(f"[google-maps-poc] Skipped unreadable result card: {exc}")
                        continue
                    if candidate:
                        candidates.setdefault(candidate["source_id"], candidate)
        finally:
            context.close()
            browser.close()
    return list(candidates.values())


def _nearby_name_matches(requested_name: str, resolved_name: str) -> bool:
    requested_tokens = set(sanitize_attraction_name(requested_name).lower().split())
    resolved_tokens = set(sanitize_attraction_name(resolved_name).lower().split())
    if not requested_tokens or not resolved_tokens:
        return False
    overlap = len(requested_tokens & resolved_tokens)
    return overlap / min(len(requested_tokens), len(resolved_tokens)) >= 0.6


def _candidate_from_google_maps_place_page(
    page: Any,
    seed: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    coordinates = _place_coordinates_from_google_maps_url(page.url)
    if not coordinates:
        shared_url = _google_maps_shared_place_url(page)
        if shared_url:
            page.goto(shared_url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_function(
                    "() => /!3d-?\\d+(?:\\.\\d+)?!4d-?\\d+(?:\\.\\d+)?/.test(location.href)",
                    timeout=5_000,
                )
            except Exception:
                pass
            coordinates = _place_coordinates_from_google_maps_url(page.url)
    heading = page.locator("h1")
    name = (heading.first.inner_text(timeout=3_000) or "").strip() if heading.count() else ""
    if not name or not coordinates:
        return None
    image = None
    images = page.locator("img")
    for index in range(min(images.count(), 20)):
        source = images.nth(index).get_attribute("src") or ""
        if _valid_google_image(source):
            image = source
            break
    return {
        **seed,
        "source_id": _google_maps_source_id(page.url),
        "name": name,
        "category": seed.get("category") or "Other activities",
        "latitude": coordinates[0],
        "longitude": coordinates[1],
        "rating": None,
        "review_count": None,
        "description": None,
        "image": image,
        "url": page.url,
    }


def _place_coordinates_from_google_maps_url(url: str) -> Optional[Tuple[float, float]]:
    match = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", url or "")
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def _google_maps_shared_place_url(page: Any) -> Optional[str]:
    """Read Maps' generated short link, then use its redirect for a true place point."""
    for label in ("Chia sẻ", "Share"):
        button = page.get_by_role("button", name=label)
        if not button.count():
            continue
        try:
            button.first.click(timeout=3_000)
            for _ in range(20):
                inputs = page.locator("input")
                for index in range(inputs.count()):
                    value = inputs.nth(index).input_value() or ""
                    parsed = urlparse(value)
                    if parsed.scheme == "https" and parsed.hostname == "maps.app.goo.gl":
                        return value
                page.wait_for_timeout(500)
        except Exception:
            continue
    return None


def _within_hotel_radius(candidate: Dict[str, Any], radius_meters: int) -> bool:
    try:
        hotel_latitude = float(candidate["hotel_latitude"])
        hotel_longitude = float(candidate["hotel_longitude"])
        place_latitude = float(candidate["latitude"])
        place_longitude = float(candidate["longitude"])
    except (KeyError, TypeError, ValueError):
        return False
    latitude_delta = math.radians(place_latitude - hotel_latitude)
    longitude_delta = math.radians(place_longitude - hotel_longitude)
    distance = 2 * 6_371_000 * math.asin(math.sqrt(
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(hotel_latitude))
        * math.cos(math.radians(place_latitude))
        * math.sin(longitude_delta / 2) ** 2
    ))
    return distance <= radius_meters


def _is_geographically_valid_nearby_maps_result(
    candidate: Dict[str, Any],
    location_context: Dict[str, Any],
    hotel_radius_meters: int,
) -> bool:
    try:
        latitude = float(candidate["latitude"])
        longitude = float(candidate["longitude"])
    except (KeyError, TypeError, ValueError):
        return False
    return _within_hotel_radius(candidate, hotel_radius_meters) and is_coordinate_allowed(
        latitude,
        longitude,
        location_context,
    )


def resolve_google_maps_nearby_candidates(
    seeds: List[Dict[str, Any]],
    location_context: Dict[str, Any],
    hotel_radius_meters: int,
    destination_name: str = "",
) -> List[Dict[str, Any]]:
    """Resolve OTA nearby-place names through rendered Maps, anchored to each hotel."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Google Maps POC scraping requires Playwright and Chromium in the Airflow image."
        ) from exc

    candidates: Dict[str, Dict[str, Any]] = {}
    
    cache = _load_maps_cache()
    unseen_seeds = []
    for seed in seeds:
        name = sanitize_attraction_name(seed.get("name", ""))
        if not name:
            continue
        if name in cache:
            candidate = cache[name]
            if candidate:
                if not _within_hotel_radius(candidate, hotel_radius_meters):
                    pass
                elif not is_coordinate_allowed(
                    float(candidate["latitude"]),
                    float(candidate["longitude"]),
                    location_context,
                ):
                    pass
                else:
                    candidates.setdefault(str(candidate["source_id"]), candidate)
        else:
            unseen_seeds.append(seed)

    if not unseen_seeds:
        return list(candidates.values())

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        try:
            for seed in unseen_seeds:
                name = sanitize_attraction_name(seed.get("name", ""))
                if not name:
                    continue
                query = (
                    f"{name}, {destination_name}, Vietnam"
                    if destination_name
                    else name
                )
                if "seed_latitude" in seed and "seed_longitude" in seed:
                    center = f"/@{seed['seed_latitude']},{seed['seed_longitude']},15z"
                    url = f"https://www.google.com/maps/search/{quote(query)}{center}?hl=vi"
                else:
                    url = f"https://www.google.com/maps/search/?api=1&query={quote(query)}&hl=vi"
                try:
                    candidate = None
                    # Maps occasionally renders only its search shell on the first
                    # navigation, even for a valid nearby place.  Retry the exact
                    # query once before rejecting the OTA-provided candidate.
                    for attempt in range(2):
                        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                        _accept_google_consent(page)
                        page.wait_for_timeout(3_500 if attempt == 0 else 5_000)
                        _raise_if_google_blocked(page)
                        candidate = _candidate_from_google_maps_place_page(page, seed)
                        if candidate is None:
                            articles = page.locator('[role="article"]')
                            for index in range(min(articles.count(), 5)):
                                card = _candidate_from_google_card(
                                    articles.nth(index),
                                    str(seed.get("category") or "Other activities"),
                                )
                                nearby_card = {**seed, **card} if card else None
                                if nearby_card and _is_geographically_valid_nearby_maps_result(
                                    nearby_card,
                                    location_context,
                                    hotel_radius_meters,
                                ):
                                    if not _nearby_name_matches(name, card["name"]):
                                        print(
                                            "[hotel-nearby] Accepted nearby Google Maps canonical name: "
                                            f"{name} -> {card['name']}"
                                        )
                                    candidate = nearby_card
                                    break
                        if candidate is not None:
                            break
                        if attempt == 0:
                            print(
                                "[hotel-nearby] Retrying Maps resolution with a fresh navigation: "
                                f"{name}"
                            )
                    if candidate is None:
                        print(
                            "[hotel-nearby] Could not resolve a matching Maps result: "
                            f"{name}"
                        )
                    elif not _within_hotel_radius(candidate, hotel_radius_meters):
                        print(f"[hotel-nearby] Rejected Maps result outside hotel radius: {name}")
                    elif not is_coordinate_allowed(
                        float(candidate["latitude"]),
                        float(candidate["longitude"]),
                        location_context,
                    ):
                        print(f"[hotel-nearby] Rejected Maps result outside destination: {name}")
                    else:
                        candidates.setdefault(str(candidate["source_id"]), candidate)
                    _append_to_maps_cache(name, candidate)
                except Exception as exc:
                    print(f"[hotel-nearby] Could not resolve {name} near hotel: {exc}")
                    _append_to_maps_cache(name, None)
                time.sleep(0.75)
        finally:
            context.close()
            browser.close()
    return list(candidates.values())


def _google_maps_detail_from_page(page: Any) -> Dict[str, Any]:
    descriptions = page.locator(
        '.PYvSYb, [data-attrid*="description"]'
    ).all_inner_texts()
    image_nodes = page.locator("img").evaluate_all(
        """elements => elements.map(element => ({
            src: element.currentSrc || element.src,
            width: element.naturalWidth,
            height: element.naturalHeight
        }))"""
    )
    detail = _normalize_google_maps_detail(descriptions, image_nodes)
    categories = [
        text.strip()
        for text in page.locator(".DkEaL").all_inner_texts()
        if text.strip()
    ]
    detail["place_category"] = categories[0] if categories else None
    detail["official_website"] = _google_maps_official_website(page)
    hour_buttons = page.locator("button[aria-label]")
    hour_labels = [
        hour_buttons.nth(index).get_attribute("aria-label") or ""
        for index in range(hour_buttons.count())
    ]
    detail.update(_parse_google_maps_hours(hour_labels))

    rating = None
    review_count = None
    rating_nodes = page.locator('[role="img"]')
    for index in range(min(rating_nodes.count(), 10)):
        label = rating_nodes.nth(index).get_attribute("aria-label") or ""
        if "sao" in label.lower() or "star" in label.lower():
            match = re.search(r"(\d+(?:[.,]\d+)?)", label)
            if match:
                rating = float(match.group(1).replace(",", "."))
            review_match = re.search(r"(?:sao|stars?)\s*([\d.,]+)", label, re.IGNORECASE)
            if review_match:
                rev_str = review_match.group(1).replace(".", "").replace(",", "")
                if rev_str.isdigit():
                    review_count = int(rev_str)
            break
    
    if rating is not None:
        detail["rating"] = rating
    if review_count is not None:
        detail["review_count"] = review_count

    return detail


def _json_ld_description_candidates(payloads: List[str]) -> List[str]:
    """Read usable place/business descriptions from embedded Schema.org JSON-LD."""
    descriptions: List[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        raw_types = value.get("@type") or []
        types = raw_types if isinstance(raw_types, list) else [raw_types]
        normalized_types = {str(item).casefold() for item in types}
        description = _trim_incomplete_description(value.get("description") or "")
        if (
            normalized_types.intersection(OFFICIAL_DESCRIPTION_SCHEMA_TYPES)
            and _is_usable_attraction_description(description)
            and description not in descriptions
        ):
            descriptions.append(description)
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                visit(nested)

    for payload in payloads:
        try:
            visit(json.loads(payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return descriptions


def _official_site_detail_from_page(page: Any, website_url: str) -> Dict[str, Any]:
    meta_descriptions: List[str] = []
    for selector in ("meta[name='description']", "meta[property='og:description']"):
        nodes = page.locator(selector)
        for index in range(min(nodes.count(), 2)):
            content = nodes.nth(index).get_attribute("content") or ""
            if content.strip():
                meta_descriptions.append(_trim_incomplete_description(content))
    json_ld_nodes = page.locator('script[type="application/ld+json"]')
    json_ld_payloads = [
        json_ld_nodes.nth(index).inner_text(timeout=2_000) or ""
        for index in range(min(json_ld_nodes.count(), 20))
    ]
    body_nodes = page.locator(
        "main p, article p, [class*='about' i] p, [id*='about' i] p"
    )
    try:
        body_descriptions = body_nodes.all_inner_texts()
    except Exception:
        body_descriptions = []
    description = None
    for candidates in (
        _json_ld_description_candidates(json_ld_payloads),
        body_descriptions,
        meta_descriptions,
    ):
        usable = [
            _trim_incomplete_description(text)
            for text in candidates
            if _is_usable_attraction_description(text)
        ]
        if usable:
            description = max(usable, key=len)
            break
    images: List[str] = []
    og_image = page.locator("meta[property='og:image']")
    if og_image.count():
        source = urljoin(website_url, og_image.first.get_attribute("content") or "")
        if _is_safe_official_site_url(source) and _same_site_host(source, website_url):
            images.append(source)
    image_nodes = page.locator("img").evaluate_all(
        """elements => elements.map(element => ({
            src: element.currentSrc || element.src,
            width: element.naturalWidth,
            height: element.naturalHeight
        }))"""
    )
    for node in image_nodes:
        source = urljoin(website_url, str(node.get("src") or ""))
        width = int(node.get("width") or 0)
        height = int(node.get("height") or 0)
        if (
            width < 300
            or height < 200
            or not _is_safe_official_site_url(source)
            or not _same_site_host(source, website_url)
            or source in images
        ):
            continue
        images.append(source)
        if len(images) == 3:
            break
    return {"description": description, "images": images}


def _load_official_site_detail(context: Any, website_url: str) -> Dict[str, Any]:
    if not _is_supported_official_content_url(website_url):
        return {"description": None, "images": []}
    official_page = context.new_page()
    try:
        official_page.goto(
            website_url,
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        if (
            not _is_supported_official_content_url(official_page.url or "")
            or not _same_site_host(website_url, official_page.url or "")
        ):
            return {"description": None, "images": []}
        official_page.wait_for_timeout(750)
        return _official_site_detail_from_page(official_page, official_page.url)
    finally:
        official_page.close()


def _load_google_maps_detail(page: Any, url: str) -> Dict[str, Any]:
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    _accept_google_consent(page)
    if "/maps/search/" in (page.url or ""):
        try:
            page.wait_for_url(re.compile(r".*/maps/place/.*"), timeout=10_000)
        except Exception:
            place_links = page.locator('a[href*="/maps/place/"]')
            for index in range(min(place_links.count(), 10)):
                place_url = place_links.nth(index).get_attribute("href") or ""
                if not _is_google_maps_place_url(place_url):
                    continue
                page.goto(
                    place_url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                break
    page.wait_for_selector("h1", state="attached", timeout=10_000)
    page.wait_for_timeout(1_000)
    _raise_if_google_blocked(page)
    return _google_maps_detail_from_page(page)


def enrich_google_maps_records(
    records: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    destination_name: str,
    fast_poc_mode: bool = False,
) -> List[Dict[str, Any]]:
    """Enrich only selected records from rendered Google Maps detail panels."""
    enriched = []
    for record in records:
        enriched_record = dict(record)
        cleaned_name = sanitize_attraction_name(enriched_record.get("name", ""))
        if cleaned_name:
            enriched_record["name"] = cleaned_name
        if not _is_usable_attraction_description(
            enriched_record.get("description")
        ):
            enriched_record["description"] = None
        enriched.append(enriched_record)
    if not enriched:
        return enriched
    total_records = len(enriched)
    print(
        "[google-maps-poc] Normalize enrichment: "
        f"starting {total_records} records."
    )
    urls_by_source_id = {
        str(candidate.get("source_id") or ""): str(candidate.get("url") or "")
        for candidate in candidates
    }
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        print(f"[google-maps-poc] Detail enrichment unavailable: {exc}")
        for record in enriched:
            if not record.get("description"):
                record["description"] = _fact_based_description(
                    record,
                    destination_name,
                )
        return enriched

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="vi-VN")
            page = context.new_page()
            try:
                for index, record in enumerate(enriched):
                    completed = index + 1
                    print(
                        "[google-maps-poc] Normalize enrichment: "
                        f"processing {completed}/{total_records}."
                    )
                    candidate_url = urls_by_source_id.get(
                        str(record.get("source_id") or ""),
                        "",
                    )
                    lookup_urls = _google_maps_enrichment_urls(
                        record,
                        candidate_url,
                        destination_name,
                        prefer_exact_place=fast_poc_mode,
                    )
                    enriched_record = record
                    place_category = ""
                    official_website = ""
                    blocked = False
                    for url in lookup_urls:
                        if (
                            enriched_record.get("description")
                            and enriched_record.get("images")
                        ):
                            break
                        try:
                            detail = _load_google_maps_detail(page, url)
                            enriched_record = _merge_google_maps_detail(
                                enriched_record,
                                detail,
                            )
                            place_category = str(
                                detail.get("place_category") or place_category
                            )
                            if place_category and enriched_record.get("category") == "Other activities":
                                # Map the Google Maps place category to one of our internal categories
                                norm_cat = place_category.lower()
                                if any(term in norm_cat for term in ("bảo tàng", "museum", "di tích", "heritage", "temple", "chùa", "đền", "thờ", "dinh", "palace")):
                                    enriched_record["category"] = "Museums & culture"
                                elif any(term in norm_cat for term in ("công viên", "park", "beach", "biển", "đảo", "island", "thác", "nature")):
                                    enriched_record["category"] = "Nature & outdoor"
                                elif any(term in norm_cat for term in ("chợ", "market", "theater", "nhà hát", "giải trí", "entertainment", "cơ quan")):
                                    enriched_record["category"] = "Entertainment & tickets"
                                elif "nhà hàng" in norm_cat or "restaurant" in norm_cat:
                                    enriched_record["category"] = "Restaurants & cafes"
                                elif "khách sạn" in norm_cat or "hotel" in norm_cat:
                                    enriched_record["category"] = "Hotels & lodging"
                            official_website = str(
                                detail.get("official_website") or official_website
                            )
                            if fast_poc_mode:
                                break
                        except RuntimeError as exc:
                            print(
                                f"[google-maps-poc] Stopped detail enrichment: {exc}"
                            )
                            blocked = True
                            break
                        except Exception as exc:
                            print(
                                "[google-maps-poc] Kept available data after detail "
                                f"lookup failed for {record.get('name')}: {exc}"
                            )
                        if not fast_poc_mode:
                            time.sleep(0.5)
                    if official_website and _needs_official_site_enrichment(
                        enriched_record
                    ):
                        print(
                            "[google-maps-poc] Normalize enrichment: "
                            f"official-site fallback for {completed}/{total_records}."
                        )
                        try:
                            enriched_record = _merge_official_site_detail(
                                enriched_record,
                                _load_official_site_detail(context, official_website),
                            )
                        except Exception as exc:
                            print(
                                "[google-maps-poc] Kept Maps data after official-site "
                                f"lookup failed for {record.get('name')}: {exc}"
                            )
                    if (
                        not _is_usable_attraction_description(
                            enriched_record.get("description")
                        )
                        or len(
                            str(enriched_record.get("description") or "").strip()
                        )
                        < 80
                    ):
                        print(
                            "[google-maps-poc] Normalize enrichment: "
                            f"grounded-description fallback for "
                            f"{completed}/{total_records}."
                        )
                        grounded_detail = enrich_description_from_sources(
                            page,
                            enriched_record,
                            destination_name,
                        )
                        if grounded_detail:
                            enriched_record["description"] = grounded_detail[
                                "description"
                            ]
                            print(
                                "[google-maps-poc] Normalize enrichment: "
                                f"grounded description accepted for "
                                f"{completed}/{total_records} from "
                                f"{grounded_detail['source_url']}."
                            )
                    if not enriched_record.get("description"):
                        enriched_record["description"] = _fact_based_description(
                            enriched_record,
                            destination_name,
                            place_category,
                        )
                    enriched[index] = enriched_record
                    if blocked:
                        print(
                            "[google-maps-poc] Normalize enrichment: "
                            f"stopped at {completed}/{total_records}."
                        )
                        break
                    print(
                        "[google-maps-poc] Normalize enrichment: "
                        f"completed {completed}/{total_records}."
                    )
            finally:
                context.close()
                browser.close()
    except Exception as exc:
        print(f"[google-maps-poc] Detail enrichment unavailable: {exc}")
    for record in enriched:
        if not record.get("description"):
            record["description"] = _fact_based_description(
                record,
                destination_name,
            )
    return enriched


def collect_google_maps_attractions(
    destination_name: str,
    location_context: Dict[str, Any],
    destination_id: str,
    item_limit: int,
) -> List[Dict[str, Any]]:
    candidates = scrape_google_maps_candidates(
        destination_name,
        location_context,
        candidate_limit=max(item_limit * 4, item_limit),
    )
    cleaned_candidates = validate_clean_google_maps_candidates(
        candidates,
        location_context,
    )
    records = normalize_google_maps_candidates(
        cleaned_candidates,
        destination_id,
        destination_name,
        item_limit,
        fast_poc_mode=True,
    )
    return select_diverse_attractions(deduplicate_attractions(records), item_limit)
