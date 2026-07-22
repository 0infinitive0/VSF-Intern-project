import uuid
import random
import re
import time
from typing import List, Dict, Any, Optional

try:
    import requests
except ImportError:  # Allows pure transform tests outside the Airflow image.
    requests = None

try:
    import psycopg2
except ImportError:  # Allows pure transform tests outside the Airflow image.
    psycopg2 = None

from attraction_utils import (
    deduplicate_attractions,
    is_coordinate_allowed,
    normalize_category,
    sanitize_attraction_name,
    select_diverse_attractions,
)
from destination_geo import crawler_user_agent


OVERPASS_ENDPOINTS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

FOOD_AMENITIES = {"restaurant", "cafe", "bar"}
EXCLUDED_INDIVIDUAL_EXHIBITS = {"aircraft", "airplane"}

# ==========================================
# 1. EXTRACT: Fetch Data from OpenStreetMap & Wikipedia
# ==========================================

def is_valid_image_url(url: str) -> bool:
    """Filters out icons, maps, flags, logos, and SVGs to ensure high-quality attraction photos."""
    if not url:
        return False
    lower_url = url.lower()
    
    # Block vector graphics and small icons
    if lower_url.endswith(".svg") or lower_url.endswith(".gif") or ".svg.png" in lower_url:
        return False
        
    invalid_keywords = [
        "map", "logo", "flag", "icon", "symbol", "coat_of_arms", "locator", 
        "location", "banner", "signature", "emblem", "stub", "pushpin"
    ]
    if any(keyword in lower_url for keyword in invalid_keywords):
        return False
        
    return True

def _execute_overpass_query(query: str, source_label: str) -> List[Dict[str, Any]]:
    errors = []
    for endpoint_index, endpoint in enumerate(OVERPASS_ENDPOINTS):
        try:
            response = requests.post(
                endpoint,
                data=query.encode("utf-8"),
                headers={"User-Agent": crawler_user_agent()},
                timeout=90,
            )
            response.raise_for_status()
            return response.json().get("elements", [])
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
            if endpoint_index < len(OVERPASS_ENDPOINTS) - 1:
                time.sleep(2 ** endpoint_index)
    raise RuntimeError(
        f"All Overpass endpoints failed for {source_label}: {'; '.join(errors)}"
    )


