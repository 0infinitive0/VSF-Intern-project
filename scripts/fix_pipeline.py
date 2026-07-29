import re

with open('src/airflow/dags/data_pipeline/hotel_nearby_pipeline.py', 'r', encoding='utf-8') as f:
    content = f.read()

prefix = content.split('def _batches_by_hotel(')[0]

new_suffix = '''def _batches_by_hotel(
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


def crawl_hotel_surroundings(
    hotels: Iterable[Dict[str, Any]],
    nearby_limit_per_hotel: int,
    worker_count: int = 1,
) -> List[Dict[str, Any]]:
    """Extract names from the DB nearby_attractions column instead of crawling HTML."""
    import json
    seeds = []
    for hotel in hotels:
        nearby = hotel.get("nearby_attractions")
        if not nearby:
            continue
            
        if isinstance(nearby, str):
            try:
                nearby = json.loads(nearby)
            except json.JSONDecodeError:
                continue
                
        if isinstance(nearby, list):
            count = 0
            for attr in nearby:
                if count >= nearby_limit_per_hotel:
                    break
                name = None
                if isinstance(attr, dict):
                    name = attr.get("name")
                elif isinstance(attr, str):
                    name = attr.split(" - ")[0].strip()
                    
                if name:
                    seeds.append({
                        "hotel_id": hotel["hotel_id"],
                        "hotel_name": hotel["hotel_name"],
                        "hotel_latitude": hotel["hotel_latitude"],
                        "hotel_longitude": hotel["hotel_longitude"],
                        "name": name,
                        "category": _classify_nearby_name(name)
                    })
                    count += 1
    return seeds


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
'''

with open('src/airflow/dags/data_pipeline/hotel_nearby_pipeline.py', 'w', encoding='utf-8') as f:
    f.write(prefix + new_suffix)
