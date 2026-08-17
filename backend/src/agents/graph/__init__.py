"""The control plane: every chat turn runs through the graph built here.

Began life as a second plane alongside a legacy `process_chat_turn`
cascade, kept in its own package so the two could not entangle. That
cascade has since been deleted and the config switch that chose between
them removed, so this is now simply where a turn is handled.
"""

from __future__ import annotations
