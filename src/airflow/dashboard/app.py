import os
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent.parent.parent

# Appended (not inserted at index 0): site-packages must be searched first,
# or a same-named top-level dir here (e.g. the local Supabase CLI project's
# "supabase/" folder) shadows the real pip-installed "supabase" package.
# Needed so `from src.services.routing import ...` below can resolve.
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))
if Path("/project").exists() and "/project" not in sys.path:
    sys.path.append("/project")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from supabase import create_client, Client

import dotenv
dotenv.load_dotenv()

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Try to initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_ANON_KEY")
    or os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_KEY")
)

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")

@app.get("/api/locations")
def get_locations():
    if not supabase:
        return {"status": "error", "message": "Supabase client not initialized. Check your environment variables (.env file)."}
        
    try:
        locations = []
        fetched_ids = set()

        # 0. Extract reference_ids from current_trip_plan.json if present
        trip_item_ids = []
        candidate_paths = [
            BASE_DIR.parent.parent.parent / "data" / "current_trip_plan.json",
            Path("/project/data/current_trip_plan.json"),
            Path("/opt/airflow/data/current_trip_plan.json"),
            Path("data/current_trip_plan.json"),
            BASE_DIR.parent.parent.parent / "current_trip_plan.json", # fallback
            Path("/project/current_trip_plan.json"), # fallback
        ]
        for p in candidate_paths:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        trip_plan = json.load(f)
                    for item in trip_plan.get("itinerary_items", []):
                        ref_id = item.get("reference_id")
                        if ref_id:
                            trip_item_ids.append(ref_id)
                    break
                except Exception as e:
                    print(f"Error reading {p} for locations: {e}")

        # Explicitly fetch trip items from attractions first
        if trip_item_ids:
            try:
                response = supabase.table("attractions").select("id, name, category, coordinates, images").in_("id", trip_item_ids).execute()
                for row in response.data:
                    if not row.get("coordinates"):
                        continue
                    try:
                        lat, lng = row["coordinates"].split(',')
                        locations.append({
                            "id": str(row["id"]),
                            "name": row.get("name"),
                            "category": row.get("category"),
                            "lat": float(lat),
                            "lng": float(lng),
                            "images": row.get("images") or [],
                            "type": "attraction"
                        })
                        fetched_ids.add(str(row["id"]))
                    except Exception:
                        continue
            except Exception as e:
                print(f"Error fetching trip attractions: {e}")
        
        # 1. Attractions (general list)
        try:
            response = supabase.table("attractions").select("id, name, category, coordinates, images").not_.is_("coordinates", "null").execute()
            for row in response.data:
                row_id = str(row["id"])
                if row_id in fetched_ids:
                    continue
                try:
                    lat, lng = row["coordinates"].split(',')
                    locations.append({
                        "id": row_id,
                        "name": row.get("name"),
                        "category": row.get("category"),
                        "lat": float(lat),
                        "lng": float(lng),
                        "images": row.get("images") or [],
                        "type": "attraction"
                    })
                    fetched_ids.add(row_id)
                except Exception as e:
                    print(f"Error parsing attraction row: {e}")
                    continue
        except Exception as e:
            print(f"Error fetching attractions: {e}")
            
        # 2. Destinations
        try:
            response = supabase.table("destinations").select("id, name, region, coordinates").not_.is_("coordinates", "null").execute()
            for row in response.data:
                try:
                    lat, lng = row["coordinates"].split(',')
                    locations.append({
                        "id": str(row["id"]),
                        "name": row.get("name"),
                        "category": row.get("region"),
                        "lat": float(lat),
                        "lng": float(lng),
                        "images": [],
                        "type": "destination"
                    })
                except Exception as e:
                    continue
        except Exception as e:
            print(f"Error fetching destinations: {e}")
            
        # 3. Hotels (wrap in try/except in case table doesn't exist yet)
        try:
            response = supabase.table("hotels").select("id, name, star_rating, coordinates, images, source_url").not_.is_("coordinates", "null").execute()
            for row in response.data:
                try:
                    lat, lng = row["coordinates"].split(',')
                    star = row.get("star_rating")
                    locations.append({
                        "id": str(row["id"]),
                        "name": row.get("name"),
                        "category": f"{star} Star" if star else "Hotel",
                        "lat": float(lat),
                        "lng": float(lng),
                        "images": row.get("images") or [],
                        "source_urls": [row.get("source_url")] if row.get("source_url") else [],
                        "type": "hotel"
                    })
                except Exception as e:
                    continue
        except Exception as e:
            print(f"Error fetching hotels (might not exist yet): {e}")

        return {"status": "success", "data": locations}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/data/{table_name}")
