"""API route handlers for the trip planner.

Phase 3 changes:
- One module-level SessionRegistry replaces the bare _CHAT_SESSIONS dict.
- planner_chat: registry.get() + 404 (never auto-creates); per-session lock;
  sanitised errors; one-place PlannerChatResponse assembly from TurnResult.
- Three new endpoints: POST /chat/session, GET /chat/{session_id}/plan,
  DELETE /chat/{session_id}.
- All handlers are plain `def` (not async def) so FastAPI runs them in the
  worker thread pool — Supabase/Ollama calls are blocking and must not stall
  the event loop. The one exception is POST /planner_chat/stream: it is
  `async def` (required to yield SSE frames) but runs the blocking turn in
  the worker pool via run_in_executor, so the rule above still holds.
"""

import asyncio
import logging
from datetime import UTC, date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from src.agents.session import (
    SessionRegistry,
    debug_persist_hook,
    supabase_persist_hook,
)
from src.api.streaming import STREAM_HEADERS, TurnEmitter, emit_phase, emitting_to, sse_stream
from src.config import get_settings
from src.models.schemas import (
    AttractionDetailPayload,
    ChangeHotelRequest,
    HotelDetailPayload,
    IntakeStatus,
    PlannerChatRequest,
    PlannerChatResponse,
    SessionListPayload,
    SessionRestorePayload,
    SessionSummaryPayload,
    SelectHotelRequest,
    SelectPlaceRequest,
    sanitize_system_error,
    to_hotel_options_payload,
    to_trip_plan_payload,
)
from src.services import session_store
from src.services.place_details import get_attraction_detail, get_hotel_detail

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level session registry (replaces bare _CHAT_SESSIONS dict)
# ---------------------------------------------------------------------------

_settings = get_settings()

_persistence_enabled = _settings.session_persistence_enabled
_persist_hook = (
    supabase_persist_hook
    if _persistence_enabled
    else debug_persist_hook if _settings.debug_trip_plan_file else None
)

registry = SessionRegistry(
    ttl_seconds=_settings.session_ttl_seconds,
    cap=_settings.max_sessions,
    persist_hook=_persist_hook,
    load_hook=session_store.load if _persistence_enabled else None,
    delete_hook=session_store.delete if _persistence_enabled else None,
)
# `registry.set_checkpointer(...)` is called from src/main.py's lifespan --
# this module is imported (and `registry` constructed) before the lifespan
# runs, so the app-wide LangGraph checkpointer cannot be threaded through
# __init__ above.


# ---------------------------------------------------------------------------
# Sessionless detail endpoints (Phase 3)
# ---------------------------------------------------------------------------


@router.get("/hotels/{hotel_id}", response_model=HotelDetailPayload)
def hotel_detail(
    hotel_id: UUID, check_in: date | None = None, check_out: date | None = None
) -> HotelDetailPayload:
    if (check_in is None) != (check_out is None) or (
        check_in is not None and check_out is not None and check_out <= check_in
    ):
        raise HTTPException(status_code=422, detail="check_in and check_out must form a valid stay.")
    try:
        detail = get_hotel_detail(str(hotel_id), check_in, check_out)
    except Exception:
        logger.exception("hotel_detail lookup failed for %s", hotel_id)
        raise HTTPException(status_code=500, detail="Unable to retrieve hotel detail.")
    if detail is None:
        raise HTTPException(status_code=404, detail="Hotel not found.")
    return HotelDetailPayload.model_validate(detail)


@router.get("/attractions/{attraction_id}", response_model=AttractionDetailPayload)
def attraction_detail(attraction_id: UUID) -> AttractionDetailPayload:
    try:
        detail = get_attraction_detail(str(attraction_id))
    except Exception:
        logger.exception("attraction_detail lookup failed for %s", attraction_id)
        raise HTTPException(status_code=500, detail="Unable to retrieve attraction detail.")
    if detail is None:
        raise HTTPException(status_code=404, detail="Attraction not found.")
    return AttractionDetailPayload.model_validate(detail)


