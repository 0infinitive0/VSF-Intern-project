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
from datetime import UTC

from fastapi import APIRouter, HTTPException

from src.agents.session import (
    SessionRegistry,
    debug_persist_hook,
    derive_stage,
    process_chat_turn,
    suggestions_for,
)
from src.config import get_settings
from src.models.schemas import (
    IntakeStatus,
    PlannerChatRequest,
    PlannerChatResponse,
    sanitize_system_error,
    to_hotel_options_payload,
    to_trip_plan_payload,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level session registry (replaces bare _CHAT_SESSIONS dict)
# ---------------------------------------------------------------------------

_settings = get_settings()

_persist_hook = debug_persist_hook if _settings.debug_trip_plan_file else None

registry = SessionRegistry(
    ttl_seconds=_settings.session_ttl_seconds,
    cap=_settings.max_sessions,
    persist_hook=_persist_hook,
)


# ---------------------------------------------------------------------------
# Session lifecycle endpoints (Phase 3)
# ---------------------------------------------------------------------------


@router.post("/chat/session")
def create_session() -> dict:
    """Tạo một phiên chat mới và trả về session_id do server cấp.

    Đây là cách duy nhất để tạo session — planner_chat không còn tự tạo session
    nữa, để đảm bảo rằng một session_id chưa được cấp sẽ nhận 404.
    """
    session = registry.create()
    from datetime import datetime

    return {
        "session_id": session.session_id,
        "created_at": datetime.fromtimestamp(session.created_at, tz=UTC).isoformat(),
    }


@router.get("/chat/{session_id}/plan")
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


@router.post("/planner_chat", response_model=PlannerChatResponse)
def planner_chat(request: PlannerChatRequest) -> PlannerChatResponse:
    """Chat với trip planner thật.

    A plain `def` (not `async def`) so FastAPI runs it in its worker thread
    pool — process_chat_turn calls synchronous LangChain `.invoke()`s that
    would otherwise block the event loop.

    Phase 3 changes vs the Phase 2 handler:
    - session_id is now a UUID (RT-6); malformed ids get 422 from pydantic.
    - registry.get() → 404 for an unknown id; never auto-creates a session.
    - per-session lock serialises same-session concurrent requests.
    - evict_expired() runs before the lock, skipping locked sessions.
    - response fields (stage, hotel_options, trip_plan, intake) assembled once.
    - raw exception text never reaches the response body.
    """
    session_id = str(request.session_id)

    registry.evict_expired()
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")

    with session.lock:
        try:
            result = process_chat_turn(session, request.message)
            suggestions_raw = suggestions_for(session)
        except Exception:
            logger.exception("Unexpected error in planner_chat for session %s", session_id)
            raise HTTPException(status_code=500, detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")

    # Sanitize any SYSTEM ERROR: text that might carry internal detail before
    # it reaches the browser.
    safe_reply = sanitize_system_error(result.text, session_id=session_id)
    if safe_reply != result.text:
        logger.warning(
            "Sanitized SYSTEM ERROR reply for session %s (original logged at error level above)",
            session_id,
        )

    stage = derive_stage(result)

    # Build both hotel_options and suggestions from the SAME source so they
    # can never disagree on the pending list (asserted in tests).
    hotel_options = to_hotel_options_payload(session.pending_hotel_selection)
    suggestions = [{"label": s["label"], "value": s["value"]} for s in suggestions_raw]

    trip_plan = to_trip_plan_payload(session.trip_data)
    intake = IntakeStatus.from_state(session.intake_state)

    return PlannerChatResponse(
        session_id=session_id,
        reply=safe_reply,
        suggestions=suggestions,
        stage=stage,
        hotel_options=hotel_options,
        trip_plan=trip_plan,
        intake=intake,
    )



# ---------------------------------------------------------------------------
# Utility endpoints (unchanged)
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
