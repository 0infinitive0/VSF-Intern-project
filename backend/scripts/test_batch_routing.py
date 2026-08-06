import asyncio
import os
import sys

# Add the parent directory to sys.path so we can import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.routing import recalculate_itinerary_routes
from src.config import get_settings
from supabase import create_client, Client

async def main():
    settings = get_settings()
    supabase: Client = create_client(settings.supabase_url, settings.supabase_service_key)

    # 1. Get an itinerary with items
    itinerary_id = "86924d7c-bced-4224-b97d-46f3504c5ea6"

    # Fetch itinerary and hotel
    it_res = supabase.table("itineraries").select("*, hotel_id").eq("id", itinerary_id).execute()
    if not it_res.data:
        print("Itinerary not found")
        return
    itinerary = it_res.data[0]

    hotel_res = supabase.table("hotels").select("*").eq("id", itinerary["hotel_id"]).execute()
    hotel = hotel_res.data[0] if hotel_res.data else None

    # Fetch itinerary items and attractions
    items_res = supabase.table("itinerary_items").select("*").eq("itinerary_id", itinerary_id).order("day_number").order("order_index").execute()
    
    trip_data = {
        "hotel": hotel,
        "itinerary_items": items_res.data
    }

    # Populate coordinates for items from attractions
    for item in trip_data["itinerary_items"]:
        if item["reference_type"] == "Attraction" and item["reference_id"]:
            att_res = supabase.table("attractions").select("coordinates").eq("id", item["reference_id"]).execute()
            if att_res.data:
                item["coordinates"] = att_res.data[0]["coordinates"]
                
    # Remove existing route_to_next so we can see the recalculation cleanly
    for item in trip_data["itinerary_items"]:
        if "route_to_next" in item:
            del item["route_to_next"]
        if "route_from_hotel" in item:
            del item["route_from_hotel"]

    print(f"Testing recalculate_itinerary_routes with {len(trip_data['itinerary_items'])} items...")
    
    updated_trip = recalculate_itinerary_routes(trip_data)
    
    print("\n--- Routing Results ---")
    for item in updated_trip["itinerary_items"]:
        print(f"Day {item['day_number']}, Order {item.get('order_index')}")
        
        if "route_from_hotel" in item:
            r = item["route_from_hotel"]
            print(f"  [From Hotel] -> {r['distance_km']}km, {r['duration_mins']}mins ({r['profile']})")
            
        if "route_to_next" in item:
            r = item["route_to_next"]
            print(f"  [To Next]    -> {r['distance_km']}km, {r['duration_mins']}mins ({r['profile']})")
            
    print("\nSuccess! Batch routing processed correctly.")

if __name__ == "__main__":
    asyncio.run(main())
