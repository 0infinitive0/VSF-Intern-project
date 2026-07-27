import os
import sys
import psycopg2
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
        
        # Create payload indexes for fast filtering
        client.create_payload_index(collection_name, "destination_id", field_schema="keyword")
        client.create_payload_index(collection_name, "category", field_schema="keyword")
        client.create_payload_index(collection_name, "is_tour", field_schema="bool")
        print("Collection created with payload indexes.")
    else:
        print(f"Collection '{collection_name}' already exists.")

def sync_attractions():
    settings = get_settings()
    
    # We use localhost and 5432 since this script runs on the host
    conn = psycopg2.connect(
        dbname='vsf_database',
        user='airflow',
        password='airflow',
        host='localhost',
        port='5432'
    )
    cursor = conn.cursor()
    
    print("Fetching attractions from PostgreSQL...")
    # Fetch data according to the schema
    try:
        cursor.execute("SELECT id, name, destination_id, description, category, is_tour, ticket_price_adult, ticket_price_child FROM attractions;")
        rows = cursor.fetchall()
    except Exception as e:
        # Fallback if some columns don't exist yet
        print(f"Error fetching exact columns, falling back to basic: {e}")
        conn.rollback()
        cursor.execute("SELECT id, name, destination_id, description, category, is_tour FROM attractions;")
        rows = [row + (None, None) for row in cursor.fetchall()]
        
    documents = []
    for row in rows:
        attraction_id, name, dest_id, desc, category, is_tour, price_adult, price_child = row
        
        # The text to embed: Tên + Mô tả + Thể loại
        page_content = f"Tên: {name}\nMô tả: {desc or ''}\nThể loại: {category or ''}"
        
        # Ticket price string formatting
        price_range = None
        if price_adult is not None:
            price_range = f"Người lớn: {price_adult}"
            if price_child is not None:
                price_range += f", Trẻ em: {price_child}"
                
        # Create metadata payload
        metadata = {
            "attraction_id": str(attraction_id),
            "name": name,
            "destination_id": str(dest_id) if dest_id else "",
            "category": category or "",
            "is_tour": bool(is_tour),
            "ticket_price_range": price_range
        }
        
        documents.append(Document(page_content=page_content, metadata=metadata))

    print(f"Prepared {len(documents)} documents for embedding.")
    
    if not documents:
        print("No documents to sync.")
        return

    # Initialize Qdrant Client directly to set up collection
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key if settings.qdrant_api_key else None)
    init_qdrant_collection(client, "attractions_vector", vector_size=1024)
    
    print("Connecting to vector store and embedding documents via Ollama (bge-m3)...")
    # This will take a while if the model is large and it's the first time processing
    vector_store = get_vector_store("attractions_vector")
    
    # We clear the existing docs by re-creating it or just add to it. 
    # For now, we just add (upsert). We could optionally delete the collection first for a clean sync.
    vector_store.add_documents(documents)
    
    print(f"Successfully synced {len(documents)} attractions to Qdrant!")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    sync_attractions()
