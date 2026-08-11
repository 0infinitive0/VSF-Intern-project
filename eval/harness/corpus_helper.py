"""Authoring aid for Phase 2: filter the offline vector_bench fixture by
structured attributes (destination, star rating) while writing golden
records. Semantic judgement (sea view, family-friendly, ...) is not in this
fixture and must come from reading the live Supabase row - see
eval/datasets/README.md for how those candidates were resolved.

Usage: eval/.venv-eval/bin/python eval/harness/corpus_helper.py --destination "Nha Trang" --min-star 4
"""

import argparse
import json
from pathlib import Path
from typing import Any

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "vector_bench"

DESTINATION_NAME_TO_ID = {
    "nha trang": "3d97277e-8210-45bf-9842-eea4fd356e9e",
    "ha noi": "e42b3fcb-bf38-4168-88bd-694af25d43cc",
    "hà nội": "e42b3fcb-bf38-4168-88bd-694af25d43cc",
    "da nang": "44f1bfd4-f8a9-4d49-a0fb-932d69d705c9",
    "đà nẵng": "44f1bfd4-f8a9-4d49-a0fb-932d69d705c9",
    "hue": "6dd17d02-74a5-4640-beb3-f116c8c34ea7",
    "huế": "6dd17d02-74a5-4640-beb3-f116c8c34ea7",
    "ho chi minh": "6f860287-189e-46db-81f6-cd3c7ee5f1f7",
    "hồ chí minh": "6f860287-189e-46db-81f6-cd3c7ee5f1f7",
}


def load_hotels() -> list[dict[str, Any]]:
    with open(_FIXTURES_DIR / "hotels.json", encoding="utf-8") as f:
        return json.load(f)


def load_attractions() -> list[dict[str, Any]]:
    with open(_FIXTURES_DIR / "attractions.json", encoding="utf-8") as f:
        return json.load(f)


def filter_hotels(
    destination: str | None = None,
    min_star: float | None = None,
    max_star: float | None = None,
) -> list[dict[str, Any]]:
    """Filter the fixture by structured attributes only - no semantic filtering."""
    hotels = load_hotels()
    if destination:
        dest_id = DESTINATION_NAME_TO_ID.get(destination.casefold())
        if dest_id is None:
            raise ValueError(f"Unknown destination: {destination!r}")
        hotels = [h for h in hotels if h["destination_id"] == dest_id]
    if min_star is not None:
        hotels = [h for h in hotels if (h.get("star_rating") or 0) >= min_star]
    if max_star is not None:
        hotels = [h for h in hotels if (h.get("star_rating") or 0) <= max_star]
    return hotels


def filter_attractions(destination: str | None = None) -> list[dict[str, Any]]:
    attractions = load_attractions()
    if destination:
        dest_id = DESTINATION_NAME_TO_ID.get(destination.casefold())
        if dest_id is None:
            raise ValueError(f"Unknown destination: {destination!r}")
        attractions = [a for a in attractions if a["destination_id"] == dest_id]
    return attractions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination")
    parser.add_argument("--min-star", type=float)
    parser.add_argument("--max-star", type=float)
    parser.add_argument("--attractions", action="store_true", help="filter attractions instead of hotels")
    args = parser.parse_args()

    if args.attractions:
        candidates = filter_attractions(destination=args.destination)
        for a in candidates:
            print(f"{a['attraction_id']}  {a['name']}  ({a['category']})")
    else:
        candidates = filter_hotels(
            destination=args.destination, min_star=args.min_star, max_star=args.max_star
        )
        for h in candidates:
            print(f"{h['hotel_id']}  {h['name']}  star={h.get('star_rating')}")
    print(f"\n{len(candidates)} candidates")


if __name__ == "__main__":
    main()
