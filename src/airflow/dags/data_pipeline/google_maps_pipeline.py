import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

from attraction_utils import (
    deduplicate_attractions,
    is_coordinate_allowed,
    sanitize_attraction_name,
    select_diverse_attractions,
    stable_attraction_id,
)


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
        if "·" in line or "mở cửa" in normalized or "đóng cửa" in normalized:
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


def _google_maps_enrichment_urls(
    record: Dict[str, Any],
    candidate_url: str,
    destination_name: str,
) -> List[str]:
    """Search by the cleaned name first, retaining the exact place URL as fallback."""
    name = sanitize_attraction_name(record.get("name", ""))
    destination = sanitize_attraction_name(destination_name)
    urls: List[str] = []
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
    if _is_google_maps_place_url(candidate_url) and candidate_url not in urls:
        urls.append(candidate_url)
    return urls


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
            if 40 <= len((text or "").strip()) <= 1_000
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


def _google_image_identity(url: str) -> str:
    return re.sub(r"=w\d+-h\d+[^?]*$", "", url or "")


def _merge_google_maps_detail(
    record: Dict[str, Any],
    detail: Dict[str, Any],
) -> Dict[str, Any]:
    merged = dict(record)
    if detail.get("description"):
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
) -> List[Dict[str, Any]]:
    """Map clean cards to the canonical schema, then enrich their details."""
    records = [
        _google_maps_candidate_to_record(candidate, destination_id)
        for candidate in candidates
    ]
    enrichment_pool = select_diverse_attractions(
        deduplicate_attractions(records),
        enrichment_limit,
    )
    return enrich_google_maps_records(enrichment_pool, candidates, destination_name)


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
        page.wait_for_timeout(900)
        unchanged_rounds = unchanged_rounds + 1 if current_count == previous_count else 0
        previous_count = current_count


def _candidate_from_google_card(article: Any, fallback_category: str) -> Optional[Dict[str, Any]]:
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

    lines = [line.strip() for line in article.inner_text().splitlines() if line.strip()]
    return {
        "source_id": _google_maps_source_id(url),
        "name": name,
        "category": fallback_category,
        "latitude": coordinates[0],
        "longitude": coordinates[1],
        "rating": rating,
        "review_count": None,
        "description": _card_description(lines, name),
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
                page.wait_for_timeout(2_500)
                _raise_if_google_blocked(page)
                _scroll_results(page, target_per_query)
                articles = page.locator('[role="article"]')
                for index in range(min(articles.count(), target_per_query)):
                    try:
                        candidate = _candidate_from_google_card(
                            articles.nth(index),
                            category,
                        )
                    except Exception as exc:
                        print(f"[google-maps-poc] Skipped unreadable result card: {exc}")
                        continue
                    if candidate:
                        candidates.setdefault(candidate["source_id"], candidate)
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
    return detail


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
) -> List[Dict[str, Any]]:
    """Enrich only selected records from rendered Google Maps detail panels."""
    enriched = []
    for record in records:
        enriched_record = dict(record)
        cleaned_name = sanitize_attraction_name(enriched_record.get("name", ""))
        if cleaned_name:
            enriched_record["name"] = cleaned_name
        enriched.append(enriched_record)
    if not enriched:
        return enriched
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
                    candidate_url = urls_by_source_id.get(
                        str(record.get("source_id") or ""),
                        "",
                    )
                    lookup_urls = _google_maps_enrichment_urls(
                        record,
                        candidate_url,
                        destination_name,
                    )
                    enriched_record = record
                    place_category = ""
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
                        time.sleep(0.5)
                    if not enriched_record.get("description"):
                        enriched_record["description"] = _fact_based_description(
                            enriched_record,
                            destination_name,
                            place_category,
                        )
                    enriched[index] = enriched_record
                    if blocked:
                        break
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
    )
    return select_diverse_attractions(deduplicate_attractions(records), item_limit)
