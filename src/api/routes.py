from fastapi import APIRouter, HTTPException

from src.agents.graph import agent
from src.models.schemas import ChatRequest, ChatResponse, PlannerChatRequest, PlannerChatResponse
from src.services.chat_session import ChatSession, create_chat_session, process_chat_turn

router = APIRouter()

# In-memory session store for the basic web chat UI (GET /chat). Lost on
# server restart, and shared globally like current_trip_plan.json/
# pending_hotel_selection.json already are — a known "basic v1" limitation,
# not a new one; see docs/architecture/agent_workflow_and_semantic_search_stack.md.
_CHAT_SESSIONS: dict[str, ChatSession] = {}


@router.post("/planner_chat", response_model=PlannerChatResponse)
def planner_chat(request: PlannerChatRequest) -> PlannerChatResponse:
    """Chat với trip planner thật (khác với /chat — endpoint đó dùng agent mẫu riêng).

    A plain `def` (not `async def`) so FastAPI runs it in its worker thread pool —
    process_chat_turn calls synchronous LangChain `.invoke()`s that would otherwise
    block the event loop.
    """
    session = _CHAT_SESSIONS.get(request.session_id)
    if session is None:
        session = create_chat_session(request.session_id)
        _CHAT_SESSIONS[request.session_id] = session
    try:
        reply = process_chat_turn(session, request.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return PlannerChatResponse(reply=reply)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Chat với AI agent."""
    try:
        result = await agent.ainvoke({"query": request.message})
        return ChatResponse(
            response=result.get("response", ""),
            analysis=result.get("analysis", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
                search_results.append({
                    "id": str(a["id"]),
                    "score": float(a.get("similarity", 0.0)),
                    "name": a.get("name"),
                    "category": a.get("category"),
                })
        
        return {"status": "success", "results": search_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
                
                search_results.append({
                    "id": str(h["id"]),
                    "score": float(h.get("similarity", 0.0)),
                    "name": h.get("name"),
                    "star_rating": h.get("star_rating"),
                    "matched_rooms": matched_rooms_dict,
                    "matched_room_names": h.get("matched_room_names") or [],
                })
        
        return {"status": "success", "results": search_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
