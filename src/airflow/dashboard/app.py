import os
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from supabase import create_client, Client

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Try to initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

supabase: Client = None
if SUPABASE_URL and SUPABASE_ANON_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    except Exception as e:
        print(f"Failed to initialize Supabase client: {e}")

@app.get("/api/locations")
def get_locations():
    if not supabase:
        return {"status": "error", "message": "Supabase client not initialized. Check your environment variables (.env file)."}
        
    try:
        locations = []
        
        # 1. Attractions
        try:
            response = supabase.table("attractions").select("id, name, category, coordinates, images").not_.is_("coordinates", "null").execute()
            for row in response.data:
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

@app.get("/api/trip_plan")
def get_trip_plan():
    candidates = [
        BASE_DIR.parent.parent.parent / "current_trip_plan.json", # local root repo dir
        Path("/project/current_trip_plan.json"), # docker volume mount
        Path("/opt/airflow/current_trip_plan.json"),
        Path("current_trip_plan.json"),
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {"status": "success", "data": data, "source": str(p)}
            except Exception as e:
                return {"status": "error", "message": f"Error reading {p}: {str(e)}"}
    return {"status": "error", "message": "current_trip_plan.json not found in candidate paths. Generate a trip plan first."}

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")
