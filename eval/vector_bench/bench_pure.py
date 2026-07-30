"""Kịch bản 1 — Vector search thuần (Criterion A): so recall@10 và latency
giữa Qdrant local (chỉ search hotels_vector) và Supabase RPC match_hotels_with_rooms,
dùng chung một bộ query đã embed sẵn.

Ground truth: brute-force, PHẢI max-pool qua cả hotel-doc và room-doc embedding
để khớp đúng hàm mục tiêu thật của match_hotels_with_rooms — RPC đó UNION hotel
similarity với room similarity rồi GROUP BY hotel_id lấy MAX(sim). Nếu ground
truth chỉ so hotel-doc, nó so sai đối tượng: nhiều hotel lọt top-k vì MỘT phòng
của nó khớp ngữ nghĩa cao, không phải vì mô tả hotel khớp — đã phát hiện qua
review thân hàm RPC thật (union all hotel_scores + room_scores, group by
hotel_id, max(sim)).

Qdrant collection hotels_vector chỉ chứa hotel-doc embedding (không có room),
nên Qdrant trong benchmark này đo được recall so với "chỉ hotel-doc", còn
Supabase đo recall so với "max(hotel-doc, room-doc)" — ground truth dưới đây
tính cả hai để so công bằng với từng store theo đúng domain của nó.

Chạy: python -m eval.vector_bench.dump_vectors   (một lần, để tạo fixture)
      python -m eval.vector_bench.bench_pure
"""
import json
import os
import time

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from supabase import create_client

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "vector_bench")
K = 10

QUERIES = [
    "khách sạn gần biển có hồ bơi",
    "phòng gia đình rộng rãi cho 4 người",
    "khách sạn giá rẻ gần trung tâm Hà Nội",
    "resort 5 sao view biển Nha Trang",
    "homestay yên tĩnh gần chợ Đà Lạt",
    "khách sạn có bồn tắm và spa",
    "chỗ ở gần sân bay Đà Nẵng",
    "khách sạn boutique phong cách cổ điển",
    "phòng đôi có ban công nhìn ra thành phố",
    "khách sạn cho phép mang thú cưng",
    "chỗ nghỉ giá rẻ cho sinh viên",
    "khách sạn gần phố cổ Hội An",
    "resort có bãi biển riêng",
    "khách sạn có phòng gym và hồ bơi vô cực",
    "nhà nghỉ bình dân gần bến xe",
    "khách sạn sang trọng cho tuần trăng mật",
    "chỗ ở có bếp riêng để tự nấu ăn",
    "khách sạn gần Vincom trung tâm mua sắm",
    "phòng có view núi Đà Lạt",
    "khách sạn thân thiện với gia đình có trẻ em",
]


def brute_force_topk(query_vec, corpus_vecs, entity_ids, k):
    q = np.array(query_vec, dtype=np.float32)
    q = q / np.linalg.norm(q)
    sims = corpus_vecs @ q
    top_idx = np.argsort(-sims)[:k]
    return [entity_ids[i] for i in top_idx]


def brute_force_topk_hotel_or_room_max(query_vec, hotel_vecs, hotel_ids, room_vecs, room_hotel_ids, k):
    """Ground truth khớp đúng match_hotels_with_rooms: với mỗi hotel, lấy
    max(sim với hotel-doc, max sim với bất kỳ room-doc nào của hotel đó)."""
    q = np.array(query_vec, dtype=np.float32)
    q = q / np.linalg.norm(q)

    best_sim = {}
    hotel_sims = hotel_vecs @ q
    for hid, sim in zip(hotel_ids, hotel_sims):
        best_sim[hid] = max(best_sim.get(hid, -1.0), float(sim))

    room_sims = room_vecs @ q
    for hid, sim in zip(room_hotel_ids, room_sims):
        best_sim[hid] = max(best_sim.get(hid, -1.0), float(sim))

    ranked = sorted(best_sim.items(), key=lambda kv: -kv[1])[:k]
    return [hid for hid, _ in ranked]


