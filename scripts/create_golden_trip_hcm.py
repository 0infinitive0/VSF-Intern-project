import os
import sys
import json
import dotenv

# Ensure project root is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

sys.stdout.reconfigure(encoding='utf-8')
dotenv.load_dotenv()

from supabase import create_client
from src.services.supabase_search import search_attractions, search_hotels_with_rooms
from src.services.itinerary_reuse import ItineraryReuseQuery, build_reuse_fingerprint
from src.services.itinerary_store import ItineraryStore
from src.services.trip_scheduler import (
    PlanningPolicy, PlaceCandidate, DayTheme, build_itinerary_with_hotel_reselection, detect_covered_hotel_meals
)

def main():
    supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))
    hcm_id = '6f860287-189e-46db-81f6-cd3c7ee5f1f7'

    # Get real hotel options
    hotel_rows = supabase.table('hotels').select('id, destination_id, name, star_rating, description, coordinates, amenities, amenity_groups').eq('destination_id', hcm_id).limit(10).execute().data
    hotel_candidates = []
    hotel_data_map = {}
    for h in hotel_rows:
        if h.get('coordinates'):
            covered = detect_covered_hotel_meals(h.get('amenities'), h.get('amenity_groups'))
            cand = PlaceCandidate.from_mapping({**h, 'category': 'Hotel', 'covered_meals': covered})
            if cand.coordinate_pair:
                hotel_candidates.append(cand)
                hotel_data_map[cand.id] = {
                    'id': cand.id,
                    'destination_id': hcm_id,
                    'name': cand.name,
                    'star_rating': h.get('star_rating'),
                    'description': h.get('description') or 'Khách sạn trung tâm TP. Hồ Chí Minh',
                    'coordinates': h.get('coordinates'),
                    'matched_rooms': ['Phòng Superior', 'Phòng Deluxe'],
                    'covered_meals': sorted(covered)
                }

    print(f'Valid hotel candidates: {len(hotel_candidates)}')

    # Themes for 3-day HCM Golden Trip
    day_themes = [
        DayTheme(day_number=1, title='Dấu Ấn Lịch Sử & Trung Tâm Sài Gòn (Quận 1)', query='dinh độc lập nhà thờ đức bà bưu điện trung tâm quận 1'),
        DayTheme(day_number=2, title='Văn Hóa & Chợ Lớn Di Sản (Quận 5)', query='chùa bà thiên hậu chợ bình tây chợ lớn bảo tàng mỹ thuật'),
        DayTheme(day_number=3, title='Sài Gòn Hiện Đại & Bến Cảng Sông Sài Gòn', query='bến cảng nhà rồng landmark 81 bus đường sông sài gòn chợ bến thành')
    ]

    # Search candidates per theme
    themed_candidates = {}
    for theme in day_themes:
        compact = search_attractions(query=f'{theme.query} TP HCM', match_count=20, filter_destination_id=hcm_id) or []
        ids = [c['id'] for c in compact if c.get('id')]
        hydrated = supabase.table('attractions').select('id,destination_id,name,description,category,is_tour,estimated_duration_minutes,opening_time,closing_time,rating,coordinates').in_('id', ids).execute().data or []
        cands = [PlaceCandidate.from_mapping(r) for r in hydrated if r.get('coordinates')]
        themed_candidates[theme.day_number] = cands

    # Search food / cafes
    food_compact = search_attractions(query='quán ăn nhà hàng cơm tấm phở bánh mì ngon Sài Gòn TP HCM', match_count=25, filter_destination_id=hcm_id) or []
    food_ids = [c['id'] for c in food_compact if c.get('id')]
    food_hydrated = supabase.table('attractions').select('id,destination_id,name,description,category,is_tour,estimated_duration_minutes,opening_time,closing_time,rating,coordinates').in_('id', food_ids).execute().data or []
    food_cands = [PlaceCandidate.from_mapping(r) for r in food_hydrated if r.get('coordinates')]

    cafe_compact = search_attractions(query='cà phê trà sữa view đẹp Sài Gòn TP HCM', match_count=25, filter_destination_id=hcm_id) or []
    cafe_ids = [c['id'] for c in cafe_compact if c.get('id')]
    cafe_hydrated = supabase.table('attractions').select('id,destination_id,name,description,category,is_tour,estimated_duration_minutes,opening_time,closing_time,rating,coordinates').in_('id', cafe_ids).execute().data or []
    cafe_cands = [PlaceCandidate.from_mapping(r) for r in cafe_hydrated if r.get('coordinates')]

    selected_hotel, schedule = build_itinerary_with_hotel_reselection(
        hotels=hotel_candidates,
        themes=day_themes,
        themed_candidates=themed_candidates,
        restaurants=food_cands,
        cafes=cafe_cands,
        breakfasts=food_cands,
        dinners=food_cands,
        child_focused=False
    )

    print(f'Selected Hotel: {selected_hotel.name} ({selected_hotel.id})')
    print(f'Generated Schedule items count: {len(schedule.items)}')

    # Convert schedule to serializable dicts grouped by day
    days_dict = {}
    for item in schedule.items:
        d_num = item.day_number
        if d_num not in days_dict:
            theme_obj = next((t for t in day_themes if t.day_number == d_num), None)
            theme_title = theme_obj.title if theme_obj else f'Ngày {d_num}'
            days_dict[d_num] = {
                'day_number': d_num,
                'theme_title': theme_title,
                'items': []
            }
        days_dict[d_num]['items'].append(item.to_mapping() if hasattr(item, 'to_mapping') else item.__dict__)

    scheduled_days = [days_dict[k] for k in sorted(days_dict.keys())]

    # Store finalized itinerary in Supabase
    store = ItineraryStore.from_default()
    reuse_query = ItineraryReuseQuery(
        destination_id=hcm_id,
        destination_name='Hồ Chí Minh',
        duration_days=3,
        number_of_adults=1,
        number_of_children=0,
        preferences=('lịch sử', 'văn hóa', 'ẩm thực'),
        child_focused=False
    )

    itinerary_id = store.store_finalized_itinerary(
        query=reuse_query,
        hotel_id=selected_hotel.id,
        day_themes=day_themes,
        scheduled_days=scheduled_days,
        summary='Lịch trình chuẩn 3 ngày 2 đêm khám phá Sài Gòn - TP.HCM dành cho khách đi 1 mình (Solo Golden Trip)'
    )

    print('SUCCESS! Stored Golden Trip ID:', itinerary_id)

    # Save to golden_trip_plan_hcm_3d.json as well for local inspection & reference
    golden_payload = {
        'itinerary_id': itinerary_id,
        'destination_id': hcm_id,
        'destination_name': 'Hồ Chí Minh',
        'duration_days': 3,
        'adults': 1,
        'children': 0,
        'preferences': ['lịch sử', 'văn hóa', 'ẩm thực'],
        'hotel': hotel_data_map.get(selected_hotel.id, {'id': selected_hotel.id, 'name': selected_hotel.name}),
        'day_themes': [{'day_number': t.day_number, 'title': t.title, 'query': t.query} for t in day_themes],
    }
    os.makedirs('data', exist_ok=True)
    output_path = os.path.join('data', 'golden_trip_plan_hcm_3d.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(golden_payload, f, ensure_ascii=False, indent=2)
    print(f'Saved {output_path}')

if __name__ == '__main__':
    main()
