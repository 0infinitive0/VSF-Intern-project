import os
import sys
import json
import uuid
import dotenv
from datetime import datetime

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.stdout.reconfigure(encoding='utf-8')
dotenv.load_dotenv()

from supabase import create_client
from src.services.supabase_search import search_attractions, search_hotels_with_rooms
from src.services.itinerary_reuse import ItineraryReuseQuery, build_reuse_fingerprint
from src.services.itinerary_store import ItineraryStore
from src.services.trip_scheduler import (
    PlanningPolicy, PlaceCandidate, DayTheme, ScheduledItem, build_itinerary_with_hotel_reselection, detect_covered_hotel_meals, serialize_day_themes
)

HCM_ID = '6f860287-189e-46db-81f6-cd3c7ee5f1f7'

def get_supabase_client():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
    return create_client(url, key)

def fetch_hotel_candidates(supabase, destination_id: str, limit: int = 15):
    rows = supabase.table('hotels').select(
        'id, destination_id, name, star_rating, description, coordinates, amenities, amenity_groups'
    ).eq('destination_id', destination_id).limit(limit).execute().data or []
    candidates = []
    data_map = {}
    for h in rows:
        if h.get('coordinates'):
            covered = detect_covered_hotel_meals(h.get('amenities'), h.get('amenity_groups'))
            cand = PlaceCandidate.from_mapping({**h, 'category': 'Hotel', 'covered_meals': covered})
            if cand.coordinate_pair:
                candidates.append(cand)
                data_map[cand.id] = {
                    'id': cand.id,
                    'destination_id': destination_id,
                    'name': cand.name,
                    'star_rating': h.get('star_rating'),
                    'description': h.get('description') or 'Khách sạn trung tâm TP. Hồ Chí Minh',
                    'coordinates': h.get('coordinates'),
                    'matched_rooms': ['Phòng Superior', 'Phòng Deluxe'],
                    'covered_meals': sorted(covered)
                }
    return candidates, data_map

def fetch_attraction_pool(supabase, destination_id: str, query: str, match_count: int = 25):
    compact = search_attractions(query=query, match_count=match_count, filter_destination_id=destination_id) or []
    ids = [c['id'] for c in compact if c.get('id')]
    if not ids:
        return []
    rows = supabase.table('attractions').select(
        'id,destination_id,name,description,category,is_tour,estimated_duration_minutes,opening_time,closing_time,rating,coordinates'
    ).in_('id', ids).execute().data or []
    return [PlaceCandidate.from_mapping(r) for r in rows if r.get('coordinates')]

