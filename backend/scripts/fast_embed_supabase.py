"""Fast parallel script to backfill ALL NULL embeddings into Supabase using Cloudflare Workers AI."""

import json
import os
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://baoeafpfyhraufinosqr.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "sb_publishable_8btzYuf2YiNUxPiSG44XSA_wcZ3DJaO")
CF_BASE = os.getenv("EMBEDDING_API_BASE", "https://api.cloudflare.com/client/v4/accounts/e8045479a2ef8992d1258b748ac5f4c0/ai/v1")
CF_TOKEN = os.getenv("EMBEDDING_API_KEY") or os.getenv("CLOUDFLARE_API_TOKEN", "cfut_SjRd9EeR14qMAI020VSiQWckIuRw6mL5mpDMnLAY930d07a2")
CF_MODEL = os.getenv("EMBEDDING_MODEL", "@cf/baai/bge-m3")

HEADERS_SUPABASE = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

HEADERS_CF = {
    "Authorization": f"Bearer {CF_TOKEN}",
    "Content-Type": "application/json",
}


def _joined(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def build_text(table, row):
    if table == "hotels":
        return (
            f"Tên: {row.get('name') or ''}\n"
            f"Loại hình: {row.get('accommodation_type') or ''}\n"
            f"Khu vực: {row.get('area_name') or ''}\n"
            f"Mô tả: {row.get('description') or ''}\n"
            f"Tiện ích: {_joined(row.get('amenities'))}"
        )
    if table == "rooms":
        return (
            f"Tên phòng: {row.get('name') or ''}\n"
            f"Giường: {row.get('bed_description') or ''}\n"
            f"Hướng nhìn: {row.get('view') or ''}\n"
            f"Tiện ích phòng: {_joined(row.get('room_facilities'))}"
        )
    return (
        f"Tên: {row.get('name') or ''}\n"
        f"Mô tả: {row.get('description') or ''}\n"
        f"Thể loại: {row.get('category') or ''}"
    )


def embed_single_row(table, row):
    row_id = row.get("id")
    text = build_text(table, row)
    
    url_cf = f"{CF_BASE.rstrip('/')}/embeddings"
    body = json.dumps({"model": CF_MODEL, "input": text})
    
    try:
        res = requests.post(url_cf, data=body, headers=HEADERS_CF, timeout=30)
        res.raise_for_status()
        vector = res.json()["data"][0]["embedding"]
    except Exception as exc:
        print(f"[{table}/{row_id}] CF error: {exc}")
        return False

    if len(vector) != 1024:
        print(f"[{table}/{row_id}] Invalid dim: {len(vector)}")
        return False

    url_sp = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}"
    headers_sp = {**HEADERS_SUPABASE, "Prefer": "return=minimal"}
    try:
        res_sp = requests.patch(url_sp, json={"embedding": vector}, headers=headers_sp, timeout=30)
        res_sp.raise_for_status()
        return True
    except Exception as exc:
        print(f"[{table}/{row_id}] Supabase patch error: {exc}")
        return False


def process_table(table, columns, max_workers=15):
    print(f"\n--- Processing table: {table} ---")
    
    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select={columns}&embedding=is.null&limit=1000"
        res = requests.get(url, headers=HEADERS_SUPABASE)
        rows = res.json()
        total = len(rows)

        if not total:
            print(f"[{table}] 100% Complete! All rows are embedded.")
            break

        print(f"[{table}] Found {total} pending NULL rows in current batch.")
        success_count = 0
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(embed_single_row, table, row): row for row in rows}
            for i, future in enumerate(as_completed(futures), 1):
                if future.result():
                    success_count += 1
                if i % 100 == 0 or i == total:
                    elapsed = time.time() - start_time
                    rate = i / elapsed if elapsed > 0 else 0
                    print(f"[{table}] Batch Progress: {i}/{total} ({success_count} success) - {rate:.1f} rows/sec")

        print(f"[{table}] Batch Finished! {success_count}/{total} embedded successfully.")


def main():
    tables = {
        "hotels": "id,name,accommodation_type,area_name,description,amenities",
        "rooms": "id,name,bed_description,view,room_facilities",
        "attractions": "id,name,description,category",
    }
    for table, cols in tables.items():
        process_table(table, cols, max_workers=25)


if __name__ == "__main__":
    main()
