"""The `orchestrator=graph` control plane (Phase 5,
260812-0927-langgraph-orchestration-state-patch-and-interrupts).

A separate package from `src/agents/graph.py` so the legacy plane stays
untouched and deletion in Phase 11 is a directory removal, not surgery.
`orchestrator=legacy` (the default) never imports anything under here.
"""

from __future__ import annotations