# ---------------------------------------------------------------------------
# Session lifecycle endpoints (Phase 3)
# ---------------------------------------------------------------------------


@router.post("/chat/session")
def create_session() -> dict:
    """Tạo một phiên chat mới và trả về session_id do server cấp.

    Persists immediately (not just after the first turn) so the session shows
    up as its own row in the history rail right away — otherwise every
    never-chatted draft looked identical to any other and clicking
    "+ Chuyến đi mới" repeatedly appeared to do nothing."""
    session = registry.create()
    if session.persist_hook:
        session.persist_hook(session)
    from datetime import datetime

    return {
        "session_id": session.session_id,
        "created_at": datetime.fromtimestamp(session.created_at, tz=UTC).isoformat(),
    }


@router.get("/chat/sessions", response_model=SessionListPayload)
def list_persisted_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> SessionListPayload:
    if not _persistence_enabled:
        return SessionListPayload(sessions=[], page=page, page_size=page_size, has_more=False)
    try:
        persisted = session_store.list_sessions(page=page, page_size=page_size)
        return SessionListPayload(
            sessions=[SessionSummaryPayload.model_validate(session_store.summarize(row)) for row in persisted.rows],
            page=persisted.page,
            page_size=persisted.page_size,
            has_more=persisted.has_more,
        )
    except Exception:
        logger.exception("Unable to list persisted sessions")
        raise HTTPException(status_code=500, detail="Unable to retrieve session history.")


@router.get("/chat/{session_id}/restore", response_model=SessionRestorePayload)
def restore_session(session_id: str) -> SessionRestorePayload:
    app = _get_graph_v2()
    snapshot = app.get_state({"configurable": {"thread_id": session_id}})
    state = snapshot.values
    if not state:
        raise HTTPException(status_code=404, detail="Session not found.")
    
    return SessionRestorePayload(
        session_id=session_id,
        messages=[],
        suggestions=[],
        stage="intake",
        hotel_options=to_hotel_options_payload(state.get("hotel_options")),
        trip_plan=to_trip_plan_payload(state.get("trip_data")),
        intake=IntakeStatus.from_state(None, None),
    )


@router.get("/chat/{session_id}/plan")
@router.get("/session/{session_id}/state")
def get_session_plan(session_id: str) -> dict:
    """Trả về kế hoạch chuyến đi hiện tại của một phiên, hoặc 404 nếu không có."""
    app = _get_graph_v2()
    snapshot = app.get_state({"configurable": {"thread_id": session_id}})
    state = snapshot.values
    if not state:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")
    return {"trip_plan": to_trip_plan_payload(state.get("trip_data"))}


