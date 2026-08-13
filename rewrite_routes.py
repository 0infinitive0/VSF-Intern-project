import re

with open("backend/src/api/routes.py", "r") as f:
    content = f.read()

# Replace legacy imports
content = re.sub(
    r'from src\.agents\.session import \([\s\S]*?\)\n',
    'from src.agents.session import (\n    SessionRegistry,\n    debug_persist_hook,\n    supabase_persist_hook,\n)\n',
    content
)

# Remove process_chat_turn related code
content = re.sub(r'def _prepare_turn_inputs[\s\S]*?def build_chat_response[\s\S]*?return response\n', '', content)

# Rewrite select_hotel
select_hotel_new = '''@router.post("/chat/select_hotel", response_model=PlannerChatResponse)
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
            return _run_turn_via_graph(session_id, message, session.language)
        except Exception as exc:
            logger.exception("Chat error for session %s", session_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
'''
content = re.sub(r'@router\.post\("/chat/select_hotel"[\s\S]*?(?=@router\.post\("/hotels/change")', select_hotel_new + '\n\n', content)

# Rewrite change_hotel
change_hotel_new = '''@router.post("/hotels/change", response_model=PlannerChatResponse)
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
'''
content = re.sub(r'@router\.post\("/hotels/change"[\s\S]*?(?=# ---------------------------------------------------------------------------)', change_hotel_new + '\n\n', content)

# Rewrite planner_chat
planner_chat_new = '''@router.post("/planner_chat", response_model=PlannerChatResponse)
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
'''
content = re.sub(r'@router\.post\("/planner_chat"[\s\S]*?(?=@router\.post\("/planner_chat/stream"\))', planner_chat_new + '\n\n', content)

# Rewrite planner_chat_stream
stream_new = '''@router.post("/planner_chat/stream")
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
            with session.lock:
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
'''
content = re.sub(r'@router\.post\("/planner_chat/stream"\)[\s\S]*?(?=# ---------------------------------------------------------------------------)', stream_new + '\n\n', content)


with open("backend/src/api/routes.py", "w") as f:
    f.write(content)
