import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open('current_trip_plan.json', 'r', encoding='utf-8') as f:
    trip = json.load(f)

with open('api_locations.json', 'r', encoding='utf-8') as f:
    locs = json.load(f)

loc_map = {item['id']: item for item in locs.get('data', [])}
print('Total locations in api_locations.json:', len(loc_map))

day2_items = [i for i in trip.get('itinerary_items', []) if i.get('day_number') == 2]

for item in day2_items:
    ref_id = item.get('reference_id')
    ref_type = item.get('reference_type')
    loc = loc_map.get(ref_id)
    print(f"Day 2 Step #{item.get('order_index')}: {item.get('activity')} | ref_id={ref_id} ({ref_type}) -> Found: {loc is not None}")
    if loc:
        print(f"   coords: {loc.get('lat')}, {loc.get('lng')}")
    else:
        print(f"   MISSING IN API LOCATIONS MAP!")
