import html as html_module
import os
import random
import re
import time
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse

from attraction_utils import (
    deduplicate_attractions,
    is_coordinate_allowed,
    normalize_category,
    normalize_text,
    parse_duration_minutes,
    select_diverse_attractions,
    stable_attraction_id,
)
from destination_geo import crawler_user_agent, geocode_address


BOOKING_BASE_URL = "https://www.booking.com"
AGODA_BASE_URL = "https://www.agoda.com"
BLOCKING_MARKERS = (
    "verify you are human",
    "unusual traffic",
    "access denied",
    "captcha",
)


class ScrapeBlockedError(RuntimeError):
    pass


class _ProductHtmlParser(HTMLParser):
    """Extract semantic text without depending on generated CSS class names."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.capture: Optional[Dict[str, Any]] = None
        self.current_heading = ""
        self.headings: List[str] = []
        self.h1_values: List[str] = []
        self.paragraphs: List[Tuple[str, str]] = []
        self.addresses: List[Tuple[str, str]] = []
        self.visible_text: List[str] = []
        self.images: List[str] = []
        self.meta_description = ""
        self.ignored_depth = 0

    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.ignored_depth += 1
        if tag not in self._VOID_TAGS:
            self.depth += 1
        attributes = dict(attrs)
        accessible_label = (attributes.get("aria-label") or "").strip()
        if accessible_label:
            self.visible_text.append(accessible_label)
        if tag == "meta" and attributes.get("name", "").lower() == "description":
            self.meta_description = (attributes.get("content") or "").strip()
        if tag == "img":
            source = attributes.get("src") or attributes.get("data-src")
            if source:
                self.images.append(source)
        if self.capture is None and tag in {"h1", "h2", "h3", "p", "address"}:
            self.capture = {"tag": tag, "depth": self.depth, "parts": []}

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.visible_text.append(value)
        if self.capture is not None:
            self.capture["parts"].append(value)

    def handle_endtag(self, tag: str) -> None:
        if self.capture and self.capture["tag"] == tag and self.capture["depth"] == self.depth:
            value = " ".join(self.capture["parts"]).strip()
            if value:
                if tag == "h1":
                    self.h1_values.append(value)
                elif tag in {"h2", "h3"}:
                    self.current_heading = value
                    self.headings.append(value)
                elif tag == "p":
                    self.paragraphs.append((self.current_heading, value))
                elif tag == "address":
                    self.addresses.append((self.current_heading, value))
            self.capture = None
        if tag not in self._VOID_TAGS:
            self.depth = max(0, self.depth - 1)
        if tag in {"script", "style", "noscript"}:
            self.ignored_depth = max(0, self.ignored_depth - 1)


def _parse_html(html: str) -> _ProductHtmlParser:
    parser = _ProductHtmlParser()
    parser.feed(html or "")
    return parser


def _extract_rating_and_reviews(text: str) -> Tuple[Optional[float], Optional[int]]:
    rating = None
    denominator = 5.0
    rating_patterns = (
        r"(\d(?:[.,]\d)?)\s*stars?\s*rating",
        r"(\d(?:[.,]\d)?)\s*(?:out of|/)\s*(5|10)",
        r"(?:user reviews?|rating)[^\d]{0,20}(\d(?:[.,]\d)?)",
    )
    for pattern in rating_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            rating = float(match.group(1).replace(",", "."))
            if match.lastindex and match.lastindex >= 2 and match.group(2):
                denominator = float(match.group(2))
            break
    if rating is not None and denominator == 10:
        rating /= 2
    if rating is not None and not 0 <= rating <= 5:
        rating = None

    review_count = None
    review_match = re.search(
        r"(?:from\s+|\()([\d][\d,\.\s]*)\s+reviews?\)?",
        text,
        re.IGNORECASE,
    )
    if review_match:
        digits = re.sub(r"\D", "", review_match.group(1))
        if digits:
            review_count = int(digits)
    return rating, review_count


def _extract_price(text: str) -> Tuple[Optional[float], Optional[str]]:
    patterns = (
        ("VND", r"(?:VND\s*|₫\s*)([\d][\d.,\s]*)"),
        ("USD", r"(?:US\$\s*|USD\s*|\$\s*)([\d][\d.,\s]*)"),
    )
    for currency, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        raw = re.sub(r"\s", "", match.group(1))
        if currency == "VND":
            normalized = re.sub(r"[.,](?=\d{3}(?:\D|$))", "", raw)
        elif raw.count(",") and not raw.count("."):
            normalized = raw.replace(",", ".") if len(raw.rsplit(",", 1)[-1]) == 2 else raw.replace(",", "")
        else:
            normalized = raw.replace(",", "")
        try:
            return float(normalized), currency
        except ValueError:
            continue
    return None, None


def _section_value(
    parser: _ProductHtmlParser,
    heading_keywords: Iterable[str],
) -> Tuple[str, str]:
    keywords = tuple(normalize_text(keyword) for keyword in heading_keywords)
    for heading, value in parser.addresses + parser.paragraphs:
        normalized_heading = normalize_text(heading)
        if any(keyword in normalized_heading for keyword in keywords):
            return value, heading
    return "", ""


def _visible_value_after_label(
    parser: _ProductHtmlParser,
    labels: Iterable[str],
    stop_labels: Iterable[str],
) -> str:
    normalized_labels = {normalize_text(label) for label in labels}
    normalized_stops = {normalize_text(label) for label in stop_labels}
    for index, value in enumerate(parser.visible_text):
        if normalize_text(value) not in normalized_labels:
            continue
        for following in parser.visible_text[index + 1 : index + 12]:
            normalized = normalize_text(following)
            if normalized in normalized_stops:
                break
            if normalized not in normalized_labels and len(following) >= 30:
                return following
    return ""


def _product_summary_text(parser: _ProductHtmlParser, name: str) -> str:
    """Limit ratings and prices to the main product, excluding recommendation cards."""
    values = parser.visible_text
    normalized_name = normalize_text(name)
    start = next(
        (index for index, value in enumerate(values) if normalize_text(value) == normalized_name),
        0,
    )
    recommendation_markers = tuple(
        normalize_text(marker)
        for marker in (
            "while you're exploring",
            "you might also like",
            "similar activities",
            "recommended for you",
            "top in",
        )
    )
    end = len(values)
    for index in range(start + 1, len(values)):
        normalized = normalize_text(values[index])
        if any(normalized.startswith(marker) for marker in recommendation_markers):
            end = index
            break
    return " ".join(values[start:end])


def _extract_location(parser: _ProductHtmlParser) -> Tuple[str, str]:
    explicit_value, explicit_heading = _section_value(
        parser,
        ("location", "departure point", "meeting point", "pickup point", "where to meet"),
    )
    if explicit_value:
        return explicit_value, explicit_heading

    location_labels = {
        "location",
        "departure point",
        "meeting point",
        "pickup point",
        "where to meet",
        "attraction location",
    }
    normalized_headings = {normalize_text(heading) for heading in parser.headings}
    for index, value in enumerate(parser.visible_text):
        if normalize_text(value) != "location":
            continue
        location_kind = "Location"
        for following in parser.visible_text[index + 1 : index + 12]:
            normalized = normalize_text(following)
            if normalized in location_labels:
                location_kind = following
                continue
            if normalized in normalized_headings:
                break
            if len(following) <= 220 and ("," in following or "vietnam" in normalized):
                return following, location_kind
        break
    return "", ""


def _extract_duration(parser: _ProductHtmlParser, full_text: str) -> Optional[int]:
    for heading, value in parser.paragraphs:
        normalized_heading = normalize_text(heading)
        if any(label in normalized_heading for label in ("duration", "at a glance")):
            duration = parse_duration_minutes(value)
            if duration:
                return duration
    labelled_match = re.search(
        r"\bduration\s*:?\s*((?:\d+(?:\.\d+)?\s*(?:days?|hours?|hrs?|minutes?|mins?)\s*){1,3})",
        full_text,
        re.IGNORECASE,
    )
    return parse_duration_minutes(labelled_match.group(1)) if labelled_match else None


def _extract_embedded_coordinates(
    html: str,
    source: str,
) -> Tuple[Optional[float], Optional[float]]:
    if source != "booking":
        return None, None
    # Booking's product-location objects use quoted coordinate values. The
    # destination metadata elsewhere on the page uses numeric values, so this
    # avoids mistaking the city centre for the attraction itself.
    match = re.search(
        r'"latitude"\s*:\s*"(-?\d+(?:\.\d+)?)".{0,250}?'
        r'"longitude"\s*:\s*"(-?\d+(?:\.\d+)?)"',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None, None
    latitude = float(match.group(1))
    longitude = float(match.group(2))
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None, None
    return latitude, longitude


def _valid_images(images: Iterable[str], allowed_domains: Iterable[str]) -> List[str]:
    allowed = tuple(allowed_domains)
    result = []
    for image in images:
        lowered = image.lower()
        if not image.startswith("http") or not any(domain in lowered for domain in allowed):
            continue
        if any(token in lowered for token in ("logo", "icon", ".svg", "favicon", "flag-")):
            continue
        result.append(image)
    return list(dict.fromkeys(result))[:10]


def _parse_product_html(html: str, url: str, source: str) -> Dict[str, Any]:
    parser = _parse_html(html)
    full_text = " ".join(parser.visible_text)
    if not parser.h1_values:
        raise ValueError(f"{source} page did not contain a product heading: {url}")
    name = parser.h1_values[0]
    overview, _ = _section_value(
        parser,
        ("product overview", "about this activity", "about this experience", "description"),
    )
    if not overview:
        overview = _visible_value_after_label(
            parser,
            ("product overview", "about this activity", "about this experience", "description"),
            ("highlights", "location", "package options", "cancellation policy"),
        )
    description = parser.meta_description or overview
    address, location_heading = _extract_location(parser)
    latitude, longitude = _extract_embedded_coordinates(html, source)
    product_text = _product_summary_text(parser, name)
    rating, review_count = _extract_rating_and_reviews(product_text)
    price, currency = _extract_price(product_text)
    duration = _extract_duration(parser, full_text)
    normalized_name = normalize_text(name)
    is_tour = any(
        keyword in normalized_name
        for keyword in (
            " tour",
            "tour ",
            "boat trip",
            "cooking class",
            "cruise",
            "day trip",
            "excursion",
            "island hopping",
            "motorbike lesson",
            "snorkel",
            "training course",
            "transfer",
            "underwater walk",
        )
    )
    opening_time = None
    closing_time = None
    hours_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\s*[-–]\s*([01]?\d|2[0-3]):([0-5]\d)\b", product_text)
    if hours_match:
        opening_time = f"{int(hours_match.group(1)):02d}:{hours_match.group(2)}:00"
        closing_time = f"{int(hours_match.group(3)):02d}:{hours_match.group(4)}:00"

    if source == "booking":
        source_match = re.search(r"/(pr[a-z0-9]+)-", url, re.IGNORECASE)
        allowed_image_domains = ("bstatic.com", "booking.com")
    else:
        activity_id = (parse_qs(urlparse(url).query).get("activityId") or [""])[0]
        source_match = (
            re.match(r"^(\d+)$", activity_id)
            if activity_id
            else re.search(r"-(\d+)(?:[/?#]|$)", url)
        )
        allowed_image_domains = ("agoda.net", "agoda.com")
    if not source_match:
        raise ValueError(f"Could not extract {source} product ID from {url}")

    return {
        "source": source,
        "source_id": source_match.group(1).lower(),
        "source_url": url,
        "name": name,
        "description": description,
        "category": normalize_category(name, description, is_tour=is_tour),
        "is_tour": is_tour,
        "estimated_duration_minutes": duration,
        "opening_time": opening_time,
        "closing_time": closing_time,
        "departure_schedule": None,
        "ticket_price_adult": price,
        "ticket_price_child": None,
        "currency": currency,
        "rating": rating,
        "review_count": review_count,
        "address": address,
        "location_kind": location_heading,
        "latitude": latitude,
        "longitude": longitude,
        "images": _valid_images(parser.images, allowed_image_domains),
    }


def parse_booking_html(html: str, url: str) -> Dict[str, Any]:
    return _parse_product_html(html, url, "booking")


def parse_agoda_html(html: str, url: str) -> Dict[str, Any]:
    return _parse_product_html(html, url, "agoda")


def _canonical_agoda_product_url(href: str) -> Optional[str]:
    """Return a stable public Agoda activity URL, or None for non-product links."""
    absolute_url = urljoin(AGODA_BASE_URL, href)
    parsed = urlparse(absolute_url)
    hostname = (parsed.hostname or "").lower()
    if hostname != "agoda.com" and not hostname.endswith(".agoda.com"):
        return None

    if re.search(r"/activities/detail/vn/", parsed.path, re.IGNORECASE):
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    if not re.search(r"/activities/detail/?$", parsed.path, re.IGNORECASE):
        return None
    query = parse_qs(parsed.query)
    activity_id = (query.get("activityId") or [""])[0]
    if not activity_id.isdigit():
        return None
    canonical_query = {"activityId": activity_id}
    city_id = (query.get("cityId") or [""])[0]
    if city_id.isdigit():
        canonical_query["cityId"] = city_id
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            urlencode(canonical_query),
            "",
        )
    )


def _request_html(url: str, retries: int = 2) -> str:
    import requests

    for attempt in range(retries + 1):
        response = requests.get(
            url,
            headers={
                "User-Agent": crawler_user_agent(),
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=40,
        )
        lowered = response.text.lower()
        if response.status_code in {403, 429} or any(marker in lowered for marker in BLOCKING_MARKERS):
            raise ScrapeBlockedError(f"Web scraping was blocked at {url} ({response.status_code}).")
        if response.status_code >= 500 and attempt < retries:
            time.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        return response.text
    raise RuntimeError(f"Could not retrieve {url}")


def _destination_slug_candidates(destination_name: str) -> List[str]:
    words = normalize_text(destination_name).split()
    candidates = ["-".join(words), "".join(words)]
    aliases = {
        "ho chi minh": "ho-chi-minh-city",
        "saigon": "ho-chi-minh-city",
        "ha long": "ha-long",
        "phu quoc": "phu-quoc",
    }
    alias = aliases.get(" ".join(words))
    if alias:
        candidates.insert(0, alias)
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def _booking_search_url(destination_name: str) -> str:
    for slug in _destination_slug_candidates(destination_name):
        landing_url = f"{BOOKING_BASE_URL}/attractions/city/vn/{slug}.en-gb.html"
        try:
            page_html = _request_html(landing_url)
        except Exception as exc:
            if isinstance(exc, ScrapeBlockedError):
                raise
            continue
        destination_ids = re.findall(r"(?:dest_id|ufi)(?:=|%3D)(-?\d+)", page_html)
        if destination_ids:
            query = urlencode(
                {
                    "dest_id": destination_ids[0],
                    "sort_by": "trending",
                    "selected_currency": "VND",
                    "source": "city-cta",
                }
            )
            return f"{BOOKING_BASE_URL}/attractions/searchresults.html?{query}"
    raise ValueError(f"Booking.com has no discoverable Vietnam attraction page for '{destination_name}'.")


def _booking_product_links(search_html: str) -> List[str]:
    decoded = html_module.unescape(search_html).replace("\\u0026", "&")
    matches = re.findall(
        r"(?:https://www\.booking\.com)?(/attractions/vn/pr[a-z0-9]+-[^\"'<>?]+(?:\.[a-z-]+)?\.html)",
        decoded,
        re.IGNORECASE,
    )
    links = []
    for path in matches:
        clean_path = re.sub(r"\.(?:vi|fr|de|es)(?=\.html$)", ".en-gb", path, flags=re.IGNORECASE)
        links.append(urljoin(BOOKING_BASE_URL, clean_path))
    return list(dict.fromkeys(links))


def scrape_booking_candidates(destination_name: str, candidate_limit: int) -> List[Dict[str, Any]]:
    search_url = _booking_search_url(destination_name)
    product_links: List[str] = []
    for page_number in range(1, 11):
        parsed = urlparse(search_url)
        query = parse_qs(parsed.query)
        query["page"] = [str(page_number)]
        page_url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
        links = _booking_product_links(_request_html(page_url))
        before = len(product_links)
        product_links.extend(link for link in links if link not in product_links)
        if len(product_links) >= candidate_limit or len(product_links) == before:
            break
        time.sleep(random.uniform(2.0, 4.0))

    candidates = []
    for link in product_links[:candidate_limit]:
        separator = "&" if "?" in link else "?"
        product_url = f"{link}{separator}selected_currency=VND"
        try:
            candidates.append(parse_booking_html(_request_html(product_url), product_url))
        except ScrapeBlockedError:
            raise
        except Exception as exc:
            print(f"[booking] Skipping {link}: {exc}")
        time.sleep(random.uniform(3.0, 5.0))
    return candidates


def _first_visible(page: Any, selectors: Iterable[str]) -> Any:
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 5)):
            candidate = locator.nth(index)
            if candidate.is_visible():
                return candidate
    return None


def _agoda_browser_context_options() -> Dict[str, str]:
    # Let Playwright report the installed Chromium version. A stale UA can cause
    # Agoda to serve an incompatible client bundle with incomplete product data.
    return {"locale": "en-GB"}


def scrape_agoda_candidates(destination_name: str, candidate_limit: int) -> List[Dict[str, Any]]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Agoda scraping requires Playwright and Chromium in the Airflow image.") from exc

    candidates: List[Dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(**_agoda_browser_context_options())
        page = context.new_page()
        try:
            page.goto(f"{AGODA_BASE_URL}/activities", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)
            search_input = _first_visible(
                page,
                (
                    'input[placeholder*="Where" i]',
                    'input[placeholder*="destination" i]',
                    'input[placeholder*="search" i]',
                    'input[type="text"]',
                ),
            )
            if search_input is None:
                raise ValueError("Agoda Activities destination input was not found.")
            search_input.fill(destination_name)
            page.wait_for_timeout(2_000)
            destination_suggestions = page.get_by_text(destination_name, exact=True)
            for index in range(destination_suggestions.count()):
                suggestion = destination_suggestions.nth(index)
                if suggestion.is_visible():
                    suggestion.click()
                    break
            page.wait_for_timeout(1_000)
            if "/activities/search" not in page.url:
                search_button = page.get_by_role(
                    "button", name=re.compile("search", re.IGNORECASE)
                ).first
                if search_button.is_visible():
                    search_button.click()
                else:
                    search_input.press("Enter")
            page.wait_for_load_state("domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

            product_links: List[str] = []
            unchanged_rounds = 0
            for _ in range(20):
                count_before_collection = len(product_links)
                links = page.locator('a[href*="/activities/detail"]')
                for index in range(links.count()):
                    href = links.nth(index).get_attribute("href")
                    if href:
                        full_url = _canonical_agoda_product_url(href)
                        if not full_url:
                            continue
                        if full_url not in product_links:
                            product_links.append(full_url)
                if len(product_links) >= candidate_limit:
                    break
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2_000)
                unchanged_rounds = (
                    unchanged_rounds + 1
                    if len(product_links) == count_before_collection
                    else 0
                )
                if unchanged_rounds >= 3:
                    break

            for link in product_links[:candidate_limit]:
                detail_page = context.new_page()
                try:
                    detail_page.goto(link, wait_until="domcontentloaded", timeout=60_000)
                    try:
                        detail_page.wait_for_function(
                            r"""() => /Product Overview\s*\n\s*.{80,}?\n\s*Highlights/s
                                .test(document.body.innerText)""",
                            timeout=10_000,
                        )
                    except PlaywrightTimeoutError:
                        detail_page.wait_for_timeout(1_000)
                    content = detail_page.content()
                    lowered = content.lower()
                    if any(marker in lowered for marker in BLOCKING_MARKERS):
                        raise ScrapeBlockedError(f"Agoda blocked the rendered page at {link}.")
                    candidates.append(parse_agoda_html(content, link))
                except ScrapeBlockedError:
                    raise
                except PlaywrightTimeoutError as exc:
                    print(f"[agoda] Timed out at {link}: {exc}")
                except Exception as exc:
                    print(f"[agoda] Skipping {link}: {exc}")
                finally:
                    detail_page.close()
                page.wait_for_timeout(random.randint(3_000, 5_000))
        finally:
            context.close()
            browser.close()
    return candidates


def _candidate_has_strict_location(candidate: Dict[str, Any], location_context: Dict[str, Any]) -> bool:
    if not candidate.get("address"):
        return bool(candidate.get("name")) and not candidate.get("is_tour")
    if location_context.get("mode") != "boundary" or not candidate.get("is_tour"):
        return True
    location_kind = normalize_text(candidate.get("location_kind", ""))
    return not any(keyword in location_kind for keyword in ("departure", "meeting", "pickup"))


_FIXED_PLACE_TERMS = (
    "aquarium",
    "bar",
    "bath",
    "beach",
    "cafe",
    "cathedral",
    "church",
    "garden",
    "market",
    "museum",
    "pagoda",
    "palace",
    "park",
    "restaurant",
    "resort",
    "salon",
    "spa",
    "spring",
    "temple",
    "theater",
    "theatre",
    "tower",
    "waterfall",
    "zoo",
)


def _looks_like_fixed_place(candidate: Dict[str, Any]) -> bool:
    if candidate.get("is_tour"):
        return False
    name = normalize_text(candidate.get("name", ""))
    return any(term in name for term in _FIXED_PLACE_TERMS)


def _google_maps_coordinates_from_url(url: str) -> Optional[Tuple[float, float]]:
    match = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", url)
    if not match:
        match = re.search(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", url)
    if not match:
        return None
    latitude = float(match.group(1))
    longitude = float(match.group(2))
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude


def _google_maps_title_matches(product_name: str, page_title: str) -> bool:
    product_tokens = set(normalize_text(product_name).split())
    title_tokens = set(normalize_text(page_title.replace("- Google Maps", "")).split())
    ignored = {
        "admission",
        "booking",
        "experience",
        "nha",
        "show",
        "ticket",
        "trang",
        "vietnam",
    }
    product_tokens -= ignored
    title_tokens -= ignored
    if not product_tokens or not title_tokens:
        return False
    overlap = len(product_tokens & title_tokens)
    return overlap / min(len(product_tokens), len(title_tokens)) >= 0.6


def scrape_google_maps_coordinates(
    candidates: Iterable[Dict[str, Any]],
    destination_name: str,
) -> Dict[str, Tuple[float, float]]:
    fixed_names = list(
        dict.fromkeys(
            candidate["name"]
            for candidate in candidates
            if _looks_like_fixed_place(candidate) and candidate.get("name")
        )
    )
    if not fixed_names:
        return {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        print(f"[google-maps] Playwright unavailable: {exc}")
        return {}

    resolved: Dict[str, Tuple[float, float]] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="en-GB")
        page = context.new_page()
        try:
            for name in fixed_names:
                query = quote(f"{name}, {destination_name}, Vietnam")
                try:
                    page.goto(
                        f"https://www.google.com/maps/search/?api=1&query={query}",
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    page.wait_for_timeout(4_000)
                    coordinates = _google_maps_coordinates_from_url(page.url)
                    if (
                        "/place/" in page.url
                        and coordinates
                        and _google_maps_title_matches(name, page.title())
                    ):
                        resolved[name] = coordinates
                except Exception as exc:
                    print(f"[google-maps] Could not resolve {name}: {exc}")
        finally:
            context.close()
            browser.close()
    return resolved


def geofilter_ota_candidates(
    candidates: Iterable[Dict[str, Any]],
    destination_name: str,
    location_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    accepted = []
    unresolved_fixed_places = []
    for candidate in candidates:
        if not _candidate_has_strict_location(candidate, location_context):
            print(f"[{candidate.get('source')}] Rejected unverifiable location: {candidate.get('name')}")
            continue
        latitude = candidate.get("latitude")
        longitude = candidate.get("longitude")
        coordinates = (
            (float(latitude), float(longitude))
            if latitude is not None and longitude is not None
            else None
        )
        if coordinates is None:
            location_query = candidate.get("address") or candidate["name"]
            coordinates = geocode_address(location_query, destination_name)
        if not coordinates:
            if _looks_like_fixed_place(candidate):
                unresolved_fixed_places.append(candidate)
            else:
                print(f"[{candidate.get('source')}] Could not geocode: {candidate.get('name')}")
            continue
        latitude, longitude = coordinates
        if not is_coordinate_allowed(latitude, longitude, location_context):
            print(f"[{candidate.get('source')}] Rejected outside destination: {candidate.get('name')}")
            continue
        candidate = dict(candidate)
        candidate["latitude"] = latitude
        candidate["longitude"] = longitude
        accepted.append(candidate)

    map_coordinates = scrape_google_maps_coordinates(
        unresolved_fixed_places,
        destination_name,
    )
    for candidate in unresolved_fixed_places:
        coordinates = map_coordinates.get(candidate["name"])
        if not coordinates:
            print(f"[{candidate.get('source')}] Could not geocode: {candidate.get('name')}")
            continue
        latitude, longitude = coordinates
        if not is_coordinate_allowed(latitude, longitude, location_context):
            print(f"[{candidate.get('source')}] Rejected outside destination: {candidate.get('name')}")
            continue
        candidate = dict(candidate)
        candidate["latitude"] = latitude
        candidate["longitude"] = longitude
        accepted.append(candidate)
    return accepted


def candidate_to_db_record(candidate: Dict[str, Any], destination_id: str) -> Dict[str, Any]:
    price = candidate.get("ticket_price_adult") if candidate.get("currency") == "VND" else None
    return {
        "id": stable_attraction_id(candidate),
        "destination_id": destination_id,
        "name": candidate["name"],
        "description": candidate.get("description"),
        "category": candidate.get("category"),
        "is_tour": bool(candidate.get("is_tour")),
        "estimated_duration_minutes": candidate.get("estimated_duration_minutes"),
        "opening_time": candidate.get("opening_time"),
        "closing_time": candidate.get("closing_time"),
        "departure_schedule": candidate.get("departure_schedule"),
        "ticket_price_adult": price,
        "ticket_price_child": candidate.get("ticket_price_child") if candidate.get("currency") == "VND" else None,
        "rating": candidate.get("rating"),
        "review_count": candidate.get("review_count"),
        "coordinates": f"{candidate['latitude']},{candidate['longitude']}",
        "images": candidate.get("images") or [],
        "source": candidate.get("source"),
        "source_id": candidate.get("source_id"),
        "latitude": candidate.get("latitude"),
        "longitude": candidate.get("longitude"),
    }


def collect_ota_attractions(
    destination_name: str,
    location_context: Dict[str, Any],
    destination_id: str,
    item_limit: int,
    source: str = "both",
    allow_web_scraping: bool = False,
) -> List[Dict[str, Any]]:
    env_opt_in = os.getenv("ALLOW_OTA_WEB_SCRAPING", "").lower() in {"1", "true", "yes"}
    if not allow_web_scraping and not env_opt_in:
        raise ValueError(
            "OTA web scraping is disabled. Set the DAG parameter allow_ota_web_scraping=true "
            "or ALLOW_OTA_WEB_SCRAPING=true after confirming permission to crawl these sites."
        )
    if source not in {"booking", "agoda", "both"}:
        raise ValueError("source must be 'booking', 'agoda', or 'both'.")

    oversample = max(item_limit * 3, item_limit)
    candidates: List[Dict[str, Any]] = []
    if source in {"booking", "both"}:
        try:
            candidates.extend(scrape_booking_candidates(destination_name, oversample))
        except Exception as exc:
            if source == "booking":
                raise
            print(f"[booking] Source failed without stopping Agoda: {exc}")
    if source in {"agoda", "both"}:
        try:
            candidates.extend(scrape_agoda_candidates(destination_name, oversample))
        except Exception as exc:
            if source == "agoda":
                raise
            print(f"[agoda] Source failed without stopping Booking: {exc}")

    filtered = geofilter_ota_candidates(candidates, destination_name, location_context)
    deduplicated = deduplicate_attractions(filtered)
    selected = select_diverse_attractions(deduplicated, item_limit)
    return [candidate_to_db_record(candidate, destination_id) for candidate in selected]
