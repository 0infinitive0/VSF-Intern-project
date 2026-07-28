import os
import sys
from dotenv import load_dotenv
from qdrant_client.http.models import Filter, FilterSelector, HasIdCondition
from langchain_core.documents import Document

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from src.services.vector_store import get_vector_store, get_qdrant_client
from src.services.qdrant_schema import ATTRACTIONS_VECTOR, ensure_collection, point_id
from src.services.supabase_client import fetch_all


def sync_attractions():
    load_dotenv()

    print("Fetching attractions from Supabase...")
    rows = fetch_all(
        "attractions",
        "id,name,destination_id,description,category,is_tour,ticket_price_adult,ticket_price_child",
    )

    documents = []
    ids = []
    for row in rows:
        attraction_id = row["id"]
        name = row.get("name")
        dest_id = row.get("destination_id")
        desc = row.get("description")
        category = row.get("category")
        is_tour = row.get("is_tour")
        price_adult = row.get("ticket_price_adult")
        price_child = row.get("ticket_price_child")

        # The text to embed: Tên + Mô tả + Thể loại
        page_content = f"Tên: {name}\nMô tả: {desc or ''}\nThể loại: {category or ''}"

        # Human-readable string for display, kept alongside the raw numeric
        # value so callers can filter on price without parsing the string.
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
            "ticket_price_range": price_range,
            "ticket_price_adult": float(price_adult) if price_adult is not None else None,
        }

        documents.append(Document(page_content=page_content, metadata=metadata))
        ids.append(point_id("attraction", attraction_id))

    print(f"Prepared {len(documents)} documents for embedding.")

    if not documents:
        print("No documents to sync.")
        return

    client = get_qdrant_client()
    ensure_collection(client, ATTRACTIONS_VECTOR)

    print("Connecting to vector store and embedding documents via Ollama (bge-m3)...")
    # This will take a while if the model is large and it's the first time processing
    vector_store = get_vector_store(ATTRACTIONS_VECTOR.name)

    # Deterministic ids make this an upsert: re-running leaves points_count
    # unchanged instead of minting a fresh random id per document per run.
    written_ids = []
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        doc_batch = documents[i:i + batch_size]
        id_batch = ids[i:i + batch_size]
        vector_store.add_documents(doc_batch, ids=id_batch)
        written_ids.extend(id_batch)

    print(f"Successfully synced {len(documents)} attractions to Qdrant!")

    # Reconcile: remove points for source rows that no longer exist. Only
    # runs after every batch above succeeded — a partial failure must not
    # delete points it never got to rewrite.
    client.delete(
        collection_name=ATTRACTIONS_VECTOR.name,
        points_selector=FilterSelector(
            filter=Filter(must_not=[HasIdCondition(has_id=written_ids)])
        ),
    )
    print("Reconciled attractions_vector: removed points not in this run's source set.")


if __name__ == "__main__":
    sync_attractions()
