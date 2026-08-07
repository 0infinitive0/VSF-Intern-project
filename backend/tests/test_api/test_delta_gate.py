"""test_delta_gate.py — Phase 3 (plan 260806-1602-streaming-chat-messages).

Unit tests for `_DeltaGate` in isolation: the incremental prefix check that
decides, as early as each new character makes it conclusive, whether ANY
delta is ever emitted for an attempt. This is the fix for Bẫy 1 (textual
tool-call JSON) / Bẫy 2 ("SYSTEM ERROR:" prefix) from phase-03 — both
`_looks_like_textual_tool_call` and `sanitize_system_error` key off the same
prefix, but only once the full text is known, too late for a live stream.
No FastAPI app, no session, no LLM.
"""

from __future__ import annotations

import asyncio

import pytest

from src.api.streaming import TurnEmitter, _DeltaGate, emitting_to


class _Capture:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event: str, **data) -> None:
        self.events.append((event, data))

    def deltas(self) -> list[str]:
        return [d["text"] for e, d in self.events if e == "delta"]

    def keys(self) -> list[str]:
        return [d["key"] for e, d in self.events if e == "phase"]


def _feed_all(gate: _DeltaGate, chunks: list[str]) -> None:
    for c in chunks:
        gate.feed(c)
    gate.close()


class TestCleanProseStreams:
    def test_first_character_decides_and_flushes_the_whole_chunk_immediately(self):
        """A first real character that is neither `{`/`[` nor `S` opens the
        gate right there — no wait for any minimum length."""
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, ["Đây là một câu trả lời đầy đủ và dài."])
        assert "".join(cap.deltas()) == "Đây là một câu trả lời đầy đủ và dài."
        assert gate.flushed_any

    def test_many_small_chunks_reassemble_exactly(self):
        text = "Khách sạn này có bãi đỗ xe miễn phí cho khách lưu trú."
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, list(text))  # one character at a time
        assert "".join(cap.deltas()) == text

    def test_each_feed_call_flushes_immediately_once_gate_is_open_no_batching(self):
        """Per-token streaming: once the gate has decided to stream, every
        feed() call must produce its OWN delta frame right away — never held
        back to accumulate a bigger batch first."""
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            gate.feed("Đây là một câu trả lời đầy đủ để mở gate. ")  # opens the gate
            gate.feed("Một")
            gate.feed(" từ")
            gate.feed(" nữa")
            gate.close()
        deltas = cap.deltas()
        # The three post-open feeds must appear as three SEPARATE frames —
        # never merged into one, however short each is.
        assert deltas[-3:] == ["Một", " từ", " nữa"]

    def test_single_char_diverging_from_system_error_opens_on_that_char(self):
        """A first real character of "S" is ambiguous (could start "SYSTEM
        ERROR:") so the gate must wait — but the INSTANT the second character
        rules that out, it must decide immediately, not wait for any fixed
        length. "Sunny" diverges at char 2 ("u" != "Y")."""
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            gate.feed("S")
            assert cap.deltas() == []  # still ambiguous after 1 char
            gate.feed("unny beach getaway awaits!")
            gate.close()
        assert "".join(cap.deltas()) == "Sunny beach getaway awaits!"

    def test_generating_phase_emitted_once_before_first_delta(self):
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, ["Xin chào, đây là phản hồi của trợ lý."])
        assert cap.events[0] == ("phase", {"key": "generating", "at": cap.events[0][1]["at"]})
        assert cap.events[1][0] == "delta"
        # Only once even across many small flush cycles.
        gate2 = _DeltaGate()
        cap2 = _Capture()
        with emitting_to(cap2):
            _feed_all(gate2, ["a" * 20, "b" * 20, "c" * 20])
        assert cap2.keys().count("generating") == 1


