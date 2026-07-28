import os
import sys
from dotenv import load_dotenv
from qdrant_client.http.models import Filter, FilterSelector, HasIdCondition
from langchain_core.documents import Document

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.services.vector_store import get_vector_store, get_qdrant_client
from src.services.qdrant_schema import HOTELS_VECTOR, ROOMS_VECTOR, ensure_collection, point_id
from src.services.supabase_client import fetch_all


def sync_accommodations():
    load_dotenv()

    # 1. Sync Hotels
    print("Fetching hotels from Supabase...")
    hotels = fetch_all("hotels", "*")
    
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
    rooms = fetch_all("rooms", "*")

    # Room point IDs must key on (source_platform, source_hotel_id,
    # source_room_id), not rooms.hotel_id — hotel_id is a surrogate that can
    # change on a hotel reload, which would otherwise duplicate every room.
    hotel_identity = {h["id"]: (h.get("source_platform"), h.get("source_hotel_id")) for h in hotels}

    room_documents = []
    room_ids = []
    for r in rooms:
        name = r.get('name') or ''
        bed = r.get('bed_description') or ''
        facilities = r.get('room_facilities') or []
        facilities_str = ', '.join(facilities) if isinstance(facilities, list) else facilities
        view = r.get('view') or ''

        page_content = f"Tên phòng: {name}\nGiường: {bed}\nHướng nhìn: {view}\nTiện ích phòng: {facilities_str}"

        source_platform, source_hotel_id = hotel_identity.get(r.get("hotel_id"), (None, None))
        metadata = {
            "room_id": r.get("id"),
            "hotel_id": r.get("hotel_id"),
            "source_platform": source_platform,
            "source_hotel_id": source_hotel_id,
            "name": name,
            "max_guests": r.get("max_guests"),
            "room_size_sqm": float(r.get("room_size_sqm")) if r.get("room_size_sqm") else None,
            "view": view
        }
        room_documents.append(Document(page_content=page_content, metadata=metadata))
        room_ids.append(point_id("room", source_platform, source_hotel_id, r.get("source_room_id")))

    client = get_qdrant_client()

    print(f"Prepared {len(hotel_documents)} hotels and {len(room_documents)} rooms for embedding.")

    # Init and embed Hotels
    if hotel_documents:
        ensure_collection(client, HOTELS_VECTOR)
        print("Connecting to vector store and embedding hotels...")
        hotels_vector_store = get_vector_store(HOTELS_VECTOR.name)
        hotels_vector_store.add_documents(hotel_documents)
        print("Successfully synced hotels to Qdrant!")

    # Init and embed Rooms
    if room_documents:
        ensure_collection(client, ROOMS_VECTOR)
        print("Connecting to vector store and embedding rooms...")
        rooms_vector_store = get_vector_store(ROOMS_VECTOR.name)

        # Slice one list of (document, id) pairs, not two parallel lists —
        # slicing them separately risks an off-by-one that mis-assigns ids.
        pairs = list(zip(room_documents, room_ids))
        written_room_ids = []
        batch_size = 100
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i + batch_size]
            doc_batch = [p[0] for p in batch]
            id_batch = [p[1] for p in batch]
            print(f"Embedding rooms batch {i} to {i+len(batch)}...")
            rooms_vector_store.add_documents(doc_batch, ids=id_batch)
            written_room_ids.extend(id_batch)
        print("Successfully synced rooms to Qdrant!")

        # Reconcile: only after every batch above succeeded.
        client.delete(
            collection_name=ROOMS_VECTOR.name,
            points_selector=FilterSelector(
                filter=Filter(must_not=[HasIdCondition(has_id=written_room_ids)])
            ),
        )
        print("Reconciled rooms_vector: removed points not in this run's source set.")

if __name__ == "__main__":
    sync_accommodations()
