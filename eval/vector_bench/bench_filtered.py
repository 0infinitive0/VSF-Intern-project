"""Kịch bản 2 — Vector search + filter (Criterion B): nơi Qdrant và Supabase
thực sự khác nhau về kiến trúc.

So 2 nhánh (không có S-sql vì RPC mới chưa viết — xem TODO cuối file):
  - S-current: RPC match_hotels_with_rooms hiện tại — chỉ pre-filter
    destination_id trong SQL; star_rating/price lọc SAU trong Python
    (over-fetch 3x, và có bug fallback: filter chặt quá thì trả kết quả
    KHÔNG lọc thay vì rỗng — xem src/services/supabase_search.py:226-228).
  - Q-native: Qdrant Filter (destination_id + star_rating) pre-filter thật
    trong ANN, dùng payload index có sẵn.

Ground truth: brute-force kNN trên tập con đã lọc bằng filter y hệt (numpy).

Metric:
  - filtered_recall@10 so ground truth
  - shortfall: trả về < k dù còn đủ ứng viên hợp lệ trong corpus
  - violation: kết quả trả về mà VI PHẠM filter (bug fallback-im-lặng của
    S-current sẽ lộ ra ở đây)

Chạy: python -m eval.vector_bench.dump_vectors   (một lần)
      python -m eval.vector_bench.bench_filtered
"""
import json
import os
import time

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue, Range
from supabase import create_client

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "vector_bench")
K = 10

# (query, destination_id hoặc None, min_star_rating hoặc None)
# destination_id lấy từ bảng destinations thật trong Supabase.
FILTERED_QUERIES = [
    ("khách sạn gần biển có hồ bơi", "3d97277e-8210-45bf-9842-eea4fd356e9e", 4),  # Nha Trang, >=4 sao
    ("khách sạn giá rẻ gần trung tâm", "e42b3fcb-bf38-4168-88bd-694af25d43cc", None),  # Hà Nội, không sao
    ("resort sang trọng", "44f1bfd4-f8a9-4d49-a0fb-932d69d705c9", 5),  # Đà Nẵng, 5 sao (chọn lọc rất chặt)
    ("khách sạn boutique", "6dd17d02-74a5-4640-beb3-f116c8c34ea7", 3),  # Huế, >=3 sao
    ("chỗ ở gần trung tâm", "6f860287-189e-46db-81f6-cd3c7ee5f1f7", 2),  # HCM, >=2 sao (chọn lọc rộng)
    ("khách sạn gia đình", "3d97277e-8210-45bf-9842-eea4fd356e9e", 3),  # Nha Trang, >=3 sao
    ("resort view biển", "44f1bfd4-f8a9-4d49-a0fb-932d69d705c9", 4),  # Đà Nẵng, >=4 sao
    ("khách sạn bình dân", "e42b3fcb-bf38-4168-88bd-694af25d43cc", 5),  # Hà Nội, 5 sao (khắt khe, ít KS ở HN có 5*)
]


def load_fixture():
    vecs = np.load(os.path.join(FIXTURES_DIR, "hotels.npy"))
    with open(os.path.join(FIXTURES_DIR, "hotels.json")) as f:
        rows = json.load(f)
    return vecs, rows


def brute_force_filtered_topk(query_vec, vecs, rows, destination_id, min_star, k):
    q = np.array(query_vec, dtype=np.float32)
    q = q / np.linalg.norm(q)

    eligible_idx = []
    for i, row in enumerate(rows):
        if destination_id is not None and row.get("destination_id") != destination_id:
            continue
        star = row.get("star_rating")
        if min_star is not None:
            if star is None or float(star) < min_star:
                continue
        eligible_idx.append(i)

    n_eligible = len(eligible_idx)
    if n_eligible == 0:
        return [], 0

    eligible_vecs = vecs[eligible_idx]
    sims = eligible_vecs @ q
    order = np.argsort(-sims)[:k]
    top_ids = [rows[eligible_idx[i]]["entity_id"] for i in order]
    return top_ids, n_eligible


def qdrant_filtered_search(client, collection, vector, destination_id, min_star, k):
    must = []
    if destination_id is not None:
        must.append(FieldCondition(key="metadata.destination_id", match=MatchValue(value=destination_id)))
    if min_star is not None:
        must.append(FieldCondition(key="metadata.star_rating", range=Range(gte=min_star)))

    t0 = time.perf_counter()
    res = client.query_points(
        collection,
        query=vector,
        query_filter=Filter(must=must) if must else None,
        limit=k,
        with_payload=["metadata"],
    )
    dt = time.perf_counter() - t0
    ids = [p.payload.get("metadata", {}).get("hotel_id") for p in res.points]
    stars = [p.payload.get("metadata", {}).get("star_rating") for p in res.points]
    dests = [p.payload.get("metadata", {}).get("destination_id") for p in res.points]
    return ids, dt, stars, dests


def supabase_filtered_search(sb, vector, destination_id, min_star, k):
    """Nhân bản đúng logic search_hotels_with_rooms hiện tại (S-current),
    kể cả bug fallback im lặng — để đo baseline thật, không phải bản lý tưởng."""
    fetch_count = k * 3 if min_star else k
    params = {"query_embedding": vector, "match_threshold": 0.0, "match_count": fetch_count}
    if destination_id is not None:
        params["filter_destination_id"] = destination_id

    t0 = time.perf_counter()
    res = sb.rpc("match_hotels_with_rooms", params).execute()
    dt = time.perf_counter() - t0
    data = res.data or []

    filtered = []
    for h in data:
        if min_star is not None and min_star > 0:
            star = h.get("star_rating")
            if star is not None and int(star) < int(min_star):
                continue
        filtered.append(h)

    fell_back = False
    if not filtered and min_star and len(data) > 0:
        fell_back = True
        filtered = data[:k]

    return filtered[:k], dt, fell_back


