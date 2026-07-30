"""Dump vectors + payload từ Qdrant local (nguồn chuẩn, đã verify parity với
Supabase) ra .npy + .json để dùng làm ground truth brute-force cho benchmark.

Chạy: python -m eval.vector_bench.dump_vectors
"""
import json
import os

import numpy as np
from dotenv import load_dotenv
from qdrant_client import QdrantClient

load_dotenv()

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "vector_bench")


def dump_collection(qc: QdrantClient, collection: str, id_field_path: list[str], out_name: str):
    vectors = []
    rows = []
    next_offset = None
    while True:
        points, next_offset = qc.scroll(
            collection, limit=500, offset=next_offset, with_payload=True, with_vectors=True
        )
        for p in points:
            payload = p.payload or {}
            metadata = payload.get("metadata", payload)
            entity_id = metadata.get(id_field_path[-1]) if len(id_field_path) > 1 else payload.get(id_field_path[0])
            if entity_id is None or not p.vector:
                continue
            vectors.append(p.vector)
            row = {"point_id": p.id, "entity_id": entity_id}
            row.update({k: v for k, v in metadata.items() if not isinstance(v, (list, dict))})
            rows.append(row)
        if next_offset is None:
            break

    os.makedirs(FIXTURES_DIR, exist_ok=True)
    vec_array = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(vec_array, axis=1, keepdims=True)
    vec_array = vec_array / norms

    np.save(os.path.join(FIXTURES_DIR, f"{out_name}.npy"), vec_array)
    with open(os.path.join(FIXTURES_DIR, f"{out_name}.json"), "w") as f:
        json.dump(rows, f, ensure_ascii=False)
    print(f"{out_name}: {len(rows)} rows dumped, vector shape {vec_array.shape}")


def main():
    qc = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ.get("QDRANT_API_KEY"), timeout=30)

    hotels_collection = next(c.name for c in qc.get_collections().collections if c.name.startswith("hotels_vector"))

    dump_collection(qc, hotels_collection, ["metadata", "hotel_id"], "hotels")
    dump_collection(qc, "rooms_vector", ["metadata", "room_id"], "rooms")
    dump_collection(qc, "attractions_vector", ["metadata", "attraction_id"], "attractions")


if __name__ == "__main__":
    main()
