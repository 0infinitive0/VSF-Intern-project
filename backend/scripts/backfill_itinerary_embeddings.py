"""Resumable embedding backfill for finalized itinerary templates.

Run after ``20260728_add_itinerary_reuse.sql`` has been applied.  It only
considers finalized records with explicit destination/hotel ownership and never
changes draft itineraries.
"""

from __future__ import annotations

import argparse
import logging

from src.services.itinerary_reuse import ItineraryReuseQuery, build_itinerary_summary
from src.services.itinerary_store import ItineraryStore, ItineraryStoreError
from src.services.supabase_search import get_supabase_client

logger = logging.getLogger(__name__)


def _child_focused(preferences: list[str]) -> bool:
    text = " ".join(preferences).casefold()
    return any(word in text for word in ("trẻ em", "tre em", "children", "child", "kids", "gia đình", "gia dinh"))


def backfill(*, limit: int, dry_run: bool) -> tuple[int, int]:
    client = get_supabase_client()
    store = ItineraryStore.from_default()
    response = (
        client.table("itineraries")
        .select("id,destination_id,hotel_id,duration_days,number_of_adults,number_of_children,preferences,day_themes,planning_constraints,budget")
        .eq("status", "Finalized")
        .is_("embedding", "null")
        .limit(limit)
        .execute()
    )
    completed = 0
    failed = 0
    for row in response.data or []:
        itinerary_id = str(row.get("id") or "")
        if not itinerary_id or not row.get("destination_id") or not row.get("hotel_id"):
            logger.warning("Skipping %s because its ownership fields are incomplete", itinerary_id or "unknown")
            failed += 1
            continue
        bundle = store.load_itinerary_bundle(itinerary_id)
        if not bundle or not bundle.hotel.get("coordinates"):
            logger.warning("Skipping %s because its template bundle is incomplete", itinerary_id)
            failed += 1
            continue
        preferences = [str(value) for value in row.get("preferences") or []]
        query = ItineraryReuseQuery(
            destination_id=str(row["destination_id"]),
            destination_name=str(row["destination_id"]),
            duration_days=int(row.get("duration_days") or 0),
            number_of_adults=int(row.get("number_of_adults") or 1),
            number_of_children=int(row.get("number_of_children") or 0),
            preferences=tuple(preferences),
            child_focused=_child_focused(preferences),
            hotel_id=str(row["hotel_id"]),
            planning_constraints=dict(row.get("planning_constraints") or {}),
        )
        summary = build_itinerary_summary(
            query,
            day_themes=bundle.template.day_themes,
            hotel=bundle.hotel,
            items=bundle.template.items,
            budget=row.get("budget"),
        )
        if dry_run:
            print(f"would embed {itinerary_id}: {summary}")
            completed += 1
            continue
        try:
            store.refresh_embedding(itinerary_id, summary)
            completed += 1
        except ItineraryStoreError as exc:
            logger.warning("Embedding backfill failed for %s: %s", itinerary_id, exc)
            failed += 1
    return completed, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="maximum finalized rows to process")
    parser.add_argument("--dry-run", action="store_true", help="show deterministic summaries without writing")
    args = parser.parse_args()
    completed, failed = backfill(
        limit=max(1, min(args.limit, 1_000)),
        dry_run=args.dry_run,
    )
    print(f"completed={completed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