def violation_rate(stars, dests, destination_id, min_star):
    violations = 0
    for star, dest in zip(stars, dests):
        if destination_id is not None and dest != destination_id:
            violations += 1
            continue
        if min_star is not None and (star is None or float(star) < min_star):
            violations += 1
    return violations


def recall_at_k(retrieved, ground_truth, k):
    gt = set(ground_truth[:k])
    if not gt:
        return None
    return len(gt & set(retrieved[:k])) / len(gt)


def main():
    hotels_vecs, hotels_rows = load_fixture()

    embeddings = OllamaEmbeddings(model="bge-m3", base_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    qc = QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ.get("QDRANT_API_KEY"), timeout=30)
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    hotels_collection = next(c.name for c in qc.get_collections().collections if c.name.startswith("hotels_vector"))

    rows_out = []
    for query, dest_id, min_star in FILTERED_QUERIES:
        vec = embeddings.embed_query(query)

        gt_ids, n_eligible = brute_force_filtered_topk(vec, hotels_vecs, hotels_rows, dest_id, min_star, K)

        q_ids, q_lat, q_stars, q_dests = qdrant_filtered_search(qc, hotels_collection, vec, dest_id, min_star, K)
        q_violations = violation_rate(q_stars, q_dests, dest_id, min_star)
        q_shortfall = len(q_ids) < min(K, n_eligible)

        s_data, s_lat, s_fell_back = supabase_filtered_search(sb, vec, dest_id, min_star, K)
        s_ids = [row["id"] for row in s_data]
        s_stars = [row.get("star_rating") for row in s_data]
        # S-current không trả destination_id trong response — coi như đúng
        # vì SQL đã pre-filter destination_id (điểm mạnh duy nhất của S-current).
        s_dests = [dest_id] * len(s_data)
        s_violations = violation_rate(s_stars, s_dests, None, min_star)
        s_shortfall = len(s_ids) < min(K, n_eligible)

        rows_out.append(
            {
                "query": query,
                "destination_id": dest_id,
                "min_star": min_star,
                "n_eligible": n_eligible,
                "qdrant_recall_at_10": recall_at_k(q_ids, gt_ids, K),
                "qdrant_shortfall": q_shortfall,
                "qdrant_violations": q_violations,
                "qdrant_latency_ms": q_lat * 1000,
                "supabase_recall_at_10": recall_at_k(s_ids, gt_ids, K),
                "supabase_shortfall": s_shortfall,
                "supabase_violations": s_violations,
                "supabase_fell_back_unfiltered": s_fell_back,
                "supabase_latency_ms": s_lat * 1000,
            }
        )

    header = (
        f"{'query':<30} {'star':>4} {'n_elig':>7} "
        f"{'q_rec':>6} {'q_sf':>5} {'q_vio':>6} "
        f"{'s_rec':>6} {'s_sf':>5} {'s_vio':>6} {'s_fb':>5}"
    )
    print(header)
    for r in rows_out:
        print(
            f"{r['query'][:29]:<30} {str(r['min_star']):>4} {r['n_eligible']:>7} "
            f"{r['qdrant_recall_at_10']:>6.2f} {str(r['qdrant_shortfall']):>5} {r['qdrant_violations']:>6} "
            f"{r['supabase_recall_at_10']:>6.2f} {str(r['supabase_shortfall']):>5} {r['supabase_violations']:>6} "
            f"{str(r['supabase_fell_back_unfiltered']):>5}"
        )

    q_recalls = [r["qdrant_recall_at_10"] for r in rows_out if r["qdrant_recall_at_10"] is not None]
    s_recalls = [r["supabase_recall_at_10"] for r in rows_out if r["supabase_recall_at_10"] is not None]
    print()
    print(f"Qdrant   mean filtered recall@{K}: {np.mean(q_recalls):.3f}  "
          f"shortfall_rate: {sum(r['qdrant_shortfall'] for r in rows_out)}/{len(rows_out)}  "
          f"total_violations: {sum(r['qdrant_violations'] for r in rows_out)}")
    print(f"Supabase mean filtered recall@{K}: {np.mean(s_recalls):.3f}  "
          f"shortfall_rate: {sum(r['supabase_shortfall'] for r in rows_out)}/{len(rows_out)}  "
          f"total_violations: {sum(r['supabase_violations'] for r in rows_out)}  "
          f"fell_back_unfiltered: {sum(r['supabase_fell_back_unfiltered'] for r in rows_out)}/{len(rows_out)}")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "results", "vector_bench", "raw")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bench_filtered.jsonl"), "w") as f:
        for r in rows_out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# TODO: thiếu nhánh S-sql (RPC mới đẩy star_rating vào WHERE trước ANN thay
# vì post-filter Python). Không có nó thì không tách được "chi phí sửa
# Supabase" khỏi "lợi ích thật của Qdrant" — xem plan gốc
# plans/260729-0959-vector-search-supabase-vs-qdrant/plan.md phần
# "Ba nhánh so sánh". Cần viết RPC SQL mới + migration để đo nhánh này.
if __name__ == "__main__":
    main()
