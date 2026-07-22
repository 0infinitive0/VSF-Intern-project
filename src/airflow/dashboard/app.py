from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import psycopg2

app = FastAPI()
templates = Jinja2Templates(directory="templates")

db_conn_kwargs = {
    'dbname': 'vsf_database',
    'user': 'airflow',
    'password': 'airflow',
    'host': 'postgres',
    'port': '5432'
}

def get_db_connection():
    return psycopg2.connect(**db_conn_kwargs)

def parse_images(imgs):
    if not imgs:
        return []
    if isinstance(imgs, list) and len(imgs) == 1 and isinstance(imgs[0], str) and imgs[0].startswith('{') and imgs[0].endswith('}'):
        return [img.strip() for img in imgs[0].strip('{}').split(',') if img.strip()]
    return imgs

@app.get("/api/locations")
def get_locations():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Attractions
        cursor.execute("SELECT id, name, category, coordinates, images FROM attractions WHERE coordinates IS NOT NULL;")
        attraction_rows = cursor.fetchall()
        
        # Destinations
        cursor.execute("SELECT id, name, region, coordinates FROM destinations WHERE coordinates IS NOT NULL;")
        destination_rows = cursor.fetchall()
        
        # Hotels
        cursor.execute("SELECT id, name, star_rating, coordinates, images, source_urls FROM hotels WHERE coordinates IS NOT NULL;")
        hotel_rows = cursor.fetchall()
        
        locations = []
        for row in attraction_rows:
            item_id, name, category, coords, images = row
            try:
                lat, lng = coords.split(',')
                locations.append({
                    "id": str(item_id),
                    "name": name,
                    "category": category,
                    "lat": float(lat),
                    "lng": float(lng),
                    "images": parse_images(images),
                    "type": "attraction"
                })
            except Exception:
                continue
                
        for row in destination_rows:
            item_id, name, region, coords = row
            try:
                lat, lng = coords.split(',')
                locations.append({
                    "id": str(item_id),
                    "name": name,
                    "category": region,
                    "lat": float(lat),
                    "lng": float(lng),
                    "images": [],
                    "type": "destination"
                })
            except Exception:
                continue
                
        for row in hotel_rows:
            item_id, name, star_rating, coords, images, source_urls = row
            try:
                lat, lng = coords.split(',')
                locations.append({
                    "id": str(item_id),
                    "name": name,
                    "category": f"{star_rating} Star" if star_rating else "Hotel",
                    "lat": float(lat),
                    "lng": float(lng),
                    "images": parse_images(images),
                    "source_urls": parse_images(source_urls),
                    "type": "hotel"
                })
            except Exception:
                continue
                
        cursor.close()
        conn.close()
        return {"status": "success", "data": locations}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")