class TestGateMutesToolCallJson:
    def test_leading_brace_never_emits_a_delta(self):
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, ['{"name": "recommend_hotels", "arguments": {}}'])
        assert cap.deltas() == []
        assert not gate.flushed_any

    def test_leading_bracket_never_emits_a_delta(self):
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, ['[{"name": "x"}]'])
        assert cap.deltas() == []

    def test_system_error_prefix_never_emits_a_delta(self):
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, ["SYSTEM ERROR: Mô hình hội thoại không thể xử lý yêu cầu này."])
        assert cap.deltas() == []

    def test_muted_across_many_small_feeds_before_probe_threshold(self):
        """The gate must not leak a partial JSON prefix even when fed in
        pieces smaller than PROBE_CHARS."""
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            for c in '{"name": "recommend_hotels"}':
                gate.feed(c)
            gate.close()
        assert cap.deltas() == []

    def test_leading_whitespace_run_reaching_probe_length_does_not_leak_json(self):
        """A pure-whitespace first chunk that reaches PROBE_CHARS in raw
        length must NOT count as "enough content to decide" — deciding on
        zero real characters would default the gate open, and a JSON chunk
        fed right after would then stream straight through unchecked."""
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            gate.feed(" " * 20)
            gate.feed('{"name": "recommend_hotels", "arguments": {"x": 1}}')
            gate.close()
        assert cap.deltas() == []

    def test_chunk_boundary_splitting_system_error_prefix_does_not_leak(self):
        """A chunk boundary landing exactly at PROBE_CHARS raw chars, right
        after "SYSTEM ERROR" but before its colon, must not lock in a
        premature "looks like prose" decision."""
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            gate.feed("\n\n\n\n")  # 4 raw chars, 0 real content
            gate.feed("SYSTEM ERROR")  # buffer now 16 raw chars, no colon yet
            gate.feed(": Supabase dsn=postgres://user:pw@host/db")
            gate.close()
        assert cap.deltas() == []

    def test_gate_stays_muted_across_further_feeds_after_deciding(self):
        gate = _DeltaGate()
        cap = _Capture()
        with emitting_to(cap):
            gate.feed('{"name": "x", "arguments": {}}')  # decides muted
            gate.feed("more text that would otherwise look like prose")
            gate.close()
        assert cap.deltas() == []


class TestShortReplies:
    def test_short_clean_reply_still_flushes_at_close(self):
        """A reply shorter than PROBE_CHARS ("Có.") never crosses the
        length threshold in feed() — close() must still decide and flush it."""
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, ["Có."])
        assert cap.deltas() == ["Có."]

    def test_short_tool_call_looking_reply_still_muted_at_close(self):
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, ["{}"])
        assert cap.deltas() == []


class TestLeadingWhitespace:
    def test_leading_whitespace_is_stripped_before_the_prefix_check(self):
        cap = _Capture()
        with emitting_to(cap):
            gate = _DeltaGate()
            _feed_all(gate, ['   {"name": "x", "arguments": {}}'])
        assert cap.deltas() == []


class TestNoEmitterBound:
    def test_feed_only_accumulates_without_emitting_when_unbound(self):
        """Plain POST turn: no emitting_to() wrapper, no TurnEmitter bound —
        feed() must not raise, and no emission is observable (nothing to
        assert against but the absence of an exception)."""
        gate = _DeltaGate()
        _feed_all(gate, ["Xin chào, đây là một câu trả lời."])


@pytest.mark.asyncio
async def test_real_turn_emitter_roundtrip():
    """Smoke test against the real TurnEmitter (not the _Capture test double)
    — confirms the gate emits through the actual asyncio.Queue-backed emitter
    used in production. TurnEmitter.emit() schedules delivery via
    loop.call_soon_threadsafe onto the loop it was built with, so this must
    run in an async test bound to that same running loop."""
    emitter = TurnEmitter(asyncio.get_running_loop())
    with emitting_to(emitter):
        gate = _DeltaGate()
        gate.feed("Một câu trả lời đầy đủ, không phải JSON.")
        gate.close()
    emitter.close()

    events: list[str] = []
    for _ in range(10):
        item = await emitter.get(timeout=0.1)
        if item is None:
            continue
        if not hasattr(item, "event"):  # _SENTINEL marks end-of-stream
            break
        events.append(item.event)
    assert events == ["phase", "delta"]
