import logging

from fastapi import APIRouter, HTTPException

from src.agents.graph import agent
from src.models.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter()


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
    """Tìm kiếm semantic cho hotels qua Qdrant (Phase 5): kết quả gộp theo
    canonical_hotel_key — một khách sạn vật lý trùng trên nhiều OTA trả về
    một kết quả duy nhất với nhiều `offers`, thay vì lặp lại."""
    try:
        from src.services.hotel_search import search_hotels as _search_hotels_service

        results = _search_hotels_service(q, k=k)

        search_results = []
        for result in results:
            search_results.append({
                # `id`/`score`: dashboard (src/airflow/dashboard/templates/index.html)
                # cross-references these against /api/locations by id. `id` is
                # None until Phase 4's Supabase load has run for this hotel
                # (sync_to_supabase on) — the dashboard's join then simply
                # finds no matching location, which is a silent no-match, not
                # a crash.
                "id": result.get("id"),
                "score": result.get("score"),
                "canonical_hotel_key": result.get("canonical_hotel_key"),
                "name": result.get("display_name"),
                "offers": result.get("offers") or [],
                "grounding_facts": result.get("grounding_facts") or {},
            })

        return {"status": "success", "results": search_results}
    except Exception:
        # Unlike /search_attractions above, this path can surface Qdrant
        # connection details in the exception text — log it, return a
        # generic detail instead of str(e).
        logger.exception("search_hotels failed for query %r", q)
        raise HTTPException(status_code=500, detail="Hotel search failed")
