"""Smoke test: does a real turn survive `LLM_USE_RESPONSES_API=true`?

Plan `260819-0931-responses-api-migration-opt-in-with-reasoning-summary` Phase 3.
One binary question, answered by running the SAME turns through the graph twice --
once per transport -- and comparing the results, not the timings.

Latency is deliberately NOT measured here. One run per cell says nothing about it,
and the cost/hop A/B that would need many runs is deferred (phase 3b).

**Turns run synchronously, in this thread, on purpose.** `usage_recorder` binds
through a `ContextVar`, so a call made via `ThreadPoolExecutor.submit` or
`loop.run_in_executor` records NOTHING and raises nothing -- and `routes.py`'s
streaming endpoint uses exactly `run_in_executor`. Driving this through HTTP would
report zero usage and look like a pass.

Usage:
    python backend/scripts/smoke_responses_api.py
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND.parent / "eval"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND / ".env", override=True)
os.environ.setdefault("LANGSMITH_TRACING", "false")

from harness.usage_recorder import record_usage  # noqa: E402

import src.api.routes as routes  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.api.streaming import emitting_to  # noqa: E402
from src.domain.travel_state import TravelState, apply_patch  # noqa: E402


class _RecordingEmitter:
    """Same `emit(event, **data)` surface as `TurnEmitter`, no event loop."""

    def __init__(self) -> None:
        self.frames: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, **data: Any) -> None:
        self.frames.append((event, data))

    def count(self, event: str) -> int:
        return sum(1 for name, _ in self.frames if name == event)

    @property
    def delta_text(self) -> str:
        return "".join(str(d.get("text", "")) for n, d in self.frames if n == "delta")


def _travel_state(*, complete: bool) -> dict:
    changes: list[dict[str, Any]] = [
        {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
        {"path": "people", "operation": "set", "value": 2},
    ]
    if complete:
        changes += [
            {"path": "dates.start", "operation": "set", "value": "2099-01-01"},
            {"path": "dates.end", "operation": "set", "value": "2099-01-05"},
            {"path": "budget.target", "operation": "set", "value": 5_000_000},
        ]
    return apply_patch(TravelState(), changes).state.to_dict()


#: (label, message, travel_state) -- one per node group the flag can reach.
TURNS = [
    ("intake  ", "Đà Nẵng tháng 7 thời tiết thế nào?", _travel_state(complete=False)),
    ("qa      ", "khách sạn ở Đà Nẵng có hồ bơi không?", _travel_state(complete=True)),
    ("edit    ", "đổi thành 3 người và tăng ngân sách lên 8 triệu", _travel_state(complete=True)),
]


def run_turn(tag: str, message: str, travel_state: dict, scope: str) -> dict[str, Any]:
    emitter = _RecordingEmitter()
    error = None
    result: Any = {}
    try:
        with record_usage(scope=scope) as rec:
            with emitting_to(emitter):  # type: ignore[arg-type]
                result = routes._run_turn_via_graph(
                    f"smoke-{scope}-{tag.strip()}",
                    message,
                    "vi",
                    extra_state={"travel_state": travel_state},
                    stream=True,
                )
        calls = rec.calls
    except Exception as exc:  # a crash IS the finding; record it, keep going
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc(limit=2)
        calls = []

    state = routes._get_graph_v2().get_state(
        {"configurable": {"thread_id": f"smoke-{scope}-{tag.strip()}"}}
    ).values or {}

    return {
        "error": error,
        "intent": state.get("intent"),
        "patch_len": len(state.get("patch") or []),
        "deltas": emitter.count("delta"),
        "delta_chars": len(emitter.delta_text),
        "phases": emitter.count("phase"),
        "reply_len": len(getattr(result, "reply", "") or ""),
        "llm_calls": len(calls),
        "calls_with_usage": sum(1 for c in calls if c.get("usage_metadata")),
        "calls_with_model": sum(1 for c in calls if c.get("model")),
    }


def main() -> int:
    routes._persistence_enabled = False
    rows: dict[str, dict[str, dict]] = {}

    for flag, scope in (("false", "off"), ("true", "on")):
        os.environ["LLM_USE_RESPONSES_API"] = flag
        get_settings.cache_clear()
        print(f"\n=== LLM_USE_RESPONSES_API={flag} ===")
        rows[scope] = {}
        for tag, message, travel_state in TURNS:
            row = run_turn(tag, message, travel_state, scope)
            rows[scope][tag] = row
            print(
                f"  {tag} err={row['error'] or '-'} intent={row['intent']!r} "
                f"patch={row['patch_len']} deltas={row['deltas']}({row['delta_chars']}c) "
                f"reply={row['reply_len']}c calls={row['llm_calls']} "
                f"usage={row['calls_with_usage']}/{row['llm_calls']} "
                f"model={row['calls_with_model']}/{row['llm_calls']}"
            )

    print("\n=== SO SÁNH ===")
    failures = []
    for tag, _, _ in TURNS:
        off, on = rows["off"][tag], rows["on"][tag]
        checks = {
            "không exception": on["error"] is None,
            "intent khớp": off["intent"] == on["intent"],
            "patch khớp": off["patch_len"] == on["patch_len"],
            "có reply": on["reply_len"] > 0,
            "usage đủ": on["llm_calls"] > 0 and on["calls_with_usage"] == on["llm_calls"],
            "model đủ": on["llm_calls"] > 0 and on["calls_with_model"] == on["llm_calls"],
        }
        # Deltas only exist for the two streaming nodes; assert parity, not presence.
        checks["delta parity"] = (off["deltas"] > 0) == (on["deltas"] > 0)
        bad = [name for name, ok in checks.items() if not ok]
        print(f"  {tag} {'PASS' if not bad else 'FAIL -> ' + ', '.join(bad)}")
        failures += [(tag, b) for b in bad]

    print("\nKẾT QUẢ:", "PASS" if not failures else f"FAIL ({len(failures)} kiểm tra)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
