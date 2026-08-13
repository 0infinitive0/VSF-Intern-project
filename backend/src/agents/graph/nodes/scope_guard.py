"""`scope_guard` — jailbreak guard (real) + out-of-scope refusal (stub).

Two distinct controls live at this one node, and only one of them is
actually shipped:

- `guardrails/jailbreak.py`'s `detect_jailbreak` is real, wired-in legacy
  infra (`session.py:935-955`, gated by `JAILBREAK_GUARD_MODE`). The graph
  plane must honor the same operator-facing setting, or flipping
  `orchestrator=graph` silently drops a control every other turn respects —
  found during this phase's code review, not a stub deferred to a later
  phase.
- Phase 2's out-of-scope refusal (`guardrails/scope.py`, math/code/flight
  requests) was never actually built despite its plan doc being marked
  done — confirmed by scanning the repo during this phase's cook session.
  The user chose to leave *that* control as a pass-through here rather than
  fold Phase 2's work into Phase 5. Replace this function with a real call
  to `guardrails/scope.py` once Phase 2 ships; the node/edge shape will not
  need to change.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.graph.state import TravelGraphState
from src.config import get_settings
from src.guardrails.jailbreak import detect_jailbreak

logger = logging.getLogger(__name__)

_BLOCKED_REPLY_VI = (
    "Mình có thể hỗ trợ lên kế hoạch chuyến đi, nhưng không thể làm theo "
    "yêu cầu ghi đè hoặc tiết lộ hướng dẫn hệ thống."
)
_BLOCKED_REPLY_EN = (
    "I can help plan your trip, but I can't follow requests to override or reveal system instructions."
)


def _last_user_message(state: TravelGraphState) -> str:
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) == "human":
            return str(getattr(message, "content", "") or "")
    return ""


def scope_guard(state: TravelGraphState) -> dict[str, Any]:
    guard_mode = getattr(get_settings(), "jailbreak_guard_mode", "block")
    if guard_mode == "off":
        return {}

    decision = detect_jailbreak(_last_user_message(state))
    if not decision.blocked:
        return {}

    logger.warning("Blocked jailbreak input reason=%s (orchestrator=graph)", decision.reason)
    if guard_mode == "log":
        return {}

    reply = _BLOCKED_REPLY_EN if state.get("language") == "en" else _BLOCKED_REPLY_VI
    return {
        "jailbreak_blocked": True,
        "task_results": [
            *(state.get("task_results") or []),
            {"worker": "scope_guard", "status": "blocked", "reply": reply},
        ],
    }
