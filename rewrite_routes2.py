import re

with open("backend/src/api/routes.py", "r") as f:
    content = f.read()

restore_old = r'''@router\.get\("/chat/{session_id}/restore", response_model=SessionRestorePayload\)
def restore_session\(session_id: str\) -> SessionRestorePayload:
    session = registry\.get\(session_id\)
    if session is None:
        raise HTTPException\(status_code=404, detail="Session not found\."\)
    stage = derive_stage\(
        TurnResult\(text=str\(session\.state\.get\("reply"\) or ""\), tool=session\.state\.get\("tool_ran"\)\), session
    \)
    return SessionRestorePayload\(
        session_id=session\.session_id,
        messages=session_store\.restored_messages\(session\.state\.get\("messages"\)\),
        suggestions=suggestions_for\(session\),
        stage=stage,
        hotel_options=to_hotel_options_payload\(session\.pending_hotel_selection\),
        trip_plan=to_trip_plan_payload\(session\.trip_data\),
        intake=IntakeStatus\.from_state\(session\.intake_state, session\.hotel_pref_state\),
    \)'''

restore_new = '''@router.get("/chat/{session_id}/restore", response_model=SessionRestorePayload)
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
        trip_plan=to_trip_plan_payload(state.get("travel_state")),
        intake=IntakeStatus.from_state(None, None),
    )'''

content = re.sub(restore_old, restore_new, content)

plan_old = r'''@router\.get\("/chat/{session_id}/plan"\)
@router\.get\("/session/{session_id}/state"\)
def get_session_plan\(session_id: str\) -> dict:
    """Trả về kế hoạch chuyến đi hiện tại của một phiên, hoặc 404 nếu không có\."""
    session = registry\.get\(session_id\)
    if session is None:
        raise HTTPException\(status_code=404, detail="Phiên chat không tồn tại\."\)
    return \{"trip_plan": to_trip_plan_payload\(session\.trip_data\)\}'''

plan_new = '''@router.get("/chat/{session_id}/plan")
@router.get("/session/{session_id}/state")
def get_session_plan(session_id: str) -> dict:
    """Trả về kế hoạch chuyến đi hiện tại của một phiên, hoặc 404 nếu không có."""
    app = _get_graph_v2()
    snapshot = app.get_state({"configurable": {"thread_id": session_id}})
    state = snapshot.values
    if not state:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")
    return {"trip_plan": to_trip_plan_payload(state.get("travel_state"))}'''

content = re.sub(plan_old, plan_new, content)

with open("backend/src/api/routes.py", "w") as f:
    f.write(content)