def build_trip_data(destination_name: str, destination_id: str, day_themes: list[DayTheme], hotel_candidates: list[PlaceCandidate], hotel_data_map: dict, preferences: list[str], adults: int = 1):
    supabase = get_supabase_client()
    themed_candidates = {}
    for theme in day_themes:
        themed_candidates[theme.day_number] = fetch_attraction_pool(
            supabase, destination_id, f"{theme.query} TP HCM Sài Gòn", match_count=20
        )
    
    food_cands = fetch_attraction_pool(
        supabase, destination_id, "quán ăn nhà hàng cơm tấm phở bánh mì ngon Sài Gòn TP HCM", match_count=25
    )
    cafe_cands = fetch_attraction_pool(
        supabase, destination_id, "cà phê trà sữa view đẹp thư giãn Sài Gòn TP HCM", match_count=25
    )

    selected_hotel, schedule = build_itinerary_with_hotel_reselection(
        hotel_candidates,
        day_themes,
        themed_candidates,
        food_cands,
        cafe_cands,
        breakfasts=food_cands,
        dinners=food_cands,
        child_focused=False
    )

    now_iso = datetime.now().isoformat()
    itinerary_id = str(uuid.uuid4())
    serialized_themes = serialize_day_themes(day_themes)
    
    hotel_data = hotel_data_map.get(selected_hotel.id, {
        'id': selected_hotel.id,
        'destination_id': destination_id,
        'name': selected_hotel.name
    })

    itinerary_record = {
        "id": itinerary_id,
        "session_id": None,
        "duration_days": len(day_themes),
        "number_of_adults": adults,
        "number_of_children": 0,
        "budget": None,
        "preferences": [destination_name, *preferences],
        "day_themes": serialized_themes,
        "destination_id": destination_id,
        "hotel_id": selected_hotel.id,
        "parent_itinerary_id": None,
        "status": "Draft",
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    serialized_items = []
    for item in schedule.items:
        serialized_items.append({
            "id": str(uuid.uuid4()),
            "itinerary_id": itinerary_id,
            "day_number": item.day_number,
            "order_index": item.order_index,
            "start_time": item.start_time,
            "end_time": item.end_time,
            "reference_type": item.reference_type,
            "reference_id": item.reference_id,
            "estimated_cost": None,
            "created_at": now_iso,
            "updated_at": now_iso,
            "activity": item.activity,
            "kind": item.kind,
            "place_name": item.place_name,
            "coordinates": item.coordinates,
            "duration_minutes": item.duration_minutes,
            "category": item.category,
            "opening_time": item.opening_time,
            "closing_time": item.closing_time,
            "is_playground": item.is_playground,
        })

    days_dict = {}
    for item in serialized_items:
        d_num = item["day_number"]
        if d_num not in days_dict:
            theme_obj = next((t for t in day_themes if t.day_number == d_num), None)
            theme_title = theme_obj.title if theme_obj else f'Ngày {d_num}'
            days_dict[d_num] = {
                'day_number': d_num,
                'theme_title': theme_title,
                'items': []
            }
        days_dict[d_num]['items'].append(item)

    scheduled_days = [days_dict[k] for k in sorted(days_dict.keys())]

    trip_data = {
        "hotel": hotel_data,
        "itineraries": [itinerary_record],
        "itinerary_items": serialized_items,
        "scheduled_days": scheduled_days,
        "adjustments": schedule.adjustments,
    }
    return trip_data, selected_hotel

def save_to_supabase_tables(supabase, trip_data):
    itinerary_record = trip_data["itineraries"][0]
    supabase.table("itineraries").upsert(itinerary_record).execute()
    
    # Filter DB items to match exact PostgreSQL table columns
    db_items = []
    for item in trip_data["itinerary_items"]:
        db_items.append({
            "id": item["id"],
            "itinerary_id": item["itinerary_id"],
            "day_number": item["day_number"],
            "order_index": item["order_index"],
            "start_time": item["start_time"],
            "end_time": item["end_time"],
            "reference_type": item["reference_type"],
            "reference_id": item["reference_id"],
            "estimated_cost": item.get("estimated_cost"),
            "item_kind": item.get("item_kind") or item.get("kind"),
        })
    if db_items:
        supabase.table("itinerary_items").upsert(db_items).execute()

def create_golden_trip_3d():
    print("=== Step 1: Generating 3-Day Golden Trip for TP HCM (Solo) ===")
    supabase = get_supabase_client()
    hotels, hotel_map = fetch_hotel_candidates(supabase, HCM_ID, limit=15)
    
    day_themes = [
        DayTheme(day_number=1, title='Dấu Ấn Lịch Sử & Trung Tâm Sài Gòn (Quận 1)', query='dinh độc lập nhà thờ đức bà bưu điện trung tâm quận 1'),
        DayTheme(day_number=2, title='Văn Hóa & Chợ Lớn Di Sản (Quận 5)', query='chùa bà thiên hậu chợ bình tây chợ lớn bảo tàng mỹ thuật'),
        DayTheme(day_number=3, title='Sài Gòn Hiện Đại & Bến Cảng Sông Sài Gòn', query='bến cảng nhà rồng landmark 81 bus đường sông sài gòn chợ bến thành')
    ]

    preferences = ['lịch sử', 'văn hóa', 'ẩm thực']
    trip_data, selected_hotel = build_trip_data("Hồ Chí Minh", HCM_ID, day_themes, hotels, hotel_map, preferences, adults=1)

    # Save to Supabase tables
    save_to_supabase_tables(supabase, trip_data)

    store = ItineraryStore.from_default()
    reuse_query = ItineraryReuseQuery(
        destination_id=HCM_ID,
        destination_name='Hồ Chí Minh',
        duration_days=3,
        number_of_adults=1,
        number_of_children=0,
        preferences=tuple(preferences),
        child_focused=False
    )

    result = store.finalize_trip_data(trip_data, reuse_query)
    itinerary_id = trip_data["itineraries"][0]["id"]
    trip_data["itineraries"][0]["status"] = "Finalized"
    trip_data["itineraries"][0]["summary"] = result.get("summary")

    os.makedirs('data', exist_ok=True)
    golden_path = os.path.join('data', 'golden_trip_plan_hcm_3d.json')
    with open(golden_path, 'w', encoding='utf-8') as f:
        json.dump(trip_data, f, ensure_ascii=False, indent=2)

    print(f"✅ SUCCESS! 3-Day Golden Trip (ID: {itinerary_id}) persisted and finalized in database & saved to {golden_path}!")
    return itinerary_id

def test_user_flow_5d_historical():
    print("\n=== Step 2: Testing User Flow for 5-Day Historical TP HCM Trip (Solo) ===")
    supabase = get_supabase_client()
    hotels, hotel_map = fetch_hotel_candidates(supabase, HCM_ID, limit=15)

    day_themes = [
        DayTheme(day_number=1, title='Dấu Ấn Kháng Chiến & Di Tích Lịch Sử Quốc Gia', query='dinh độc lập bảo tàng chứng tích chiến tranh lịch sử khang chien'),
        DayTheme(day_number=2, title='Kiến Trúc Pháp Cổ & Trung Tâm Sài Gòn Xưa', query='nhà thờ đức bà bưu điện trung tâm sài gòn nhà hát thành phố trụ sở ubnd'),
        DayTheme(day_number=3, title='Di Sản Văn Hóa & Tín Ngưỡng Chợ Lớn (Quận 5)', query='chùa bà thiên hậu hội quán minh hương chợ bình tây di tích lịch sử quận 5'),
        DayTheme(day_number=4, title='Hệ Thống Bảo Tàng Mỹ Thuật & Lịch Sử Nam Bộ', query='bảo tàng mỹ thuật bảo tàng lịch sử việt nam bảo tàng thành phố hồ chí minh'),
        DayTheme(day_number=5, title='Dấu Ấn Sông Sài Gòn & Chợ Di Sản Bến Thành', query='bến cảng nhà rồng bảo tàng hồ chí minh chợ bến thành bus đường sông')
    ]

    preferences = ['lịch sử', 'di sản', 'bảo tàng']
    trip_data, selected_hotel = build_trip_data("Hồ Chí Minh", HCM_ID, day_themes, hotels, hotel_map, preferences, adults=1)

    # Save to Supabase tables
    save_to_supabase_tables(supabase, trip_data)

    os.makedirs('data', exist_ok=True)
    historical_path = os.path.join('data', 'test_trip_plan_hcm_5d_historical.json')
    with open(historical_path, 'w', encoding='utf-8') as f:
        json.dump(trip_data, f, ensure_ascii=False, indent=2)

    total_items = len(trip_data['itinerary_items'])
    print(f"✅ SUCCESS! Generated 5-Day Historical Trip with {total_items} scheduled activities across 5 days!")
    print(f"Saved {historical_path}")

if __name__ == '__main__':
    create_golden_trip_3d()
    test_user_flow_5d_historical()
