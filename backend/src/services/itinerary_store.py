"""Supabase boundary for durable, reusable itinerary bundles.

The store intentionally delegates policy to ``itinerary_reuse`` and the trip
scheduler.  It validates third-party response shapes at this boundary and never
updates the terminal JSON file itself.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from src.api.streaming import emit_phase
from src.services.itinerary_reuse import (
    EMBEDDING_DIMENSION,
    ItineraryReuseQuery,
    ItineraryTemplate,
    build_itinerary_summary,
    build_reuse_fingerprint,
)

ITINERARY_RPC_FIELDS = frozenset(
    {
        "id",
        "session_id",
        "destination_id",
        "hotel_id",
        "start_date",
        "end_date",
        "duration_days",
        "number_of_adults",
        "number_of_children",
        "budget",
        "preferences",
        "day_themes",
        "planning_constraints",
        "status",
        "summary",
        "parent_itinerary_id",
        "reuse_root_id",
    }
)
ITEM_RPC_FIELDS = frozenset(
    {
        "id",
        "day_number",
        "order_index",
        "start_time",
        "end_time",
        "reference_type",
        "reference_id",
        "estimated_cost",
        "item_kind",
        "route_to_next",
        "route_from_hotel",
    }
)


logger = logging.getLogger(__name__)


class ItineraryStoreError(RuntimeError):
    """A recoverable persistence or retrieval failure."""


@dataclass(frozen=True)
class LoadedItineraryBundle:
    template: ItineraryTemplate
    hotel: Mapping[str, Any]


def _rows(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _first(value: object) -> dict[str, Any] | None:
    rows = _rows(value)
    return rows[0] if rows else None


class ItineraryStore:
    """Typed repository over the migration's itinerary RPC functions."""

    def __init__(self, client: Any, embed_query: Callable[[str], Sequence[float]]) -> None:
        self._client = client
        self._embed_query = embed_query

    @classmethod
    def from_default(cls) -> ItineraryStore:
        # Keep the high-impact hotel/attraction search contracts unchanged.
        from src.services.supabase_search import get_embeddings, get_supabase_client

        embeddings = get_embeddings()
        return cls(get_supabase_client(), embeddings.embed_query)

    def _embed(self, text: str) -> list[float]:
        vector = list(self._embed_query(text))
        if len(vector) != EMBEDDING_DIMENSION:
            raise ItineraryStoreError(
                f"Itinerary embedding dimension must be {EMBEDDING_DIMENSION}, got {len(vector)}."
            )
        return vector

    @staticmethod
    def _template(row: Mapping[str, Any], items: Sequence[Mapping[str, Any]] = ()) -> ItineraryTemplate:
        themes = row.get("day_themes") or []
        return ItineraryTemplate(
            id=str(row.get("id") or ""),
            destination_id=str(row.get("destination_id") or ""),
            hotel_id=str(row["hotel_id"]) if row.get("hotel_id") else None,
            duration_days=int(row.get("duration_days") or 0),
            number_of_adults=int(row.get("number_of_adults") or 1),
            number_of_children=int(row.get("number_of_children") or 0),
            preferences=tuple(str(value) for value in row.get("preferences") or []),
            day_themes=tuple(dict(theme) for theme in themes if isinstance(theme, Mapping)),
            items=tuple(dict(item) for item in items if isinstance(item, Mapping)),
            status=str(row.get("status") or ""),
            similarity=float(row.get("similarity") or 0.0),
            parent_itinerary_id=(
                str(row["parent_itinerary_id"]) if row.get("parent_itinerary_id") else None
            ),
            reuse_root_id=str(row["reuse_root_id"]) if row.get("reuse_root_id") else None,
            reuse_count=int(row.get("reuse_count") or 0),
            summary=str(row["summary"]) if row.get("summary") else None,
            planning_constraints=(
                dict(row.get("planning_constraints") or {})
                if isinstance(row.get("planning_constraints") or {}, Mapping)
                else {}
            ),
        )

    def search_reusable_itineraries(
        self,
        query: ItineraryReuseQuery,
        *,
        threshold: float,
        match_count: int = 5,
    ) -> list[ItineraryTemplate]:
        if not query.hotel_id:
            raise ItineraryStoreError("Itinerary reuse search requires a selected hotel_id.")
        fingerprint = build_reuse_fingerprint(query)
        vector = self._embed(fingerprint.summary)
        params = {
            "query_embedding": vector,
            "match_threshold": float(threshold),
            "match_count": max(1, min(int(match_count), 20)),
            "filter_destination_id": query.destination_id,
            "filter_duration_days": int(query.duration_days),
            "filter_hotel_id": query.hotel_id,
            "filter_planning_constraints": dict(query.planning_constraints),
        }
        try:
            response = self._client.rpc("match_itineraries", params).execute()
        except Exception as exc:  # Supabase/network failures must not block normal planning.
            raise ItineraryStoreError(f"Itinerary reuse search failed: {exc}") from exc
        return [self._template(row) for row in _rows(getattr(response, "data", None))]

    def load_itinerary_bundle(self, itinerary_id: str) -> LoadedItineraryBundle | None:
        try:
            itinerary_response = self._client.table("itineraries").select("*").eq("id", itinerary_id).execute()
            itinerary = _first(getattr(itinerary_response, "data", None))
            if not itinerary:
                return None
            item_response = (
                self._client.table("itinerary_items")
                .select("*")
                .eq("itinerary_id", itinerary_id)
                .order("day_number")
                .order("order_index")
                .execute()
            )
            items = _rows(getattr(item_response, "data", None))
            hotel_id = itinerary.get("hotel_id")
            hotel: dict[str, Any] = {}
            if hotel_id:
                hotel_response = self._client.table("hotels").select("*").eq("id", hotel_id).execute()
                hotel = _first(getattr(hotel_response, "data", None)) or {}
        except Exception as exc:
            raise ItineraryStoreError(f"Itinerary bundle load failed: {exc}") from exc
        return LoadedItineraryBundle(self._template(itinerary, items), hotel)

    def load_session_trip_data(self, itinerary_id: str) -> dict[str, Any] | None:
        """Hydrate the canonical itinerary rows into the active planner shape.

        A session checkpoint deliberately stores only the itinerary and hotel IDs.
        This keeps a restored planner editable after a process restart without
        duplicating a full trip plan in ``sessions.context_data``.
        """
        try:
            itinerary_response = self._client.table("itineraries").select("*").eq("id", itinerary_id).execute()
            itinerary = _first(getattr(itinerary_response, "data", None))
            if not itinerary:
                return None
            item_response = (
                self._client.table("itinerary_items")
                .select("*")
                .eq("itinerary_id", itinerary_id)
                .order("day_number")
                .order("order_index")
                .execute()
            )
            items = _rows(getattr(item_response, "data", None))
            hotel: dict[str, Any] = {}
            hotel_id = itinerary.get("hotel_id")
            if hotel_id:
                hotel_response = self._client.table("hotels").select("*").eq("id", hotel_id).execute()
                hotel = _first(getattr(hotel_response, "data", None)) or {}

            attraction_ids = [
                str(item["reference_id"])
                for item in items
                if str(item.get("reference_type") or "").casefold() == "attraction" and item.get("reference_id")
            ]
            attractions_by_id: dict[str, dict[str, Any]] = {}
            if attraction_ids:
                attraction_response = (
                    self._client.table("attractions")
                    .select("id,name,coordinates,images")
                    .in_("id", attraction_ids)
                    .execute()
                )
                attractions_by_id = {
                    str(row.get("id")): row for row in _rows(getattr(attraction_response, "data", None))
                }
        except Exception as exc:
            raise ItineraryStoreError(f"Session itinerary hydration failed: {exc}") from exc

        hydrated_items = []
        for item in items:
            hydrated = dict(item)
            if str(hydrated.get("reference_type") or "").casefold() == "hotel":
                hydrated.setdefault("activity", hotel.get("name") or "Hotel")
                hydrated.setdefault("image_url", hotel.get("image_url"))
                hydrated.setdefault("coordinates", hotel.get("coordinates"))
            else:
                attraction = attractions_by_id.get(str(hydrated.get("reference_id"))) or {}
                hydrated.setdefault("activity", attraction.get("name") or "")
                hydrated.setdefault("coordinates", attraction.get("coordinates"))
                images = attraction.get("images") or []
                if images and isinstance(images, list):
                    hydrated.setdefault("image_url", images[0])
            hydrated_items.append(hydrated)
        return {"hotel": hotel, "itineraries": [itinerary], "itinerary_items": hydrated_items}

    def load_session_trip_data_by_session(self, session_id: str) -> dict[str, Any] | None:
        """Durable fallback for a session whose LangGraph checkpoint is gone.

        `SessionRegistry.evict_expired()` (agents/session.py) deletes a
        session's checkpoint thread after `SESSION_TTL_SECONDS` (default 2h)
        idle -- the graph plane's ONLY copy of `trip_data` with the current
        (v3) schema. `itineraries.session_id` (`database_schema.sql`) has no
        TTL of its own, so the itinerary a guest already built survives that
        prune untouched; this just finds it and hands off to
        `load_session_trip_data`, the same hydration `session.py`'s legacy
        rehydration path already uses -- callers (routes.py's
        `restore_session`, turn_runner.py's `run_turn`) are the current-
        schema equivalent that path's own comment says was deliberately left
        without one ("nothing on the HTTP path reads and nothing keeps
        current" was true for `TripSession.state`, never for a pruned
        checkpoint with no state at all to disagree with).

        Picks the most recently updated itinerary for the session if more
        than one exists (e.g. a duplicated trip) -- returns None when the
        session genuinely never built one, same as `load_session_trip_data`
        does for an unknown id.
        """
        try:
            response = (
                self._client.table("itineraries")
                .select("id")
                .eq("session_id", session_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            row = _first(getattr(response, "data", None))
        except Exception as exc:
            raise ItineraryStoreError(f"Session itinerary lookup failed: {exc}") from exc
        if not row or not row.get("id"):
            return None
        return self.load_session_trip_data(str(row["id"]))

    def refresh_itinerary_image_urls(self, trip_data: dict[str, Any] | None) -> dict[str, Any] | None:
        """Overwrites each itinerary item's `image_url` with whatever
        `attractions.images[0]` / `hotels.image_url` says RIGHT NOW, without
        touching anything else in `trip_data`.

        `item.image_url` is baked in once, at generation time
        (`trip_scheduler.py`'s `PlaceCandidate.from_mapping`), and then never
        refreshed again for the practical lifetime of a session:
        `to_trip_plan_payload` (`trip_formatter.py`) is a pure pass-through of
        whatever `trip_data` already holds, and this checkpoint is only ever
        re-hydrated from scratch after 2h+ idle eviction
        (`load_session_trip_data_by_session`, above). Meanwhile
        `place_details.py`'s `GET /attractions/{id}` queries Supabase live on
        every open. If an attraction's `images` changes after the plan was
        generated (a later crawl re-run, or an admin edit), the itinerary
        keeps showing the old snapshot — sometimes a since-expired Google
        Photos link — while the detail panel shows the current one. This
        closes exactly that gap, for the two places a plan is served for
        DISPLAY (`routes.py`'s `restore_session`/`get_session_plan`) — never
        wired into the hot chat-turn path (`respond.py`, the `get_trip_plan`
        agent tool), where an extra DB round trip would buy nothing: neither
        renders a photo.

        Best-effort by design: any failure returns `trip_data` completely
        unchanged rather than raising, and a reference whose live row has no
        image keeps its existing (possibly still-usable) frozen value rather
        than being blanked. A cosmetic refresh must never be able to break
        loading the itinerary itself.
        """
        if not trip_data:
            return trip_data
        items = trip_data.get("itinerary_items")
        if not isinstance(items, list) or not items:
            return trip_data

        attraction_ids = {
            str(item["reference_id"])
            for item in items
            if isinstance(item, Mapping)
            and str(item.get("reference_type") or "").casefold() == "attraction"
            and item.get("reference_id")
        }
        hotel_ids = {
            str(item["reference_id"])
            for item in items
            if isinstance(item, Mapping)
            and str(item.get("reference_type") or "").casefold() == "hotel"
            and item.get("reference_id")
        }
        if not attraction_ids and not hotel_ids:
            return trip_data

        try:
            images_by_attraction: dict[str, Any] = {}
            if attraction_ids:
                response = (
                    self._client.table("attractions")
                    .select("id,images")
                    .in_("id", list(attraction_ids))
                    .execute()
                )
                images_by_attraction = {
                    str(row.get("id")): row.get("images") or []
                    for row in _rows(getattr(response, "data", None))
                }
            image_url_by_hotel: dict[str, Any] = {}
            if hotel_ids:
                response = (
                    self._client.table("hotels")
                    .select("id,image_url")
                    .in_("id", list(hotel_ids))
                    .execute()
                )
                image_url_by_hotel = {
                    str(row.get("id")): row.get("image_url")
                    for row in _rows(getattr(response, "data", None))
                }
        except Exception:
            logger.exception("Live image_url refresh failed; serving the frozen snapshot instead.")
            return trip_data

        refreshed_items = []
        for item in items:
            if not isinstance(item, Mapping):
                refreshed_items.append(item)
                continue
            reference_type = str(item.get("reference_type") or "").casefold()
            reference_id = str(item.get("reference_id") or "")
            refreshed = dict(item)
            if reference_type == "attraction":
                images = images_by_attraction.get(reference_id)
                if images and isinstance(images, list) and images[0]:
                    refreshed["image_url"] = images[0]
            elif reference_type == "hotel":
                live_url = image_url_by_hotel.get(reference_id)
                if live_url:
                    refreshed["image_url"] = live_url
            refreshed_items.append(refreshed)

        return {**trip_data, "itinerary_items": refreshed_items}

    @staticmethod
    def _itinerary_record(trip_data: Mapping[str, Any]) -> dict[str, Any]:
        itineraries = trip_data.get("itineraries") or []
        itinerary = itineraries[0] if isinstance(itineraries, list) and itineraries else itineraries
        if not isinstance(itinerary, Mapping) or not itinerary.get("id"):
            raise ItineraryStoreError("Trip data has no itinerary record to persist.")
        record = {key: value for key, value in itinerary.items() if key in ITINERARY_RPC_FIELDS}
        hotel = trip_data.get("hotel") or {}
        if isinstance(hotel, Mapping):
            record.setdefault("hotel_id", hotel.get("id"))
            record.setdefault("destination_id", hotel.get("destination_id"))
        if not record.get("destination_id") or not record.get("hotel_id"):
            raise ItineraryStoreError("A reusable itinerary requires destination_id and hotel_id.")
        return record

    def persist_itinerary_bundle(self, trip_data: Mapping[str, Any]) -> str:
        itinerary = self._itinerary_record(trip_data)
        routing_items = []
        for item in trip_data.get("itinerary_items") or []:
            if not isinstance(item, Mapping):
                continue
            row = dict(item)
            row["item_kind"] = row.get("item_kind") or row.get("kind")
            routing_items.append(row)

        # Recalculate routes using recalculate_itinerary_routes helper
        mutable_trip_data = dict(trip_data)
        mutable_trip_data["itinerary_items"] = routing_items
        from src.services.routing import recalculate_itinerary_routes
        recalculate_itinerary_routes(mutable_trip_data)

        # The chat response is built from ``trip_data`` immediately after this
        # persistence call. Propagate the calculated routes from the RPC-safe
        # copies so that response is not one request behind the stored plan.
        source_items = trip_data.get("itinerary_items") or []
        for source, routed in zip(source_items, routing_items):
            if not isinstance(source, dict):
                continue
            for field in ("route_from_hotel", "route_to_next"):
                if field in routed:
                    source[field] = routed[field]

        items = [
            {key: value for key, value in row.items() if key in ITEM_RPC_FIELDS}
            for row in routing_items
        ]

        try:
            response = self._client.rpc(
                "persist_itinerary_bundle",
                {"p_itinerary": itinerary, "p_items": items},
            ).execute()
            return str(getattr(response, "data", None) or itinerary["id"])
        except Exception as exc:
            raise ItineraryStoreError(
                "Unable to persist the atomic itinerary bundle; local JSON was retained. "
                f"Supabase RPC error: {exc}"
            ) from exc

    def finalize_trip_data(self, trip_data: Mapping[str, Any], query: ItineraryReuseQuery) -> Mapping[str, Any]:
        itinerary = self._itinerary_record(trip_data)
        summary = build_itinerary_summary(
            query,
            day_themes=itinerary.get("day_themes") or [],
            hotel=trip_data.get("hotel") or {},
            items=trip_data.get("itinerary_items") or [],
            budget=itinerary.get("budget"),
        )
        params = {
            "p_itinerary_id": itinerary["id"],
            "p_summary": summary,
        }
        # Same `persisting` key as trip_planner._persist_itinerary_metadata —
        # emitted right before the first external write of this call, and the
        # aligned Phase 4 point-of-no-return anchor.
        emit_phase("persisting")
        try:
            response = self._client.rpc("finalize_itinerary", params).execute()
            result = _first(getattr(response, "data", None)) or {}
        except Exception as exc:
            try:
                self._client.table("itineraries").update({"status": "Finalized", "summary": summary}).eq("id", itinerary["id"]).execute()
                result = {"status": "Finalized", "summary": summary}
            except Exception as fallback_exc:
                raise ItineraryStoreError(
                    f"Itinerary finalization failed: {exc} | Fallback failed: {fallback_exc}"
                ) from exc
        if result.get("status") == "already_finalized" and result.get("has_embedding"):
            return result
        try:
            vector = self._embed(summary)
            self._client.rpc(
                "update_itinerary_embedding",
                {
                    "p_itinerary_id": itinerary["id"],
                    "p_embedding": vector,
                },
            ).execute()
            return {**result, "embedding_saved": True, "summary": summary}
        except Exception as exc:
            # Preserve the finalized state; a NULL vector remains retryable.
            return {
                **result,
                "embedding_saved": False,
                "embedding_error": str(exc),
                "summary": summary,
            }

    def refresh_embedding(
        self,
        itinerary_id: str,
        summary: str,
    ) -> None:
        """Store a deterministic summary and refresh one already-finalized vector."""
        try:
            self._client.table("itineraries").update(
                {
                    "summary": summary,
                }
            ).eq("id", itinerary_id).execute()
            vector = self._embed(summary)
            self._client.rpc(
                "update_itinerary_embedding",
                {
                    "p_itinerary_id": itinerary_id,
                    "p_embedding": vector,
                },
            ).execute()
        except Exception as exc:
            raise ItineraryStoreError(f"Itinerary embedding refresh failed: {exc}") from exc


def push_current_trip_plan_to_supabase(
    file_path: str | Path = "current_trip_plan.json",
    *,
    store: ItineraryStore | None = None,
) -> str:
    """Load one saved terminal plan and atomically persist its full Supabase bundle.

    ``store`` is injectable for tests and alternate Supabase clients. Production
    callers can omit it to use the configured service-role client and embedding
    provider.
    """
    plan_path = Path(file_path)
    try:
        raw_plan = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ItineraryStoreError(f"Cannot read trip plan file '{plan_path}': {exc}") from exc

    try:
        trip_data = json.loads(raw_plan)
    except JSONDecodeError as exc:
        raise ItineraryStoreError(
            f"Trip plan file '{plan_path}' does not contain valid JSON: {exc}"
        ) from exc

    if not isinstance(trip_data, Mapping):
        raise ItineraryStoreError("Trip plan JSON must be an object.")
    items = trip_data.get("itinerary_items")
    if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
        raise ItineraryStoreError("Trip plan JSON must contain an itinerary_items list of objects.")

    itinerary_store = store or ItineraryStore.from_default()
    return itinerary_store.persist_itinerary_bundle(trip_data)