@router.delete("/chat/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    """Xóa một phiên chat. Trả về 204 dù phiên có tồn tại hay không."""
    registry.drop(session_id)


# ---------------------------------------------------------------------------
# Main chat endpoint (hardened in Phase 3)
# ---------------------------------------------------------------------------


def _prepare_turn_inputs(session, request: PlannerChatRequest) -> tuple[str, str] | None:
    """Apply the optional price-preference override and derive the stay_dates
    tuple. Shared by planner_chat and planner_chat_stream so the two endpoints
    cannot drift apart."""
    if request.min_price is not None or request.max_price is not None:
        from src.services.hotel_selection import HotelPreferenceState

        session.hotel_pref_state = HotelPreferenceState(
            stage="done",
            min_price=request.min_price,
            max_price=request.max_price,
            target_price=request.max_price or request.min_price,
        )

    return (
        (request.stay_dates.start_date.isoformat(), request.stay_dates.end_date.isoformat())
        if request.stay_dates is not None
        else None
    )


@router.post("/chat/select_hotel", response_model=PlannerChatResponse)
@router.post("/hotels/select", response_model=PlannerChatResponse)
def select_hotel(request: SelectHotelRequest) -> PlannerChatResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    with session.lock:
        try:
            message = f"Tôi chọn khách sạn ID {request.hotel_id}"
            # `selected_hotel_id` is the deterministic signal `hotel_node`
            # acts on (review finding F2) -- the message text above stays
            # for the conversation transcript/audit trail only.
            return _run_turn_via_graph(
                session_id, message, session.language, extra_state={"selected_hotel_id": str(request.hotel_id)}
            )
        except Exception as exc:
            logger.exception("Chat error for session %s", session_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/select_place", response_model=PlannerChatResponse)
@router.post("/places/select", response_model=PlannerChatResponse)
def select_place(request: SelectPlaceRequest) -> PlannerChatResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    with session.lock:
        try:
            message = f"Tôi chọn địa điểm ID {request.place_id}"
            return _run_turn_via_graph(session_id, message, session.language)
        except Exception as exc:
            logger.exception("Chat error for session %s", session_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/hotels/change", response_model=PlannerChatResponse)
def change_hotel(request: ChangeHotelRequest) -> PlannerChatResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    with session.lock:
        try:
            return _run_turn_via_graph(session_id, "đổi khách sạn", session.language)
        except Exception as exc:
            logger.exception("Hotel-change error for session %s", session_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Graph dispatch — how every chat endpoint handles a turn, never touching
# TripSession.state. There is no alternative plane and no setting selecting
# one: the legacy process_chat_turn cascade is gone. Compiled once, lazily,
# so the app-lifespan checkpointer (set on `registry` after this module is
# imported) is captured at first use rather than at import time.
# ---------------------------------------------------------------------------

_graph_v2_app = None


def _get_graph_v2():
    global _graph_v2_app
    if _graph_v2_app is None:
        from src.agents.graph.graph import build_graph

        checkpointer = registry.checkpointer
        if checkpointer is None:
            logger.warning(
                "graph_v2 compiling with a process-local MemorySaver: no app-lifespan checkpointer was "
                "set on `registry` yet (checkpointer_backend != 'postgres', or called before lifespan "
                "startup). Graph state will not survive a process restart until this is re-compiled "
                "with a real checkpointer."
            )
        _graph_v2_app = build_graph(checkpointer=checkpointer)
    return _graph_v2_app


def _invoke_fresh_turn(
    app, config: dict, session_id: str, message: str, language: str, extra_state: dict | None = None
) -> dict:
    return app.invoke(
        {
            "session_id": session_id,
            "language": language,
            "messages": [HumanMessage(content=message)],
            **(extra_state or {}),
        },
        config=config,
    )


def _run_turn_via_graph(
    session_id: str, message: str, language: str, extra_state: dict | None = None
) -> PlannerChatResponse:
    """Phase 7: a thread can be PAUSED at `interrupt()` (an ambiguous date --
    see `nodes/validate_patch.py`) from the previous turn. `get_state(...)
    .interrupts` is non-empty exactly then, and this turn's message must
    resume that paused node via `Command(resume=...)` rather than start a
    fresh turn -- which would re-run the pipeline from `load_context` and
    re-ask every slot already answered. A turn that itself pauses returns
    with `"__interrupt__"` in the result instead of `"response"` (`respond`
    never runs -- the graph stopped at `validate_patch`), so this builds the
    frozen response shape directly from the interrupt's own message.

    A resume reply that does NOT resolve the paused ambiguity (the user
    answered something else entirely, e.g. "thôi đổi điểm đến sang Huế"
    instead of naming a year) comes back with `unresolved_resume_text` set
    (see `nodes/validate_patch.py`) -- that text never reached
    `extract_patch` this turn (resuming re-executes only `validate_patch`,
    not the whole pipeline), so it is re-run here as one ordinary fresh
    turn. This is the fix for "a pending question isn't interruptible by a
    different intent" recreated one level down, inside the interrupt itself.

    `extra_state` (review finding F2) merges extra keys into this turn's
    `invoke()` input -- e.g. `selected_hotel_id` from `POST /hotels/select`,
    read deterministically by `hotel_node` rather than re-parsed out of the
    message text. Only applied on the fresh-turn path: a turn that resumes a
    paused `interrupt()` must resolve that ambiguity first, and threading a
    hotel pick through a resume is an edge case rare enough not to bother.

    `emit_phase("received")` (no-op on the plain POST path -- see
    `emit_phase`'s own no-emitter-bound guard) fires before anything else
    below: no graph_v2 node emits a `phase`/`delta` frame during an
    intake-stage turn (`extract_patch`'s LLM call is the graph's only slow
    step, and it is silent), so the client's `firstFrameTimeoutMs` (5s,
    `stream-client.ts`) previously had nothing to see but the filtered-out
    `: open` comment frame until `final` -- aborting the connection
    ("BodyStreamBuffer was aborted") on any turn whose extraction call ran
    past 5s, e.g. a compound "destination + dates + people + budget" message.
    """
    emit_phase("received")
    app = _get_graph_v2()
    config = {"configurable": {"thread_id": session_id}}

    snapshot = app.get_state(config)
    if snapshot.interrupts:
        result = app.invoke(Command(resume=message), config=config)
        unresolved = result.get("unresolved_resume_text")
        if unresolved and "__interrupt__" not in result:
            result = _invoke_fresh_turn(app, config, session_id, unresolved, language, extra_state)
    else:
        result = _invoke_fresh_turn(app, config, session_id, message, language, extra_state)

    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value or {}
        return PlannerChatResponse(session_id=session_id, reply=str(payload.get("message", "")), stage="intake")

    return PlannerChatResponse(**result["response"])


@router.post("/planner_chat", response_model=PlannerChatResponse)
@router.post("/chat", response_model=PlannerChatResponse)
def planner_chat(request: PlannerChatRequest) -> PlannerChatResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    with session.lock:
        try:
            return _run_turn_via_graph(session_id, request.message or "", request.language)
        except Exception:
            logger.exception("Unexpected error in planner_chat for session %s", session_id)
            raise HTTPException(status_code=500, detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")


@router.post("/planner_chat/stream")
async def planner_chat_stream(request: PlannerChatRequest) -> StreamingResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    loop = asyncio.get_running_loop()
    emitter = TurnEmitter(loop)

    def _run_turn() -> None:
        try:
            with emitting_to(emitter), session.lock:
                response = _run_turn_via_graph(session_id, request.message or "", request.language)
            emitter.emit("final", **response.model_dump(mode="json"))
        except Exception:
            logger.exception("Unexpected error in planner_chat_stream for session %s", session_id)
            emitter.emit("error", detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")
        finally:
            emitter.close()

    loop.run_in_executor(None, _run_turn)

    return StreamingResponse(
        sse_stream(emitter),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def agent_status():
    """Kiểm tra trạng thái agent."""
    return {"status": "ready", "agent": "LangGraph Agent v1.0"}


@router.get("/search_attractions")
async def search_attractions(q: str, k: int = 10):
    """Tìm kiếm semantic cho attractions sử dụng Supabase RPC."""
    try:
        from src.services.supabase_search import search_attractions as rpc_search_attractions

        results = rpc_search_attractions(q, match_count=k)

        search_results = []
        for a in results:
            if a.get("id"):
                search_results.append(
                    {
                        "id": str(a["id"]),
                        "score": float(a.get("similarity", 0.0)),
                        "name": a.get("name"),
                        "category": a.get("category"),
                    }
                )

        return {"status": "success", "results": search_results}
    except Exception:
        logger.exception("search_attractions error")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")


@router.get("/search_hotels")
async def search_hotels(q: str, k: int = 10):
    """Tìm kiếm semantic cho hotels và rooms sử dụng Supabase RPC."""
    try:
        from src.services.supabase_search import search_hotels_with_rooms

        results = search_hotels_with_rooms(q, match_count=k)

        search_results = []
        for h in results:
            if h.get("id"):
                matched_rooms_dict = {}
                for idx, r_name in enumerate(h.get("matched_room_names") or []):
                    matched_rooms_dict[f"room_{idx}"] = r_name

                search_results.append(
                    {
                        "id": str(h["id"]),
                        "score": float(h.get("similarity", 0.0)),
                        "name": h.get("name"),
                        "star_rating": h.get("star_rating"),
                        "matched_rooms": matched_rooms_dict,
                        "matched_room_names": h.get("matched_room_names") or [],
                    }
                )

        return {"status": "success", "results": search_results}
    except Exception:
        logger.exception("search_hotels error")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")


from pydantic import BaseModel


class LoadMoreHotelsRequest(BaseModel):
    session_id: str
    load_more: bool

@router.post("/hotels/search")
def hotels_search(request: LoadMoreHotelsRequest):
    session_id = str(request.session_id)
    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    with session.lock:
        try:
            from src.services.hotel_selection import select_hotel_candidates

            existing = session.pending_hotel_selection.get("options", []) if session.pending_hotel_selection else []
            exclude_ids = [opt["id"] for opt in existing if "id" in opt]

            dest_id = session.pending_hotel_selection.get("destination_id") if session.pending_hotel_selection else None
            print(f"DEBUG: pending_hotel_selection destination_id = {dest_id}")
            if not dest_id:
                from src.services.trip_planner import _get_destination_id
                dest_id = _get_destination_id(session.intake_state.destination)
                print(f"DEBUG: _get_destination_id({session.intake_state.destination}) = {dest_id}")

            final_dest_id = str(dest_id) if dest_id else ""
            print(f"DEBUG: calling select_hotel_candidates with destination_id = {final_dest_id}")

            results = select_hotel_candidates(
                destination=session.intake_state.destination or "",
                destination_id=final_dest_id,
                people=session.intake_state.people or "2",
                hotel_query=",".join(session.intake_state.preferences) if session.intake_state.preferences else None,
                match_count=5,
                max_price=session.hotel_pref_state.target_price,
                start_date=session.intake_state.start_date,
                end_date=session.intake_state.end_date,
                exclude_hotel_ids=exclude_ids
            )
            results = [item[0] for item in results]

            # Identify which hotels we already have
            existing = session.pending_hotel_selection.get("options", []) if session.pending_hotel_selection else []
            existing_names = {h.get("name") for h in existing if isinstance(h, dict)}

            new_hotels = []
            for r in results:
                if r.get("name") not in existing_names:
                    new_hotels.append(r)
                if len(new_hotels) == 5:
                    break

            if not session.pending_hotel_selection:
                session.pending_hotel_selection = {"options": []}

            start_idx = len(existing) + 1
            added_hotels = []
            for i, h in enumerate(new_hotels):
                # Ensure it's a dict and append
                hotel_dict = dict(h)
                hotel_dict["index"] = start_idx + i
                session.pending_hotel_selection["options"].append(hotel_dict)
                added_hotels.append(hotel_dict)

            return {
                "hotels": added_hotels,
                "has_more": len(results) >= 10
            }
        except Exception:
            logger.exception("Error in hotels_search")
            raise HTTPException(status_code=500, detail="Error fetching more hotels")

@router.post("/itineraries/generate")
def itineraries_generate(request: PlannerChatRequest):
    session_id = str(request.session_id)
    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    with session.lock:
        if session.trip_data and session.trip_data.get("itineraries"):
            # Already generated during select_hotel
            trip_plan = to_trip_plan_payload(session.trip_data)
            return {"status": "success", "trip_plan": trip_plan}

        try:
            from src.agents.session import process_chat_turn
            result = process_chat_turn(session, "Tạo lịch trình", language=request.language)
            trip_plan = to_trip_plan_payload(session.trip_data)
            return {"status": "success", "trip_plan": trip_plan}
        except Exception:
            logger.exception("Error generating itinerary")
            raise HTTPException(status_code=500, detail="Error generating itinerary")