def recall_at_k(retrieved, ground_truth, k):
    gt = set(ground_truth[:k])
    if not gt:
        return None
    return len(gt & set(retrieved[:k])) / len(gt)


def qdrant_search(client, collection, vector, k):
    t0 = time.perf_counter()
    res = client.query_points(collection, query=vector, limit=k, with_payload=["metadata"])
    dt = time.perf_counter() - t0
    ids = [p.payload.get("metadata", {}).get("hotel_id") for p in res.points]
    return ids, dt


def supabase_search(sb, vector, k):
    t0 = time.perf_counter()
    res = sb.rpc(
        "match_hotels_with_rooms",
        {"query_embedding": vector, "match_threshold": 0.0, "match_count": k},
    ).execute()
    dt = time.perf_counter() - t0
    ids = [row["id"] for row in (res.data or [])]
    return ids, dt


def percentile(values, p):
    return float(np.percentile(values, p))


def main():
    hotels_vecs = np.load(os.path.join(FIXTURES_DIR, "hotels.npy"))
    with open(os.path.join(FIXTURES_DIR, "hotels.json")) as f:
        hotels_rows = json.load(f)
    entity_ids = [row["entity_id"] for row in hotels_rows]

    rooms_vecs = np.load(os.path.join(FIXTURES_DIR, "rooms.npy"))
    with open(os.path.join(FIXTURES_DIR, "rooms.json")) as f:
        rooms_rows = json.load(f)
    room_hotel_ids = [row["hotel_id"] for row in rooms_rows]

    embeddings = OllamaEmbeddings(model="bge-m3", base_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    qc = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ.get("QDRANT_API_KEY"), timeout=30)
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    hotels_collection = next(c.name for c in qc.get_collections().collections if c.name.startswith("hotels_vector"))

    rows = []
    for query in QUERIES:
        vec = embeddings.embed_query(query)

        # Qdrant hotels_vector chỉ chứa hotel-doc -> so với ground truth hotel-doc thuần.
        gt_hotel_only = brute_force_topk(vec, hotels_vecs, entity_ids, K)
        # match_hotels_with_rooms UNION hotel-doc + room-doc rồi MAX theo hotel_id
        # -> so với ground truth khớp đúng hàm mục tiêu đó.
        gt_hotel_or_room = brute_force_topk_hotel_or_room_max(
            vec, hotels_vecs, entity_ids, rooms_vecs, room_hotel_ids, K
        )

        q_ids, q_lat = qdrant_search(qc, hotels_collection, vec, K)
        s_ids, s_lat = supabase_search(sb, vec, K)

        rows.append(
            {
                "query": query,
                "qdrant_recall_at_10": recall_at_k(q_ids, gt_hotel_only, K),
                "supabase_recall_at_10": recall_at_k(s_ids, gt_hotel_or_room, K),
                "qdrant_latency_ms": q_lat * 1000,
                "supabase_latency_ms": s_lat * 1000,
            }
        )

    print(f"{'query':<45} {'q_recall':>9} {'s_recall':>9} {'q_ms':>8} {'s_ms':>8}")
    for r in rows:
        print(
            f"{r['query'][:44]:<45} {r['qdrant_recall_at_10']:>9.2f} {r['supabase_recall_at_10']:>9.2f} "
            f"{r['qdrant_latency_ms']:>8.1f} {r['supabase_latency_ms']:>8.1f}"
        )

    q_recalls = [r["qdrant_recall_at_10"] for r in rows]
    s_recalls = [r["supabase_recall_at_10"] for r in rows]
    q_lats = [r["qdrant_latency_ms"] for r in rows]
    s_lats = [r["supabase_latency_ms"] for r in rows]

    print()
    print(f"Qdrant   mean recall@{K}: {np.mean(q_recalls):.3f}  "
          f"p50/p95 latency: {percentile(q_lats,50):.1f}/{percentile(q_lats,95):.1f} ms")
    print(f"Supabase mean recall@{K}: {np.mean(s_recalls):.3f}  "
          f"p50/p95 latency: {percentile(s_lats,50):.1f}/{percentile(s_lats,95):.1f} ms")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "results", "vector_bench", "raw")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bench_pure.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
