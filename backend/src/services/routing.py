import math
import logging
import requests
from typing import Optional, Dict, Any, Tuple
from functools import lru_cache

from src.config import get_settings

logger = logging.getLogger(__name__)

WALKING_THRESHOLD_KM = 1.2

def _haversine_km(origin: Tuple[float, float], dest: Tuple[float, float]) -> float:
    """Calculate the great circle distance between two points on the earth."""
    lat1, lon1 = origin
    lat2, lon2 = dest
    radius = 6371.0 # km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + math.cos(math.radians(lat1)) \
        * math.cos(math.radians(lat2)) * math.sin(dlon / 2) * math.sin(dlon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c

def _pick_profile(origin: Tuple[float, float], dest: Tuple[float, float]) -> str:
    """Chọn profile theo khoảng cách đường chim bay.
    Ngưỡng 1.2km ~ 15 phút đi bộ — quãng mà người đi du lịch thường đi bộ thay vì
    bắt xe. Đây là luật sản phẩm, không phải dữ liệu: nó quyết định HỎI Mapbox cái gì.
    Nhãn hiển thị luôn khớp profile đã gọi, nên con số trả về vẫn là thật.
    """
    if _haversine_km(origin, dest) < WALKING_THRESHOLD_KM:
        return "walking"
    return "driving-traffic"

class MapboxDirectionsClient:
    """Client for fetching route data from Mapbox Directions API v5."""
    
    BASE_URL = "https://api.mapbox.com/directions/v5/mapbox"
    TIMEOUT_SECONDS = 5
    
    @staticmethod
    @lru_cache(maxsize=1024)
    def get_route_info(
        origin_coords: Tuple[float, float], 
        dest_coords: Tuple[float, float],
        profile: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch route information between two coordinates using Mapbox API.
        Coordinates should be (latitude, longitude).
        Returns a dictionary with distance_km, duration_mins, polyline and profile if successful.
        Returns None if the request fails or no route is found.
        """
        settings = get_settings()
        token = settings.mapbox_access_token
        
        if not token:
            # We use a static attribute to warn only once
            if not getattr(MapboxDirectionsClient, "_warned_missing_token", False):
                logger.warning("MAPBOX_ACCESS_TOKEN is not set. Routing will be skipped and return None.")
                MapboxDirectionsClient._warned_missing_token = True
            return None

        origin_lat, origin_lon = origin_coords
        dest_lat, dest_lon = dest_coords
        
        # Mapbox expects {longitude},{latitude}
        url = f"{MapboxDirectionsClient.BASE_URL}/{profile}/{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
        
        params = {
            "overview": "full",
            "access_token": token
        }
        
        try:
            response = requests.get(url, params=params, timeout=MapboxDirectionsClient.TIMEOUT_SECONDS)
            
            if response.status_code == 401:
                logger.error("Mapbox API returned 401 Unauthorized. Check MAPBOX_ACCESS_TOKEN.")
                return None
            elif response.status_code == 422:
                logger.info("Mapbox API returned 422 Unprocessable Entity. Bad coordinates.")
                return None
            elif response.status_code == 429:
                logger.warning("Mapbox API returned 429 Too Many Requests. Rate limit exceeded.")
                return None
                
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == "Ok" and "routes" in data and len(data["routes"]) > 0:
                route = data["routes"][0]
                distance_meters = route.get("distance", 0.0)
                duration_seconds = route.get("duration", 0.0)
                geometry = route.get("geometry", "")
                
                return {
                    "distance_km": round(distance_meters / 1000.0, 2),
                    "duration_mins": round(duration_seconds / 60.0, 1),
                    "polyline": geometry,
                    "profile": profile
                }
            else:
                logger.warning(f"Mapbox API returned non-Ok code or no routes: {data.get('code')}")
                return None
                
        except requests.RequestException as e:
            logger.warning(f"Mapbox API request failed: {e}")
            return None

def parse_coordinates(value: Any) -> Optional[Tuple[float, float]]:
    """Parse coordinates from string ('lat,lng') or tuple/list into (lat, lng)."""
    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            return (float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            return None
    elif isinstance(value, str):
        try:
            parts = value.split(",", maxsplit=1)
            return (float(parts[0].strip()), float(parts[1].strip()))
        except (TypeError, ValueError):
            return None
    return None

def get_route_to_next(
    origin_coords: Any, 
    dest_coords: Any
) -> Optional[Dict[str, Any]]:
    """Helper function to get route info, handles string/tuple coordinates gracefully."""
    origin = parse_coordinates(origin_coords)
    dest = parse_coordinates(dest_coords)
    
    if not origin or not dest:
        return None
        
    profile = _pick_profile(origin, dest)

    # Ignore routing if coordinates are identical
    if origin == dest:
        return {
            "distance_km": 0.0,
            "duration_mins": 0.0,
            "polyline": "",
            "profile": profile
        }
        
    return MapboxDirectionsClient.get_route_info(origin, dest, profile)

def recalculate_itinerary_routes(trip_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recalculate route_to_next for all items in a trip_data dictionary.
    Calculates route between consecutive items on the same day.
    For the last item of each day, calculates route back to the hotel if hotel coordinates exist.
    """
    items = trip_data.get("itinerary_items") or []
    if not isinstance(items, list):
        return trip_data

    hotel_coords = None
    hotel = trip_data.get("hotel")
    if isinstance(hotel, dict):
        hotel_coords = hotel.get("coordinates")

    # Group items by day_number
    by_day: Dict[int, list] = {}
    for item in items:
        if isinstance(item, dict):
            day = item.get("day_number", 1)
            by_day.setdefault(day, []).append(item)

    for day, day_items in by_day.items():
        # Sort items by order_index if present
        day_items.sort(key=lambda x: x.get("order_index", 0))
        n = len(day_items)

        # First item of the day: route from hotel to first item if available
        if hotel_coords and n > 0:
            first_item = day_items[0]
            first_coords = first_item.get("coordinates")
            if first_coords:
                route_info = get_route_to_next(hotel_coords, first_coords)
                if route_info:
                    first_item["route_from_hotel"] = route_info

        for i in range(n):
            curr_item = day_items[i]
            curr_coords = curr_item.get("coordinates")
            
            if i < n - 1:
                next_item = day_items[i + 1]
                next_coords = next_item.get("coordinates")
                if curr_coords and next_coords:
                    route_info = get_route_to_next(curr_coords, next_coords)
                    if route_info:
                        curr_item["route_to_next"] = route_info
            else:
                # Last item of the day: route back to hotel if available and not already at hotel
                if curr_coords and hotel_coords:
                    route_info = get_route_to_next(curr_coords, hotel_coords)
                    if route_info:
                        curr_item["route_to_next"] = route_info

    return trip_data

