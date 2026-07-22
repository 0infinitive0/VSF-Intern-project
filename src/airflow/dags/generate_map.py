import psycopg2
import json

db_conn_kwargs = {
    'dbname': 'vsf_database',
    'user': 'airflow',
    'password': 'airflow',
    'host': 'postgres',
    'port': '5432'
}

def generate_map():
    conn = psycopg2.connect(**db_conn_kwargs)
    cursor = conn.cursor()
    cursor.execute("SELECT name, category, coordinates FROM attractions WHERE coordinates IS NOT NULL;")
    rows = cursor.fetchall()
    
    markers = []
    for row in rows:
        name, category, coords = row
        lat, lng = coords.split(',')
        markers.append({
            "name": name,
            "category": category,
            "lat": float(lat),
            "lng": float(lng)
        })
        
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Attractions Map</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ height: 100vh; width: 100vw; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        var locations = {json.dumps(markers)};
        
        if (locations.length > 0) {{
            var map = L.map('map').setView([locations[0].lat, locations[0].lng], 13);
            
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                maxZoom: 19,
                attribution: '&copy; OpenStreetMap'
            }}).addTo(map);
            
            var bounds = [];
            locations.forEach(function(loc) {{
                var marker = L.marker([loc.lat, loc.lng]).addTo(map);
                marker.bindPopup("<b>" + loc.name + "</b><br>" + loc.category);
                bounds.push([loc.lat, loc.lng]);
            }});
            
            if (bounds.length > 0) {{
                map.fitBounds(bounds);
            }}
        }} else {{
            document.body.innerHTML = "<h1>No coordinates found in database.</h1>";
        }}
    </script>
</body>
</html>
"""
    
    with open('/opt/airflow/dags/map.html', 'w', encoding='utf-8') as f:
        f.write(html_content)
        
    print("Map generated at /opt/airflow/dags/map.html")
    
if __name__ == "__main__":
    generate_map()
