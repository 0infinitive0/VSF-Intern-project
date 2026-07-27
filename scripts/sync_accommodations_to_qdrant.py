import os
import sys
from dotenv import load_dotenv
from supabase import create_client, Client
from qdrant_client.http.models import Distance, VectorParams
from langchain_core.documents import Document

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.services.vector_store import get_vector_store
from src.config import get_settings
from qdrant_client import QdrantClient

def init_qdrant_collection(client: QdrantClient, collection_name: str, vector_size: int = 1024):
    """Ensure the Qdrant collection exists with the correct configuration."""
    if not client.collection_exists(collection_name):
        print(f"Creating collection '{collection_name}' with vector size {vector_size}...")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
    else:
        print(f"Collection '{collection_name}' already exists.")

def sync_accommodations():
    settings = get_settings()
    load_dotenv()
    
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    
    # 1. Sync Hotels
    print("Fetching hotels from Supabase...")
    hotels_response = supabase.table("hotels").select("*").execute()
    hotels = hotels_response.data
    
    hotel_documents = []
    for h in hotels:
        name = h.get('name') or ''
        desc = h.get('description') or ''
        acc_type = h.get('accommodation_type') or ''
        area = h.get('area_name') or ''
        amenities = h.get('amenities') or []
        amenities_str = ', '.join(amenities) if isinstance(amenities, list) else amenities
        
        page_content = f"Tên: {name}\nLoại hình: {acc_type}\nKhu vực: {area}\nMô tả: {desc}\nTiện ích: {amenities_str}"
        
        metadata = {
            "hotel_id": h.get("id"),
            "name": name,
            "destination_id": h.get("destination_id"),
            "star_rating": h.get("star_rating"),
            "price_tier": None, # Will populate dynamically if needed later
            "amenities": amenities if isinstance(amenities, list) else []
        }
        hotel_documents.append(Document(page_content=page_content, metadata=metadata))

    # 2. Sync Rooms
    print("Fetching rooms from Supabase...")
    rooms_response = supabase.table("rooms").select("*").execute()
    rooms = rooms_response.data
    
    room_documents = []
    for r in rooms:
        name = r.get('name') or ''
        bed = r.get('bed_description') or ''
        facilities = r.get('room_facilities') or []
        facilities_str = ', '.join(facilities) if isinstance(facilities, list) else facilities
        view = r.get('view') or ''
        
        page_content = f"Tên phòng: {name}\nGiường: {bed}\nHướng nhìn: {view}\nTiện ích phòng: {facilities_str}"
        
        metadata = {
            "room_id": r.get("id"),
            "hotel_id": r.get("hotel_id"),
            "name": name,
            "max_guests": r.get("max_guests"),
            "room_size_sqm": float(r.get("room_size_sqm")) if r.get("room_size_sqm") else None,
            "view": view
        }
        room_documents.append(Document(page_content=page_content, metadata=metadata))

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key if settings.qdrant_api_key else None)
    
    print(f"Prepared {len(hotel_documents)} hotels and {len(room_documents)} rooms for embedding.")
    
    # Init and embed Hotels
    if hotel_documents:
        init_qdrant_collection(client, "hotels_vector", vector_size=1024)
        print("Connecting to vector store and embedding hotels...")
        hotels_vector_store = get_vector_store("hotels_vector")
        hotels_vector_store.add_documents(hotel_documents)
        print("Successfully synced hotels to Qdrant!")

    # Init and embed Rooms
    if room_documents:
        init_qdrant_collection(client, "rooms_vector", vector_size=1024)
        print("Connecting to vector store and embedding rooms...")
        rooms_vector_store = get_vector_store("rooms_vector")
        
        batch_size = 100
        for i in range(0, len(room_documents), batch_size):
            batch = room_documents[i:i+batch_size]
            print(f"Embedding rooms batch {i} to {i+len(batch)}...")
            rooms_vector_store.add_documents(batch)
        print("Successfully synced rooms to Qdrant!")

if __name__ == "__main__":
    sync_accommodations()
