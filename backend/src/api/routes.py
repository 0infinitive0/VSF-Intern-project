"""API route handlers for the trip planner.

Phase 3 changes:
- One module-level SessionRegistry replaces the bare _CHAT_SESSIONS dict.
- planner_chat: registry.get() + 404 (never auto-creates); per-session lock;
  sanitised errors; one-place PlannerChatResponse assembly from TurnResult.
- Three new endpoints: POST /chat/session, GET /chat/{session_id}/plan,
  DELETE /chat/{session_id}.
- All handlers are plain `def` (not async def) so FastAPI runs them in the
  worker thread pool — Supabase/Ollama calls are blocking and must not stall
  the event loop.
"""

import logging
from datetime import UTC, date
from uuid import UUID

from fastapi import APIRouter, HTTPException

from src.agents.session import (
    SessionRegistry,
    TurnResult,
    debug_persist_hook,
    derive_stage,
    process_chat_turn,
    supabase_persist_hook,
    suggestions_for,
)
from src.config import get_settings
from src.models.schemas import (
    AttractionDetailPayload,
    HotelDetailPayload,
    IntakeStatus,
    PlannerChatRequest,
    PlannerChatResponse,
    SessionRestorePayload,
    SessionSummaryPayload,
    SelectHotelRequest,
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
    """Tạo một phiên chat mới và trả về session_id do server cấp."""
    session = registry.create()
    from datetime import datetime

    return {
        "session_id": session.session_id,
        "created_at": datetime.fromtimestamp(session.created_at, tz=UTC).isoformat(),
    }


@router.get("/chat/sessions", response_model=list[SessionSummaryPayload])
def list_persisted_sessions() -> list[SessionSummaryPayload]:
    if not _persistence_enabled:
        return []
    try:
        return [SessionSummaryPayload.model_validate(session_store.summarize(row)) for row in session_store.list_sessions()]
    except Exception:
        logger.exception("Unable to list persisted sessions")
        raise HTTPException(status_code=500, detail="Unable to retrieve session history.")


@router.get("/chat/{session_id}/restore", response_model=SessionRestorePayload)
def restore_session(session_id: str) -> SessionRestorePayload:
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    context = session_store.serialize(session)
    stage = derive_stage(
        TurnResult(text=str(session.state.get("reply") or ""), tool=session.state.get("tool_ran")), session
    )
    return SessionRestorePayload(
        session_id=session.session_id,
        messages=session_store.restored_messages(context),
        suggestions=suggestions_for(session),
        stage=stage,
        hotel_options=to_hotel_options_payload(session.pending_hotel_selection),
        trip_plan=to_trip_plan_payload(session.trip_data),
        intake=IntakeStatus.from_state(session.intake_state, session.hotel_pref_state),
    )


@router.get("/chat/{session_id}/plan")
@router.get("/session/{session_id}/state")
def get_session_plan(session_id: str) -> dict:
    """Trả về kế hoạch chuyến đi hiện tại của một phiên, hoặc 404 nếu không có."""
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")
    return {"trip_plan": to_trip_plan_payload(session.trip_data)}


@router.delete("/chat/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    """Xóa một phiên chat. Trả về 204 dù phiên có tồn tại hay không."""
    registry.drop(session_id)


# ---------------------------------------------------------------------------
# Main chat endpoint (hardened in Phase 3)
# ---------------------------------------------------------------------------



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
            from src.agents.session import handle_frontend_hotel_selection, derive_stage, suggestions_for
            
            result = handle_frontend_hotel_selection(session, str(request.hotel_id))
            
            safe_reply = sanitize_system_error(result.text, session_id=session_id)
            suggestions = suggestions_for(session)
            hotel_options = to_hotel_options_payload(session.pending_hotel_selection)
            trip_plan = to_trip_plan_payload(session.trip_data)
            intake = IntakeStatus.from_state(session.intake_state, session.hotel_pref_state)
            
            requires_stay_dates = bool(
                session.intake_state.destination
                and session.intake_state.people
                and session.hotel_pref_state.is_complete
                and not session.intake_state.has_explicit_stay_dates
            )

            return PlannerChatResponse(
                session_id=session_id,
                reply=safe_reply,
                suggestions=suggestions,
                stage=derive_stage(result, session),
                hotel_options=hotel_options,
                trip_plan=trip_plan,
                intake=intake,
                requires_stay_dates=requires_stay_dates,
                compound_min_price=session.pending_hotel_selection.get("compound_min_price") if session.pending_hotel_selection else None,
                compound_max_price=session.pending_hotel_selection.get("compound_max_price") if session.pending_hotel_selection else None,
                all_preferences=session.pending_hotel_selection.get("all_preferences") or [] if session.pending_hotel_selection else [],
                active_preferences=session.pending_hotel_selection.get("active_preferences") or [] if session.pending_hotel_selection else [],
            )
        except Exception as exc:
            logger.exception("Chat error for session %s", session_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/planner_chat", response_model=PlannerChatResponse)
@router.post("/chat", response_model=PlannerChatResponse)
def planner_chat(request: PlannerChatRequest) -> PlannerChatResponse:
    """Chat với trip planner thật."""
    session_id = str(request.session_id)

    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    with session.lock:
        try:
            if request.min_price is not None or request.max_price is not None:
                from src.services.hotel_selection import HotelPreferenceState
                session.hotel_pref_state = HotelPreferenceState(
                    stage="done",
                    min_price=request.min_price,
                    max_price=request.max_price,
                    target_price=request.max_price or request.min_price,
                )

            stay_dates = (
                (request.stay_dates.start_date.isoformat(), request.stay_dates.end_date.isoformat())
                if request.stay_dates is not None
                else None
            )
            result = process_chat_turn(
                session,
                request.message or "",
                stay_dates=stay_dates,
                language=request.language,
            )
            suggestions_raw = suggestions_for(session)
        except Exception:
            logger.exception("Unexpected error in planner_chat for session %s", session_id)
            raise HTTPException(status_code=500, detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")

    # Sanitize any SYSTEM ERROR: text that might carry internal detail before
    # it reaches the browser. sanitize_system_error() logs the original at
    # error level (keyed by session_id) whenever it replaces the text.
    safe_reply = sanitize_system_error(result.text, session_id=session_id, language=request.language)

    stage = derive_stage(result, session)

    hotel_options = to_hotel_options_payload(session.pending_hotel_selection)
    suggestions = [{"label": s["label"], "value": s["value"]} for s in suggestions_raw]

    trip_plan = to_trip_plan_payload(session.trip_data)
    intake = IntakeStatus.from_state(session.intake_state, session.hotel_pref_state)
    requires_stay_dates = bool(
        session.intake_state.destination
        and session.intake_state.people
        and session.hotel_pref_state.is_complete
        and not session.intake_state.has_explicit_stay_dates
    )

    return PlannerChatResponse(
        session_id=session_id,
        reply=safe_reply,
        suggestions=suggestions,
        stage=stage,
        hotel_options=hotel_options,
        trip_plan=trip_plan,
        intake=intake,
        requires_stay_dates=requires_stay_dates,
        compound_min_price=session.pending_hotel_selection.get("compound_min_price") if session.pending_hotel_selection else None,
        compound_max_price=session.pending_hotel_selection.get("compound_max_price") if session.pending_hotel_selection else None,
        all_preferences=session.pending_hotel_selection.get("all_preferences") or [] if session.pending_hotel_selection else [],
        active_preferences=session.pending_hotel_selection.get("active_preferences") or [] if session.pending_hotel_selection else [],
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
            from src.models.schemas import to_hotel_options_payload
            
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
        except Exception as exc:
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
        except Exception as exc:
            logger.exception("Error generating itinerary")
            raise HTTPException(status_code=500, detail="Error generating itinerary")