def get_table_data(table_name: str, page: int = 1, page_size: int = 100, item_id: str = None):
    if not supabase:
        return {"status": "error", "message": "Supabase client not initialized."}
    if table_name not in ["attractions", "hotels", "destinations", "rooms"]:
        return {"status": "error", "message": "Invalid table."}
    
    try:
        offset = (page - 1) * page_size
        query = supabase.table(table_name).select("*", count="exact")
        if item_id:
            if table_name == "rooms":
                query = query.eq("hotel_id", item_id)
            else:
                query = query.eq("id", item_id)
        else:
            query = query.order("id", desc=False).range(offset, offset + page_size - 1)
            
        response = query.execute()
        return {
            "status": "success",
            "data": response.data,
            "count": response.count if not item_id else len(response.data),
            "page": page,
            "page_size": page_size
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/itineraries")
def get_itineraries():
    if not supabase:
        return {"status": "error", "message": "Supabase client not initialized."}
    try:
        res = (
            supabase.table("itineraries")
            .select("id, status, duration_days, number_of_adults, number_of_children, preferences, day_themes, destination_id, hotel_id, created_at, summary")
            .order("created_at", desc=True)
            .execute()
        )
        return {"status": "success", "data": res.data or []}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/trip_plan")
def get_trip_plan(itinerary_id: str = None):
    if itinerary_id and supabase:
        try:
            itin_res = supabase.table("itineraries").select("*").eq("id", itinerary_id).execute()
            if not itin_res.data:
                return {"status": "error", "message": f"Itinerary ID '{itinerary_id}' not found in database."}
            itinerary_record = itin_res.data[0]

            items_res = (
                supabase.table("itinerary_items")
                .select("*")
                .eq("itinerary_id", itinerary_id)
                .order("day_number", desc=False)
                .order("order_index", desc=False)
                .execute()
            )
            raw_items = items_res.data or []

            attraction_ids = [
                item["reference_id"]
                for item in raw_items
                if item.get("reference_id") and str(item.get("reference_type") or "").lower() != "hotel"
            ]
            attr_map = {}
            if attraction_ids:
                try:
                    att_res = supabase.table("attractions").select("id, name, coordinates, category").in_("id", attraction_ids).execute()
                    for att in (att_res.data or []):
                        attr_map[str(att["id"])] = att
                except Exception as e:
                    print(f"Error fetching attraction hydration details: {e}")

            hotel_data = {}
            if itinerary_record.get("hotel_id"):
                try:
                    hotel_res = supabase.table("hotels").select("*").eq("id", itinerary_record["hotel_id"]).execute()
                    if hotel_res.data:
                        h = hotel_res.data[0]
                        hotel_data = {
                            "id": h.get("id"),
                            "destination_id": h.get("destination_id"),
                            "name": h.get("name"),
                            "star_rating": h.get("star_rating"),
                            "description": h.get("description"),
                            "coordinates": h.get("coordinates"),
                            "matched_rooms": ["Phòng Superior", "Phòng Deluxe"],
                            "covered_meals": []
                        }
                except Exception as e:
                    print(f"Error fetching hotel details: {e}")

            hydrated_items = []
            for item in raw_items:
                ref_id = str(item.get("reference_id") or "")
                ref_type = str(item.get("reference_type") or "").lower()
                kind = item.get("item_kind") or item.get("kind") or "attraction"
                
                activity_name = item.get("activity")
                coords = item.get("coordinates")

                if not activity_name:
                    if ref_type == "hotel" or ref_id == itinerary_record.get("hotel_id"):
                        activity_name = f"Nghỉ ngơi tại {hotel_data.get('name', 'Khách sạn')}"
                    elif ref_id in attr_map:
                        activity_name = f"Tham quan {attr_map[ref_id].get('name', 'Điểm tham quan')}"
                    else:
                        activity_name = f"Hoạt động {kind}"

                if not coords:
                    if ref_type == "hotel" or ref_id == itinerary_record.get("hotel_id"):
                        coords = hotel_data.get("coordinates")
                    elif ref_id in attr_map:
                        coords = attr_map[ref_id].get("coordinates")

                hydrated_items.append({
                    "id": item.get("id"),
                    "itinerary_id": item.get("itinerary_id"),
                    "day_number": item.get("day_number"),
                    "order_index": item.get("order_index"),
                    "start_time": item.get("start_time"),
                    "end_time": item.get("end_time"),
                    "reference_type": item.get("reference_type"),
                    "reference_id": item.get("reference_id"),
                    "estimated_cost": item.get("estimated_cost"),
                    "activity": activity_name,
                    "coordinates": coords,
                    "kind": kind,
                    "item_kind": kind,
                    "route_to_next": item.get("route_to_next"),
                })

            trip_bundle = {
                "hotel": hotel_data,
                "itineraries": [itinerary_record],
                "itinerary_items": hydrated_items,
                "adjustments": []
            }
            from src.services.routing import recalculate_itinerary_routes
            recalculate_itinerary_routes(trip_bundle)

            return {"status": "success", "data": trip_bundle, "source": f"Supabase DB (id={itinerary_id})"}

        except Exception as e:
            print(f"Error loading itinerary {itinerary_id} from Supabase: {e}")

    candidate_paths = [
        BASE_DIR.parent.parent.parent / "data" / "current_trip_plan.json",
        Path("/project/data/current_trip_plan.json"),
        Path("/opt/airflow/data/current_trip_plan.json"),
        Path("data/current_trip_plan.json"),
        BASE_DIR.parent.parent.parent / "current_trip_plan.json", # fallback
        Path("/project/current_trip_plan.json"), # fallback
    ]
    for p in candidate_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                from src.services.routing import recalculate_itinerary_routes
                recalculate_itinerary_routes(data)
                return {"status": "success", "data": data, "source": str(p)}
            except Exception as e:
                return {"status": "error", "message": f"Error reading {p}: {str(e)}"}
    return {"status": "error", "message": "current_trip_plan.json not found in candidate paths. Generate a trip plan first."}

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")
