import math
import os
import time
from typing import Any, Dict, Optional, Tuple

from attraction_utils import is_coordinate_allowed, parse_coordinates
from google_maps_pipeline import scrape_google_maps_destination


NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_GEOCODE_CACHE: Dict[str, Optional[Tuple[float, float]]] = {}
_LAST_REQUEST_AT = 0.0


def crawler_user_agent() -> str:
    contact = os.getenv("VSF_CRAWLER_CONTACT", "").strip()
    if contact:
        return f"VSFAttractionCrawler/1.0 ({contact})"
    return "VSFAttractionCrawler/1.0"


def _nominatim_get(params: Dict[str, Any]) -> Any:
    global _LAST_REQUEST_AT
    import requests

    elapsed = time.monotonic() - _LAST_REQUEST_AT
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    response = requests.get(
        NOMINATIM_SEARCH_URL,
        params=params,
        headers={"User-Agent": crawler_user_agent()},
        timeout=30,
    )
    _LAST_REQUEST_AT = time.monotonic()
    response.raise_for_status()
    return response.json()


def resolve_location_context(
    destination_name: str,
    location_coords: str = "",
    radius_meters: int = 20_000,
) -> Dict[str, Any]:
    """Use supplied coordinates, otherwise resolve a strict Vietnam boundary."""
    if location_coords and location_coords.strip():
        latitude, longitude = parse_coordinates(location_coords)
        return {
            "mode": "radius",
            "latitude": latitude,
            "longitude": longitude,
            "radius_meters": int(radius_meters),
            "destination_coordinates": f"{latitude},{longitude}",
            "coordinate_source": "provided",
        }

    results = _nominatim_get(
        {
            "q": f"{destination_name}, Vietnam",
            "format": "jsonv2",
            "polygon_geojson": 1,
            "addressdetails": 1,
            "countrycodes": "vn",
            "limit": 5,
        }
    )
    for result in results:
        administrative_address_types = {
            "administrative",
            "borough",
            "city",
            "county",
            "district",
            "municipality",
            "province",
            "state",
            "town",
        }
        is_current_administrative = (
            result.get("category") == "boundary"
            and result.get("type") == "administrative"
        ) or result.get("addresstype") in administrative_address_types
        is_historic_city_boundary = (
            result.get("category") == "boundary"
            and result.get("type") == "historic"
            and result.get("addresstype") == "historic"
        )
        if not (is_current_administrative or is_historic_city_boundary):
            continue
        geometry = result.get("geojson") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        address = result.get("address") or {}
        if address.get("country_code", "").lower() != "vn":
            continue
        latitude = float(result["lat"])
        longitude = float(result["lon"])
        bounding_box = [float(value) for value in result.get("boundingbox", [])]
        search_radius = 20_000
        if len(bounding_box) == 4:
            north_south = abs(bounding_box[1] - bounding_box[0]) * 111_000 / 2
            east_west = (
                abs(bounding_box[3] - bounding_box[2])
                * 111_000
                * max(0.2, abs(math.cos(math.radians(latitude))))
                / 2
            )
            search_radius = min(75_000, max(20_000, int((north_south**2 + east_west**2) ** 0.5)))
        context = {
            "mode": "boundary",
            "latitude": latitude,
            "longitude": longitude,
            "geometry": geometry,
            "bounding_box": bounding_box,
            "search_radius_meters": search_radius,
            "display_name": result.get("display_name"),
            "destination_coordinates": f"{latitude},{longitude}",
            "coordinate_source": "openstreetmap",
        }
        try:
            google_destination = scrape_google_maps_destination(destination_name)
        except Exception as exc:
            print(
                "[destination] Google Maps center lookup failed; "
                f"using the OSM boundary center: {exc}"
            )
            google_destination = None
        if google_destination:
            google_latitude = float(google_destination["latitude"])
            google_longitude = float(google_destination["longitude"])
            if is_coordinate_allowed(google_latitude, google_longitude, context):
                context.update(
                    {
                        "latitude": google_latitude,
                        "longitude": google_longitude,
                        "destination_coordinates": (
                            f"{google_latitude},{google_longitude}"
                        ),
                        "coordinate_source": google_destination["source"],
                        "google_maps_name": google_destination.get("name"),
                        "google_maps_address": google_destination.get("address"),
                        "google_maps_url": google_destination.get("url"),
                    }
                )
            else:
                print(
                    "[destination] Ignored Google Maps center outside the "
                    "resolved OSM administrative boundary."
                )
        return context
    raise ValueError(
        f"Could not resolve an administrative boundary for '{destination_name}' in Vietnam."
    )


def geocode_address(address: str, destination_name: str) -> Optional[Tuple[float, float]]:
    if not address or not address.strip():
        return None
    query = address.strip()
    if "vietnam" not in query.lower() and "viet nam" not in query.lower():
        query = f"{query}, {destination_name}, Vietnam"
    cache_key = query.casefold()
    if cache_key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[cache_key]

    results = _nominatim_get(
        {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "countrycodes": "vn",
            "limit": 3,
        }
    )
    for result in results:
        address_details = result.get("address") or {}
        if address_details.get("country_code", "").lower() == "vn":
            coordinates = (float(result["lat"]), float(result["lon"]))
            _GEOCODE_CACHE[cache_key] = coordinates
            return coordinates
    _GEOCODE_CACHE[cache_key] = None
    return None
