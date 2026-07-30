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
from src.services.itinerary_reuse import (
    ItineraryReuseQuery,
    ItineraryTemplate,
    build_reuse_fingerprint,
    classify_reuse_candidate,
    validate_template_bundle
)
from src.services.itinerary_store import ItineraryStore, LoadedItineraryBundle
from src.services.trip_scheduler import (
    PlanningPolicy,
    PlaceCandidate,
    DayTheme,
    build_itinerary_with_hotel_reselection,
    detect_covered_hotel_meals,
    fits_opening_hours,
    haversine_distance_km
)

HCM_ID = '6f860287-189e-46db-81f6-cd3c7ee5f1f7'

def get_supabase_client():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
    return create_client(url, key)

# =====================================================================
# PART A: TRIP CLONING & LINEAGE TEST
# =====================================================================
def test_trip_cloning():
    print("\n" + "="*70)
    print("PART A: TESTING TRIP CLONING & LINEAGE TRACKING")
    print("="*70)
    
    supabase = get_supabase_client()
    store = ItineraryStore.from_default()

    finalized_rows = (
        supabase.table('itineraries')
        .select('id,hotel_id,reuse_count')
        .eq('destination_id', HCM_ID)
        .eq('duration_days', 3)
        .eq('status', 'Finalized')
        .limit(1)
        .execute()
        .data
        or []
    )
    assert finalized_rows and finalized_rows[0].get('hotel_id'), (
        "No finalized 3-day itinerary with a hotel found for the cloning test!"
    )
    selected_hotel_id = str(finalized_rows[0]['hotel_id'])

    # 1. Search for existing Finalized Golden Trips in HCM
    query = ItineraryReuseQuery(
        destination_id=HCM_ID,
        destination_name='Hồ Chí Minh',
        duration_days=3,
        number_of_adults=1,
        number_of_children=0,
        preferences=('lịch sử', 'văn hóa', 'ẩm thực'),
        child_focused=False,
        hotel_id=selected_hotel_id,
    )

    print("Searching Tier 1 Reusable Templates...")
    candidates = store.search_reusable_itineraries(query, threshold=0.70, match_count=5)
    print(f"Found {len(candidates)} reusable template candidates.")

    if not candidates:
        rows = (
            supabase.table('itineraries')
            .select('*')
            .eq('destination_id', HCM_ID)
            .eq('duration_days', 3)
            .eq('hotel_id', selected_hotel_id)
            .eq('status', 'Finalized')
            .execute()
            .data
            or []
        )
        print(f"Direct DB lookup found {len(rows)} finalized itineraries.")
        assert len(rows) > 0, "No finalized itineraries found in DB for cloning test!"
        golden_id = rows[0]['id']
        golden_reuse_count = rows[0].get('reuse_count', 0)
    else:
        golden_candidate = candidates[0]
        golden_id = golden_candidate.id
        golden_reuse_count = golden_candidate.reuse_count
        print(f"Selected Golden Template ID: {golden_id} (Similarity: {golden_candidate.similarity:.4f}, Prior Reuse Count: {golden_reuse_count})")

    # Load complete bundle of the parent Golden Trip
    bundle = store.load_itinerary_bundle(golden_id)
    assert bundle is not None, f"Failed to load itinerary bundle for ID {golden_id}"
    print(f"Loaded parent bundle with {len(bundle.template.items)} items and hotel '{bundle.hotel.get('name')}'")

    # 2. Clone the Golden Trip for a new user/session (Cloning Flow)
    cloned_itinerary_id = str(uuid.uuid4())
    now_iso = datetime.now().isoformat()

    parent_root_id = bundle.template.reuse_root_id or golden_id
    cloned_itinerary_record = {
        "id": cloned_itinerary_id,
        "session_id": None,
        "duration_days": bundle.template.duration_days,
        "number_of_adults": 2,  # Adapted for 2 adults
        "number_of_children": 0,
        "budget": None,
        "preferences": ["Hồ Chí Minh", "lịch sử", "văn hóa", "ẩm thực", "cà phê"],
        "day_themes": [dict(t) for t in bundle.template.day_themes],
        "destination_id": bundle.template.destination_id,
        "hotel_id": bundle.template.hotel_id,
        "parent_itinerary_id": golden_id,  # LINK TO PARENT
        "reuse_root_id": parent_root_id,     # LINEAGE ROOT
        "status": "Draft",
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    cloned_items = []
    for item in bundle.template.items:
        cloned_items.append({
            "id": str(uuid.uuid4()),
            "itinerary_id": cloned_itinerary_id,
            "day_number": item.get("day_number"),
            "order_index": item.get("order_index"),
            "start_time": item.get("start_time"),
            "end_time": item.get("end_time"),
            "reference_type": item.get("reference_type"),
            "reference_id": item.get("reference_id"),
            "estimated_cost": item.get("estimated_cost"),
            "item_kind": item.get("item_kind") or item.get("kind"),
            "created_at": now_iso,
            "updated_at": now_iso,
        })

    cloned_trip_data = {
        "hotel": bundle.hotel,
        "itineraries": [cloned_itinerary_record],
        "itinerary_items": cloned_items,
        "adjustments": ["Cloned from parent Golden Trip ID: " + golden_id]
    }

    # 3. Persist and finalize cloned trip
    print(f"Persisting cloned trip (ID: {cloned_itinerary_id})...")
    store.persist_itinerary_bundle(cloned_trip_data)

    clone_reuse_query = ItineraryReuseQuery(
        destination_id=HCM_ID,
        destination_name='Hồ Chí Minh',
        duration_days=bundle.template.duration_days,
        number_of_adults=2,
        number_of_children=0,
        preferences=('lịch sử', 'văn hóa', 'ẩm thực', 'cà phê'),
        child_focused=False,
        hotel_id=str(bundle.template.hotel_id),
    )

    print("Finalizing cloned trip to trigger lineage reuse count update...")
    finalize_res = store.finalize_trip_data(cloned_trip_data, clone_reuse_query)

    # 4. Verify DB State & Lineage
    db_cloned = supabase.table('itineraries').select('*').eq('id', cloned_itinerary_id).execute().data[0]
    db_parent = supabase.table('itineraries').select('*').eq('id', golden_id).execute().data[0]

    print("\n--- CLONING VERIFICATION RESULTS ---")
    print(f"✅ Cloned Itinerary Status: {db_cloned['status']} (Expected: Finalized)")
    print(f"✅ Cloned Parent ID: {db_cloned['parent_itinerary_id']} (Matches Golden ID: {golden_id})")
    print(f"✅ Cloned Reuse Root ID: {db_cloned['reuse_root_id']} (Matches Root ID: {parent_root_id})")
    print(f"✅ Parent Previous Reuse Count: {golden_reuse_count} -> Updated Reuse Count: {db_parent['reuse_count']}")

    assert db_cloned['status'] == 'Finalized'
    assert db_cloned['parent_itinerary_id'] == golden_id
    assert db_cloned['reuse_root_id'] == parent_root_id

    cloning_output = {
        "status": "success",
        "parent_golden_id": golden_id,
        "parent_previous_reuse_count": golden_reuse_count,
        "parent_new_reuse_count": db_parent['reuse_count'],
        "cloned_itinerary_id": cloned_itinerary_id,
        "cloned_parent_link": db_cloned['parent_itinerary_id'],
        "cloned_items_count": len(cloned_items),
        "summary": finalize_res.get("summary")
    }
    os.makedirs("data", exist_ok=True)
    cloning_path = os.path.join("data", "test_trip_cloning_result.json")
    with open(cloning_path, "w", encoding="utf-8") as f:
        json.dump(cloning_output, f, ensure_ascii=False, indent=2)
    print(f"Saved {cloning_path}")
    return cloning_output

# =====================================================================
# PART B: RECOMMENDATIONS ENGINE TEST
# =====================================================================
def test_recommendations_engine():
    print("\n" + "="*70)
    print("PART B: TESTING RECOMMENDATIONS ENGINE & SEMANTIC SEARCH")
    print("="*70)
    
    profiles = [
        {
            "name": "Profile A: Culture & Heritage",
            "query": "bảo tàng lịch sử di sản văn hóa kiến trúc cổ Sài Gòn"
        },
        {
            "name": "Profile B: Foodie & Local Cuisine",
            "query": "nhà hàng quán ăn ngon đặc sản cơm tấm phở bánh mì Sài Gòn"
        },
        {
            "name": "Profile C: Relaxed Coffee & Nightlife",
            "query": "cà phê ngắm cảnh thư giãn giải trí đêm Sài Gòn"
        }
    ]

    rec_results = []

    for prof in profiles:
        print(f"\nEvaluating Recommendations for: {prof['name']}")
        print(f"Query: '{prof['query']}'")
        
        # Fast direct search without Ollama network wait
        search_res = search_attractions(
            query=prof['query'],
            match_count=10,
            filter_destination_id=HCM_ID,
            use_llm_filter=False
        ) or []
        print(f"Found {len(search_res)} attraction recommendations.")
        
        recs = []
        for rank, item in enumerate(search_res[:5], 1):
            name = item.get("name")
            score = float(item.get("similarity") or 0.0)
            category = item.get("category") or "General"
            recs.append({
                "rank": rank,
                "name": name,
                "score": score,
                "category": category
            })
            print(f"  {rank}. {name} (Category: {category}, Similarity: {score:.4f})")
        
        rec_results.append({
            "profile": prof['name'],
            "query": prof['query'],
            "recommendations": recs
        })

    # Test Hotel Recommendations with Room Matching
    print("\nEvaluating Hotel Recommendations with Room & Amenity Filtering...")
    hotel_search = search_hotels_with_rooms(
        query="Khách sạn trung tâm Sài Gòn Quận 1",
        match_count=5,
        filter_destination_id=HCM_ID,
        use_llm_filter=False
    ) or []
    print(f"Found {len(hotel_search)} hotel recommendations with room matching.")
    
    hotel_recs = []
    for idx, h in enumerate(hotel_search[:3], 1):
        h_name = h.get("name")
        star = h.get("star_rating")
        score = float(h.get("similarity") or 0.0)
        rooms = h.get("matched_room_names") or []
        hotel_recs.append({
            "rank": idx,
            "name": h_name,
            "star_rating": star,
            "similarity": score,
            "matched_rooms": rooms[:2]
        })
        print(f"  {idx}. {h_name} ({star}★, Score: {score:.4f}) - Rooms: {rooms[:2]}")

    rec_payload = {
        "status": "success",
        "attraction_recommendations": rec_results,
        "hotel_recommendations": hotel_recs
    }

    os.makedirs("data", exist_ok=True)
    rec_path = os.path.join("data", "test_recommendations_result.json")
    with open(rec_path, "w", encoding="utf-8") as f:
        json.dump(rec_payload, f, ensure_ascii=False, indent=2)
    print(f"Saved {rec_path}")
    return rec_payload

if __name__ == '__main__':
    test_trip_cloning()
    test_recommendations_engine()