def fetch_osm_attractions(location_coords: str, radius_meters: int = 20000, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Find attractions using OpenStreetMap's Overpass API.
    Splits the limit to prioritize attractions (80%) over food/cafes (20%).
    """
    lat, lng = location_coords.split(',')
    
    attr_limit = max(1, int(limit * 0.8)) if limit > 1 else limit
    food_limit = max(1, limit - attr_limit) if limit > 1 else 0
    
    query_parts = ["[out:json][timeout:60];"]

    # Use one atomic request so public instances apply only one rate-limit slot.
    # nwr covers nodes, ways, and relations with half as many clauses as the old
    # separate node/way union. Separate out statements preserve the 80/20 quota.
    if attr_limit > 0:
        query_parts.append(
            f"""
            (
              nwr["tourism"~"museum|attraction|viewpoint|theme_park|zoo|aquarium"]["name:vi"](around:{radius_meters},{lat},{lng});
              nwr["historic"]["historic"!~"aircraft|airplane"]["name:vi"](around:{radius_meters},{lat},{lng});
              nwr["leisure"~"park|nature_reserve|water_park|garden"]["name:vi"](around:{radius_meters},{lat},{lng});
              nwr["natural"~"beach|cave_entrance|peak|waterfall"]["name:vi"](around:{radius_meters},{lat},{lng});
            );
            out center {attr_limit};
            """
        )
            
    # 2. Fetch Food (Restaurants, Cafes, Bars)
    if food_limit > 0:
        query_parts.append(
            f"""
            nwr["amenity"~"restaurant|cafe|bar"]["name"](around:{radius_meters},{lat},{lng});
            out center {food_limit};
            """
        )

    return _execute_overpass_query("\n".join(query_parts), "OSM attractions and food")

def fetch_wikipedia_details(name: str, region: str = "", wiki_tag: str = None) -> Dict[str, Any]:
    """
    Fetch a description and image from Wikipedia.
    If OSM provides a `wikipedia` tag (e.g. "en:Vinpearl"), it queries that exact page.
    Otherwise, it falls back to Search to add geographic context.
    """
    details = {"description": "", "image_url": None}
    
    # Try English Wikipedia by default
    wiki_url = "https://en.wikipedia.org/w/api.php"
    
    if wiki_tag:
        parts = wiki_tag.split(":", 1)
        if len(parts) == 2:
            lang, exact_title = parts
            wiki_url = f"https://{lang}.wikipedia.org/w/api.php"
        else:
            exact_title = wiki_tag
            
        params = {
            "action": "query",
            "prop": "extracts|pageimages",
            "exintro": True,
            "explaintext": True,
            "pithumbsize": 800,
            "titles": exact_title,
            "format": "json"
        }
    else:
        search_term = f"{name} {region}".strip()
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": search_term,
            "gsrlimit": 1,
            "prop": "extracts|pageimages",
            "exintro": True,
            "explaintext": True,
            "pithumbsize": 800,
            "format": "json"
        }
    
    for attempt in range(3):
        try:
            headers = {'User-Agent': crawler_user_agent()}
            response = requests.get(wiki_url, params=params, headers=headers, timeout=30)
            
            # Handle rate limiting specifically
            if response.status_code == 429:
                sleep_time = int(response.headers.get("Retry-After", 5 * (attempt + 1)))
                print(f"    [Wiki 429] Rate Limit hit for {name}. Sleeping for {sleep_time}s...")
                time.sleep(sleep_time)
                continue
                
            response.raise_for_status()
            data = response.json()
            pages = data.get("query", {}).get("pages", {})
            
            for page_id, page_data in pages.items():
                if page_id != "-1":
                    wiki_title = page_data.get("title", "")
                    desc = page_data.get("extract", "")
                    
                    # Prevent completely unrelated search results (e.g. USS Pigeon for "Hòn Chụt")
                    # ONLY apply this strict filter if we used search (no wiki_tag)
                    if not wiki_tag:
                        name_words = set(re.findall(r'\w+', name.lower()))
                        title_words = set(re.findall(r'\w+', wiki_title.lower()))
                        
                        if not (name.lower() in wiki_title.lower()) and not name_words.intersection(title_words):
                            print(f"    [Wiki Reject] '{wiki_title}' is completely unrelated to '{name}'")
                            return details # Return empty to avoid hallucinated descriptions
                        
                    # Reject obvious non-geographic disambiguations
                    lower_desc = desc.lower()
                    if any(x in lower_desc for x in ["video game", "fictional", "film series", "album by"]):
                        return details # Return empty to avoid pollution
                        
                    # Reject descriptions that are obviously about movies, songs, or novels (e.g. "Good Morning, Vietnam")
                    if re.search(r'is a.*? (film|movie|song|album|television series|novel|book)', lower_desc[:150]):
                        print(f"    [Wiki Reject] '{wiki_title}' appears to be media, not a place.")
                        return details
                        
                    details["description"] = desc
                    if "thumbnail" in page_data:
                        img_url = page_data["thumbnail"].get("source")
                        if is_valid_image_url(img_url):
                            details["image_url"] = img_url
                    return details # Found a match
            break # Break loop if request succeeds but no match found
        except Exception as e:
            if attempt == 2:
                print(f"Error fetching Wiki for {name}: {e}")
            else:
                time.sleep(2)
        
    return details

def fetch_wikidata_details(wikidata_id: str) -> Dict[str, Any]:
    """
    Fetch images directly from Wikidata using the P18 (image) property.
    """
    details = {"images": []}
    url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbgetclaims",
        "entity": wikidata_id,
        "property": "P18",
        "format": "json"
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers={'User-Agent': crawler_user_agent()},
            timeout=10,
        )
        if resp.status_code == 200:
            claims = resp.json().get("claims", {}).get("P18", [])
            for claim in claims:
                filename = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
                if filename:
                    safe_filename = filename.replace(' ', '_')
                    image_url = f"https://commons.wikimedia.org/w/index.php?title=Special:Redirect/file/{safe_filename}"
                    if is_valid_image_url(image_url):
                        details["images"].append(image_url)
    except Exception as e:
        print(f"Error fetching Wikidata: {e}")
    return details

def fetch_real_ratings(name: str, region: str) -> Dict[str, Any]:
    """
    Scrape real ratings and review counts from DuckDuckGo HTML search results.
    """
    details = {"rating": None, "review_count": None}
    search_query = f"{name} {region} tripadvisor rating".replace(' ', '+')
    url = f"https://html.duckduckgo.com/html/?q={search_query}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            text = resp.text
            rating_match = re.search(r'(\d\.\d)(?:/5|\s+of\s+5|\s+out\s+of\s+5)', text)
            if rating_match:
                details["rating"] = float(rating_match.group(1))
            
            review_match = re.search(r'([\d,]+)\s+reviews?', text, re.IGNORECASE)
            if review_match:
                details["review_count"] = int(review_match.group(1).replace(',', ''))
    except Exception as e:
        print(f"Error scraping ratings for {name}: {e}")
        
    return details

# ==========================================
# 2. DATABASE HELPERS
# ==========================================

def get_vietnam_region(name: str) -> str:
    """
    Roughly categorizes major Vietnamese destinations into North, Central, or South.
    """
    name_lower = name.lower()
    
    north = ["hà nội", "hanoi", "hải phòng", "ninh bình", "hạ long", "ha long", "sapa", "sa pa"]
    central = ["đà nẵng", "da nang", "huế", "hue", "hội an", "hoi an", "nha trang", "đà lạt", "da lat", "quy nhơn", "phú yên"]
    south = ["hồ chí minh", "ho chi minh", "saigon", "sài gòn", "cần thơ", "can tho", "phú quốc", "phu quoc", "vũng tàu"]
    
    if any(x in name_lower for x in north):
        return "Miền Bắc (North Vietnam)"
    if any(x in name_lower for x in central):
        return "Miền Trung (Central Vietnam)"
    if any(x in name_lower for x in south):
        return "Miền Nam (South Vietnam)"
        
    return "Vietnam"

def get_or_create_destination(name: str, coords: str, db_conn_kwargs: Dict[str, str]) -> str:
    """
    Creates a destination or refreshes its coordinates when it already exists.
    """
    select_query = "SELECT id FROM destinations WHERE name = %s LIMIT 1;"
    update_query = """
        UPDATE destinations
        SET coordinates = COALESCE(NULLIF(%s, ''), coordinates),
            region = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
    """
    insert_query = "INSERT INTO destinations (name, coordinates, region) VALUES (%s, %s, %s) RETURNING id;"
    
    conn = None
    try:
        conn = psycopg2.connect(**db_conn_kwargs)
        cursor = conn.cursor()
        
        cursor.execute(select_query, (name,))
        result = cursor.fetchone()
        region = get_vietnam_region(name)

        if result:
            cursor.execute(update_query, (coords, region, result[0]))
            conn.commit()
            return str(result[0])

        cursor.execute(insert_query, (name, coords, region))
        new_id = cursor.fetchone()[0]
        conn.commit()
        return str(new_id)
        
    except Exception as e:
        print(f"Database error in get_or_create_destination: {e}")
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            cursor.close()
            conn.close()

# ==========================================
# 3. TRANSFORM: Map to Attractions Schema
# ==========================================

def _osm_category(tags: Dict[str, Any], name: str, description: str = "") -> str:
    amenity = tags.get("amenity")
    tourism = tags.get("tourism")
    leisure = tags.get("leisure")
    if amenity in {"restaurant", "cafe", "bar"}:
        return "Restaurants & cafes"
    if tourism == "museum" or tags.get("historic"):
        return "Museums & culture"
    if tourism in {"theme_park", "zoo", "aquarium"} or leisure == "water_park":
        return "Entertainment & tickets"
    if (
        tourism == "viewpoint"
        or tags.get("natural")
        or leisure in {"park", "nature_reserve", "garden"}
    ):
        return "Nature & outdoor"
    return normalize_category(name, description, is_tour=False)


def _is_food_place(tags: Dict[str, Any]) -> bool:
    return tags.get("amenity") in FOOD_AMENITIES


def _is_eligible_osm_place(tags: Dict[str, Any]) -> bool:
    """Reject individual exhibits and require localized names for attractions."""
    if tags.get("aircraft:type"):
        return False
    if tags.get("historic") in EXCLUDED_INDIVIDUAL_EXHIBITS:
        return False
    if tags.get("memorial") in EXCLUDED_INDIVIDUAL_EXHIBITS:
        return False
    if _is_food_place(tags):
        return bool((tags.get("name:vi") or tags.get("name") or "").strip())
    return bool((tags.get("name:vi") or "").strip())


def transform_to_attraction(osm_element: Dict[str, Any], wiki_details: Dict[str, Any], destination_id: str, rating_details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms OSM + Wikipedia + Scraped data into the `attractions` table schema.
    """
    tags = osm_element.get("tags", {})
    
    # 1. Name
    name = tags.get("name:vi") or tags.get("name:en") or tags.get("name") or "Unknown Attraction"
    
    # 2. Description (From Wikipedia, fallback to basic OSM data)
    description = (
        wiki_details.get("description")
        or tags.get("description:en")
        or tags.get("description")
    )
        
    # 3. Category
    category = _osm_category(tags, name, description)
    
    # 4. Opening and Closing times (Parsed from OSM opening_hours)
    opening_time = None
    closing_time = None
    osm_hours = tags.get("opening_hours")
    if osm_hours:
        time_match = re.search(r'(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})', osm_hours)
        if time_match:
            opening_time = time_match.group(1) + ":00"
            closing_time = time_match.group(2) + ":00"
            
    # Parse Ticket Price
    fee_tag = tags.get("fee")
    ticket_price = None
    if fee_tag == "no":
        ticket_price = 0.00
    
    # 5. Rating & Reviews (From DDG Web Scraper)
    rating = rating_details.get("rating")
    review_count = rating_details.get("review_count")
    
    # Generate a deterministic UUID based on the unique OSM ID so we don't insert duplicates
    osm_id = str(osm_element.get('id', name))
    osm_unique_key = f"{osm_element.get('type', 'element')}:{osm_id}"
    deterministic_id = str(uuid.uuid5(uuid.NAMESPACE_OID, osm_unique_key))
    
    # 6. Coordinates
    coords = None
    if osm_element.get("type") == "node":
        coords = f"{osm_element.get('lat')},{osm_element.get('lon')}"
    elif osm_element.get("type") in {"way", "relation"} and "center" in osm_element:
        coords = f"{osm_element['center'].get('lat')},{osm_element['center'].get('lon')}"
        
    # 7. Images
    images = []
    if wiki_details.get("image_url"):
        images.append(wiki_details["image_url"])
    if wiki_details.get("images"):
        images.extend(wiki_details["images"])
    images = list(set(images)) # Deduplicate

    return {
        "id": deterministic_id,
        "destination_id": destination_id,
        "name": name,
        "description": description,
        "category": category,
        "is_tour": False,
        "estimated_duration_minutes": None,
        "opening_time": opening_time,
        "closing_time": closing_time,
        "departure_schedule": None,
        "ticket_price_adult": ticket_price,
        "ticket_price_child": ticket_price,
        "rating": rating,
        "review_count": review_count,
        "coordinates": coords,
        "images": images,
        "source": "osm",
        "source_id": osm_unique_key,
        "latitude": float(coords.split(",", 1)[0]) if coords else None,
        "longitude": float(coords.split(",", 1)[1]) if coords else None,
    }

# ==========================================
# 4. LOAD: Insert into PostgreSQL
# ==========================================

def load_attractions_to_db(attractions_data: List[Dict[str, Any]], db_conn_kwargs: Dict[str, str]):
    """
    Inserts a list of formatted attraction dictionaries into the PostgreSQL `attractions` table.
    """
    insert_query = """
        INSERT INTO attractions (
            id, destination_id, name, description, category, is_tour,
            estimated_duration_minutes, opening_time, closing_time, departure_schedule,
            ticket_price_adult, ticket_price_child, rating, review_count, coordinates, images
        ) VALUES (
            %(id)s, %(destination_id)s, %(name)s, %(description)s, %(category)s, %(is_tour)s,
            %(estimated_duration_minutes)s, %(opening_time)s, %(closing_time)s, %(departure_schedule)s,
            %(ticket_price_adult)s, %(ticket_price_child)s, %(rating)s, %(review_count)s, %(coordinates)s, %(images)s
        )
        ON CONFLICT (id) DO UPDATE SET
            destination_id = EXCLUDED.destination_id,
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            category = EXCLUDED.category,
            is_tour = EXCLUDED.is_tour,
            estimated_duration_minutes = EXCLUDED.estimated_duration_minutes,
            opening_time = EXCLUDED.opening_time,
            closing_time = EXCLUDED.closing_time,
            departure_schedule = EXCLUDED.departure_schedule,
            ticket_price_adult = EXCLUDED.ticket_price_adult,
            ticket_price_child = EXCLUDED.ticket_price_child,
            rating = EXCLUDED.rating,
            review_count = EXCLUDED.review_count,
            coordinates = EXCLUDED.coordinates,
            images = EXCLUDED.images,
            updated_at = CURRENT_TIMESTAMP;
    """
    
    sanitized_data = []
    for attraction in attractions_data:
        sanitized_name = sanitize_attraction_name(attraction.get("name", ""))
        if not sanitized_name:
            print("Skipped attraction whose name has no Vietnamese or English letters.")
            continue
        sanitized_data.append({**attraction, "name": sanitized_name})
    if not sanitized_data:
        raise ValueError("No attractions have a Vietnamese or English name.")

    conn = None
    try:
        conn = psycopg2.connect(**db_conn_kwargs)
        cursor = conn.cursor()
        
        cursor.executemany(insert_query, sanitized_data)
        conn.commit()
        
        print(f"Successfully loaded {len(sanitized_data)} attractions into the database.")
    except Exception as e:
        print(f"Database insertion error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            cursor.close()
            conn.close()

# ==========================================
# 5. ORCHESTRATION: Main Pipeline Flow
# ==========================================

def _osm_element_coordinates(osm_element: Dict[str, Any]) -> Optional[tuple]:
    if osm_element.get("type") == "node":
        latitude = osm_element.get("lat")
        longitude = osm_element.get("lon")
    else:
        center = osm_element.get("center") or {}
        latitude = center.get("lat")
        longitude = center.get("lon")
    if latitude is None or longitude is None:
        return None
    return float(latitude), float(longitude)


def collect_osm_attractions(
    destination_name: str,
    location_context: Dict[str, Any],
    destination_id: str,
    item_limit: int,
) -> List[Dict[str, Any]]:
    """Collect OSM places, enforce geography, enrich from Wikimedia, and normalize."""
    center = f"{location_context['latitude']},{location_context['longitude']}"
    radius_meters = int(
        location_context.get("radius_meters")
        or location_context.get("search_radius_meters")
        or 20_000
    )
    raw_results = fetch_osm_attractions(
        center,
        radius_meters=radius_meters,
        limit=max(item_limit * 4, item_limit),
    )
    raw_by_record_id: Dict[str, Dict[str, Any]] = {}
    normalized_candidates = []
    for place in raw_results:
        coordinates = _osm_element_coordinates(place)
        if not coordinates or not is_coordinate_allowed(*coordinates, location_context):
            continue
        tags = place.get("tags", {})
        if not _is_eligible_osm_place(tags):
            continue
        name = tags.get("name:vi") or tags.get("name:en") or tags.get("name")
        name_lower = name.lower()
        if any(
            word in name_lower
            for word in (
                "cây xăng",
                "hotel",
                "khách sạn",
                "homestay",
                "hostel",
                "motel",
                "resort",
                "villa",
            )
        ):
            continue

        normalized = transform_to_attraction(
            place,
            {},
            destination_id,
            {"rating": None, "review_count": None},
        )
        normalized_candidates.append(normalized)
        raw_by_record_id[normalized["id"]] = place

    unique_candidates = deduplicate_attractions(normalized_candidates)
    enrichment_pool = select_diverse_attractions(
        unique_candidates,
        max(item_limit * 2, item_limit),
    )
    enriched_candidates = []
    for candidate in enrichment_pool:
        place = raw_by_record_id[candidate["id"]]
        tags = place.get("tags", {})
        wiki_details = fetch_wikipedia_details(
            candidate["name"],
            destination_name,
            wiki_tag=tags.get("wikipedia"),
        )
        wikidata_id = tags.get("wikidata")
        if wikidata_id:
            wikidata_details = fetch_wikidata_details(wikidata_id)
            wiki_details.setdefault("images", []).extend(wikidata_details.get("images") or [])
        enriched_candidates.append(
            transform_to_attraction(
                place,
                wiki_details,
                destination_id,
                {"rating": None, "review_count": None},
            )
        )
        time.sleep(random.uniform(1.0, 2.0))

    return select_diverse_attractions(
        deduplicate_attractions(enriched_candidates),
        item_limit,
    )

def process_osm_pipeline(destination_name: str, location_coords: str, db_conn_kwargs: Dict[str, str]):
    """
    Runs the full ETL pipeline using OpenStreetMap and Wikipedia.
    """
    print(f"Starting pipeline for destination {destination_name}...")
    destination_id = get_or_create_destination(destination_name, location_coords, db_conn_kwargs)
    
    all_attractions_to_load = []
    
    print(f"Extracting places around {location_coords} via OSM...")
    osm_results = fetch_osm_attractions(location_coords, limit=10)
    
    for place in osm_results:
        tags = place.get("tags", {})
        if not _is_eligible_osm_place(tags):
            continue
        name = tags.get("name:vi") or tags.get("name:en") or tags.get("name")
        
        # Skip invalid or poorly tagged OSM data, and explicitly filter out ALL lodging
        if not name:
            continue
            
        name_lower = name.lower()
        if any(word in name_lower for word in ["cây xăng", "hotel", "khách sạn", "homestay", "hostel", "motel", "resort", "villa"]):
            continue
            
        print(f"  Fetching Wiki details for {name}...")
        wiki_tag = tags.get("wikipedia")
        wiki_details = fetch_wikipedia_details(name, destination_name, wiki_tag=wiki_tag)
        
        wikidata_id = tags.get("wikidata")
        if wikidata_id:
            wd_details = fetch_wikidata_details(wikidata_id)
            if wd_details["images"]:
                wiki_details.setdefault("images", []).extend(wd_details["images"])
                
        print(f"  Scraping real ratings for {name}...")
        rating_details = fetch_real_ratings(name, destination_name)
        
        print(f"  Transforming {name}...")
        transformed_data = transform_to_attraction(place, wiki_details, destination_id, rating_details)
        all_attractions_to_load.append(transformed_data)
        
        # Batching: Sleep to prevent blocking by search engines and Wikipedia
        sleep_time = random.uniform(1.0, 3.0)
        print(f"  [Sleep {sleep_time:.1f}s to prevent blocking...]")
        time.sleep(sleep_time)
        
    if all_attractions_to_load:
        print(f"Loading {len(all_attractions_to_load)} attractions to DB...")
        load_attractions_to_db(all_attractions_to_load, db_conn_kwargs)
    else:
        print("No valid attractions found to load.")
        
    print("Pipeline complete.")
