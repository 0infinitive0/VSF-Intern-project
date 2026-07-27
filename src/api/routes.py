from fastapi import APIRouter, HTTPException

from src.agents.graph import agent
from src.models.schemas import ChatRequest, ChatResponse

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
    """Tìm kiếm semantic cho attractions."""
    try:
        from src.services.vector_store import get_vector_store
        vector_store = get_vector_store("attractions_vector")
        results = vector_store.similarity_search_with_score(q, k=k)
        
        # Return a list of dicts containing attraction_id and score
        search_results = []
        for doc, score in results:
            attraction_id = doc.metadata.get("attraction_id")
            if attraction_id:
                search_results.append({
                    "id": attraction_id,
                    "score": float(score)
                })
        
        return {"status": "success", "results": search_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/search_hotels")
async def search_hotels(q: str, k: int = 10):
    """Tìm kiếm semantic cho hotels và rooms."""
    try:
        from src.services.vector_store import get_vector_store
        
        hotel_store = get_vector_store("hotels_vector")
        room_store = get_vector_store("rooms_vector")
        
        hotel_results = hotel_store.similarity_search_with_score(q, k=k)
        room_results = room_store.similarity_search_with_score(q, k=k)
        
        hotel_scores = {}
        
        # Process hotel matches
        for doc, score in hotel_results:
            h_id = doc.metadata.get("hotel_id")
            if h_id:
                hotel_scores[h_id] = {
                    "id": h_id,
                    "score": float(score),
                    "matched_rooms": {}
                }
                
        # Process room matches
        for doc, score in room_results:
            h_id = doc.metadata.get("hotel_id")
            r_id = doc.metadata.get("room_id")
            
            if h_id and r_id:
                if h_id not in hotel_scores:
                    hotel_scores[h_id] = {
                        "id": h_id,
                        "score": float(score),
                        "matched_rooms": {}
                    }
                else:
                    # Update hotel score if room score is higher
                    hotel_scores[h_id]["score"] = max(hotel_scores[h_id]["score"], float(score))
                
                # Store the room score
                hotel_scores[h_id]["matched_rooms"][r_id] = float(score)

        # Convert to list and sort by score descending
        results_list = list(hotel_scores.values())
        results_list.sort(key=lambda x: x["score"], reverse=True)
        
        # Take top k hotels
        results_list = results_list[:k]
        
        return {"status": "success", "results": results_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
