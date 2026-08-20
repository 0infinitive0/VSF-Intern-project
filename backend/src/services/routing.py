import math
import logging
import requests
from typing import Optional, Dict, Any, Tuple
from functools import lru_cache

from src.api.streaming import emit_phase
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

def encode_polyline(coordinates: list[Tuple[float, float]]) -> str:
    """Encode a list of (lat, lon) coordinates into a polyline string (precision 5)."""
    def encode_number(num):
        num = int(round(num * 1e5))
        num = ~(num << 1) if num < 0 else (num << 1)
        res = ""
        while num >= 0x20:
            res += chr((0x20 | (num & 0x1f)) + 63)
            num >>= 5
        res += chr(num + 63)
        return res

    result = []
    prev_lat = 0
    prev_lon = 0
    for lat, lon in coordinates:
        result.append(encode_number(lat - prev_lat))
        result.append(encode_number(lon - prev_lon))
        prev_lat = lat
        prev_lon = lon
    return "".join(result)

class MapboxDirectionsClient:
    """Client for fetching route data from Mapbox Directions API v5."""
    
    BASE_URL = "https://api.mapbox.com/directions/v5/mapbox"
    TIMEOUT_SECONDS = 10
    
    @staticmethod
    def get_route_info_batch(
        coords_list: list[Tuple[float, float]],
        profile: str
    ) -> Optional[list[Dict[str, Any]]]:
        """
        Fetch batch route information using Mapbox API.
        Returns a list of dictionaries corresponding to each leg between consecutive coordinates.
        """
        settings = get_settings()
        token = settings.mapbox_access_token
        
        if not token:
            if not getattr(MapboxDirectionsClient, "_warned_missing_token", False):
                logger.warning("MAPBOX_ACCESS_TOKEN is not set. Routing will be skipped and return None.")
                MapboxDirectionsClient._warned_missing_token = True
            return None

        if len(coords_list) < 2:
            return []

        # Mapbox API limit is 25 coordinates per request. 
        if len(coords_list) > 25:
            logger.warning(f"Mapbox API limit is 25 coordinates, got {len(coords_list)}. Truncating.")
            coords_list = coords_list[:25]

        coords_str = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
        url = f"{MapboxDirectionsClient.BASE_URL}/{profile}/{coords_str}"
        
        params = {
            "overview": "false",
            "steps": "true",
            "geometries": "geojson",
            "access_token": token
        }
        
        try:
            response = requests.get(url, params=params, timeout=MapboxDirectionsClient.TIMEOUT_SECONDS)
            
            if response.status_code == 401:
                logger.error("Mapbox API returned 401 Unauthorized. Check MAPBOX_ACCESS_TOKEN.")
                return None
            elif response.status_code == 422:
                logger.info(f"Mapbox API returned 422 Unprocessable Entity. Bad coordinates: {coords_str}")
                return None
            elif response.status_code == 429:
                logger.warning("Mapbox API returned 429 Too Many Requests. Rate limit exceeded.")
                return None
                
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == "Ok" and "routes" in data and len(data["routes"]) > 0:
                legs = data["routes"][0].get("legs", [])
                results = []
                for leg in legs:
                    distance_meters = leg.get("distance", 0.0)
                    duration_seconds = leg.get("duration", 0.0)
                    
                    coords = []
                    for step in leg.get("steps", []):
                        geom = step.get("geometry", {})
                        if geom.get("type") == "LineString":
                            for pt in geom.get("coordinates", []):
                                coords.append((pt[1], pt[0]))
                    
                    deduped = []
                    for pt in coords:
                        if not deduped or deduped[-1] != pt:
                            deduped.append(pt)
                            
                    polyline = encode_polyline(deduped) if deduped else ""
                    
                    results.append({
                        "distance_km": round(distance_meters / 1000.0, 2),
                        "duration_mins": round(duration_seconds / 60.0, 1),
                        "polyline": polyline,
                        "profile": profile
                    })
                return results
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

    hotel_coords_raw = None
    hotel = trip_data.get("hotel")
    if isinstance(hotel, dict):
        hotel_coords_raw = hotel.get("coordinates")
    
    parsed_hotel_coords = parse_coordinates(hotel_coords_raw) if hotel_coords_raw else None

    # Group items by day_number
    by_day: Dict[int, list] = {}
    for item in items:
        if isinstance(item, dict):
            day = item.get("day_number", 1)
            by_day.setdefault(day, []).append(item)

    # Emitted once with the honest scope of work (days × items) — no fabricated
    # leg counts: which legs actually resolve depends on per-item coordinates,
    # only known while looping below.
    if by_day:
        emit_phase("routing_legs", days=len(by_day))

    for day, day_items in by_day.items():
        # Sort items by order_index if present
        day_items.sort(key=lambda x: x.get("order_index", 0))
        
        # Build the sequence of coordinates for the day
        day_sequence = []
        # stores tuple: (item_dict, field_to_update, origin_coords, dest_coords, leg_index) --
        # leg_index is this entry's position among the legs Mapbox will return for
        # day_sequence (leg i connects day_sequence[i] and day_sequence[i+1]), tracked
        # explicitly rather than assumed from item_mapping's own list position. An item
        # with no parseable coordinates contributes NEITHER a day_sequence point NOR an
        # item_mapping entry -- it's a genuine gap, left for the frontend's straight-line
        # fallback -- but the coordinate immediately after such a gap must still be
        # RE-SEEDED into day_sequence (it's not already the last point there), which
        # inserts an extra "bridging" leg with no item of its own. Relying on
        # enumerate(item_mapping) to index into the returned legs silently drifted by
        # exactly one leg per gap once that bridging leg existed, splicing each
        # following item's route onto the wrong pair of points.
        item_mapping = []

        if parsed_hotel_coords and len(day_items) > 0:
            first_item = day_items[0]
            first_coords = parse_coordinates(first_item.get("coordinates"))
            if first_coords:
                day_sequence.append(parsed_hotel_coords)
                day_sequence.append(first_coords)
                item_mapping.append((first_item, "route_from_hotel", parsed_hotel_coords, first_coords, len(day_sequence) - 2))

        for i in range(len(day_items)):
            curr_item = day_items[i]
            curr_coords = parse_coordinates(curr_item.get("coordinates"))

            if i < len(day_items) - 1:
                next_item = day_items[i + 1]
                next_coords = parse_coordinates(next_item.get("coordinates"))
                if curr_coords and next_coords:
                    if not day_sequence or day_sequence[-1] != curr_coords:
                        day_sequence.append(curr_coords)
                    day_sequence.append(next_coords)
                    item_mapping.append((curr_item, "route_to_next", curr_coords, next_coords, len(day_sequence) - 2))
            else:
                # Last item -> back to hotel
                if curr_coords and parsed_hotel_coords:
                    if not day_sequence or day_sequence[-1] != curr_coords:
                        day_sequence.append(curr_coords)
                    day_sequence.append(parsed_hotel_coords)
                    item_mapping.append((curr_item, "route_to_next", curr_coords, parsed_hotel_coords, len(day_sequence) - 2))

        if not day_sequence or not item_mapping:
            continue

        # NOTE: day_sequence can now contain a "bridging" leg with no item_mapping entry
        # (the re-seed above, right after a gap) -- leg indexes are no longer simply
        # 1:1 with item_mapping's own order, which is exactly why each entry carries its
        # real leg_index instead of relying on position.

        driving_legs = MapboxDirectionsClient.get_route_info_batch(day_sequence, "driving-traffic")

        # Check if any leg requires walking
        needs_walking = False
        for (item, field, origin, dest, _leg_index) in item_mapping:
            if origin != dest and _haversine_km(origin, dest) < WALKING_THRESHOLD_KM:
                needs_walking = True
                break

        walking_legs = None
        if needs_walking:
            walking_legs = MapboxDirectionsClient.get_route_info_batch(day_sequence, "walking")

        # Assign back to items
        for (item, field, origin, dest, leg_index) in item_mapping:
            if origin == dest:
                item[field] = {
                    "distance_km": 0.0,
                    "duration_mins": 0.0,
                    "polyline": "",
                    "profile": "walking"
                }
                continue

            dist_km = _haversine_km(origin, dest)
            use_walking = dist_km < WALKING_THRESHOLD_KM

            # Select appropriate leg data
            leg_data = None
            if use_walking and walking_legs and leg_index < len(walking_legs):
                leg_data = walking_legs[leg_index]
            elif driving_legs and leg_index < len(driving_legs):
                leg_data = driving_legs[leg_index]

            if leg_data:
                item[field] = leg_data

    return trip_data

