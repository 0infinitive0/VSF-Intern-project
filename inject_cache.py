import re

filepath = r"d:\Git repo\vsf-project\src\airflow\dags\data_pipeline\google_maps_pipeline.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add imports and cache helpers
imports_target = """import ipaddress
import json
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple"""

imports_replacement = """import ipaddress
import json
import math
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple"""

cache_helpers = """
_MAPS_CACHE_FILE = "data/google_maps_cache.jsonl"
_MAPS_CACHE_LOCK = threading.Lock()

def _load_maps_cache() -> Dict[str, Any]:
    cache = {}
    if os.path.exists(_MAPS_CACHE_FILE):
        with open(_MAPS_CACHE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    cache[entry["seed_name"]] = entry["result"]
                except Exception:
                    pass
    return cache

def _append_to_maps_cache(seed_name: str, result: Optional[Dict[str, Any]]):
    with _MAPS_CACHE_LOCK:
        os.makedirs(os.path.dirname(_MAPS_CACHE_FILE), exist_ok=True)
        with open(_MAPS_CACHE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"seed_name": seed_name, "result": result}, ensure_ascii=False) + "\\n")
"""

content = content.replace(imports_target, imports_replacement, 1)
if "_MAPS_CACHE_FILE" not in content:
    content = content.replace("\nVIETNAMESE_CHARACTERS = set(", cache_helpers + "\n\nVIETNAMESE_CHARACTERS = set(", 1)

# 2. Modify resolve_google_maps_nearby_candidates
func_start_target = """    candidates: Dict[str, Dict[str, Any]] = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        try:
            for seed in seeds:
                name = sanitize_attraction_name(seed.get("name", ""))"""

func_start_replacement = """    candidates: Dict[str, Dict[str, Any]] = {}
    
    cache = _load_maps_cache()
    unseen_seeds = []
    for seed in seeds:
        name = sanitize_attraction_name(seed.get("name", ""))
        if not name:
            continue
        if name in cache:
            candidate = cache[name]
            if candidate:
                if not _within_hotel_radius(candidate, hotel_radius_meters):
                    pass
                elif not is_coordinate_allowed(
                    float(candidate["latitude"]),
                    float(candidate["longitude"]),
                    location_context,
                ):
                    pass
                else:
                    candidates.setdefault(str(candidate["source_id"]), candidate)
        else:
            unseen_seeds.append(seed)

    if not unseen_seeds:
        return list(candidates.values())

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        try:
            for seed in unseen_seeds:
                name = sanitize_attraction_name(seed.get("name", ""))"""

content = content.replace(func_start_target, func_start_replacement, 1)

# 3. Modify the end of the loop
loop_end_target = """                    else:
                        candidates.setdefault(str(candidate["source_id"]), candidate)
                except Exception as exc:
                    print(f"[hotel-nearby] Could not resolve {name} near hotel: {exc}")
                time.sleep(0.75)"""

loop_end_replacement = """                    else:
                        candidates.setdefault(str(candidate["source_id"]), candidate)
                    _append_to_maps_cache(name, candidate)
                except Exception as exc:
                    print(f"[hotel-nearby] Could not resolve {name} near hotel: {exc}")
                    _append_to_maps_cache(name, None)
                time.sleep(0.75)"""

content = content.replace(loop_end_target, loop_end_replacement, 1)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Patch applied.")
