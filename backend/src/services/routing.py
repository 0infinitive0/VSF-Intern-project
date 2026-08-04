import logging
import requests
from typing import Optional, Dict, Any, Tuple
from functools import lru_cache

logger = logging.getLogger(__name__)

class OSRMClient:
    """Client for fetching route data from OSRM public demo server."""
    
    BASE_URL = "http://router.project-osrm.org/route/v1/driving"
    TIMEOUT_SECONDS = 5
    
    @staticmethod
    @lru_cache(maxsize=1024)
    def get_route_info(
        origin_coords: Tuple[float, float], 
        dest_coords: Tuple[float, float]
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch route information between two coordinates.
        Coordinates should be (latitude, longitude).
        Returns a dictionary with distance_km, duration_mins, and polyline if successful.
        Returns None if the request fails or no route is found.
        """
        origin_lat, origin_lon = origin_coords
        dest_lat, dest_lon = dest_coords
        
        # OSRM expects {longitude},{latitude}
        url = f"{OSRMClient.BASE_URL}/{origin_lon},{origin_lat};{dest_lon},{dest_lat}?overview=full"
        
        try:
            response = requests.get(url, timeout=OSRMClient.TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == "Ok" and "routes" in data and len(data["routes"]) > 0:
                route = data["routes"][0]
                distance_meters = route.get("distance", 0.0)
                # OSRM demo server uses driving profile. Multiply duration by 2.5 to simulate a more realistic pace
                duration_seconds = route.get("duration", 0.0) * 2.5
                geometry = route.get("geometry", "")
                
                return {
                    "distance_km": round(distance_meters / 1000.0, 2),
                    "duration_mins": round(duration_seconds / 60.0, 1),
                    "polyline": geometry
                }
            else:
                logger.warning(f"OSRM API returned non-Ok code or no routes: {data.get('code')}")
                return None
                
        except requests.RequestException as e:
            logger.warning(f"OSRM API request failed: {e}")
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
        
    # Ignore routing if coordinates are identical
    if origin == dest:
        return {
            "distance_km": 0.0,
            "duration_mins": 0.0,
            "polyline": ""
        }
        
    return OSRMClient.get_route_info(origin, dest)

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

