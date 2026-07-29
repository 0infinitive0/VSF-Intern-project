import os, json, sys
import dotenv
from supabase import create_client

sys.stdout.reconfigure(encoding='utf-8')
dotenv.load_dotenv()

url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_SERVICE_KEY')
supabase = create_client(url, key)

with open('current_trip_plan.json', 'r', encoding='utf-8') as f:
    trip = json.load(f)

day2_items = [i for i in trip.get('itinerary_items', []) if i.get('day_number') == 2]

print(f"=== CHECKING DAY 2 ITEMS ({len(day2_items)} items) IN SUPABASE ===")

for item in day2_items:
    ref_id = item.get('reference_id')
    ref_type = item.get('reference_type', 'Attraction').lower()
    table = 'hotels' if ref_type == 'hotel' else 'attractions'
    
    res = supabase.table(table).select('id, name, coordinates').eq('id', ref_id).execute()
    if res.data:
        rec = res.data[0]
        print(f"Step #{item.get('order_index')} [{item.get('activity')}]: Found in DB table '{table}' -> coordinates: '{rec.get('coordinates')}'")
    else:
        # Check the other table
        other_table = 'attractions' if table == 'hotels' else 'hotels'
        res2 = supabase.table(other_table).select('id, name, coordinates').eq('id', ref_id).execute()
        if res2.data:
            rec = res2.data[0]
            print(f"Step #{item.get('order_index')} [{item.get('activity')}]: Found in OTHER table '{other_table}' -> coordinates: '{rec.get('coordinates')}'")
        else:
            print(f"❌ Step #{item.get('order_index')} [{item.get('activity')}]: NOT FOUND in DB (ref_id: {ref_id})")
