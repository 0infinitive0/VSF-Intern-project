---
phase: 2
title: "Out-of-scope refusal guardrail"
status: done
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 2: Out-of-scope refusal guardrail

## Overview

Refuse requests outside travel planning — maths, coding, flight booking. Small, fully
independent of the rewrite. **Ship early alongside Phase 1.**

## Problem

No mechanism exists. `guardrails/jailbreak.py:56-69` blocks exactly four things: role
spoofing, prompt exfiltration, instruction override, jailbreak persona. Scope refusal is a
different control and is entirely absent.

Today an out-of-scope request falls through routing to `_run_chat_agent`, where a
general-purpose LLM answers it. `SUPERVISOR_PROMPT` never says "refuse out-of-scope" — its
rule 4 says the opposite: *"If the user asks general questions about travel advice, answer
them directly."* Nothing narrows "general questions".

Flight booking is the sharper risk: it is adjacent enough to travel that the model will
attempt to help, and the product has no flight data at all. A confident, fabricated answer
about flights is worse than a refusal.

## Requirements

- Functional: maths/homework and code-writing requests are declined with a short, non-preachy
  message that redirects to what the assistant does.
- Functional: flight booking/search requests are declined and explicitly state that flights
  are not covered — never fabricated.
- Functional: a refusal is one sentence plus the nearest useful offer. No lecturing.
- Functional: travel questions that merely *contain* numbers or a place name are **not**
  refused — "chia 3 triệu cho 3 ngày" is budget planning, not a maths request.
- Non-functional: defence in depth — a deterministic pre-filter plus a prompt clause, mirroring
  how `detect_jailbreak` is paired with prompt rules today.
- Non-functional: refusals are logged with their trigger so false positives are measurable.

## Architecture

New `backend/src/guardrails/scope.py`, sibling to `jailbreak.py` and reusing its shape
(`_normalize`, a `Decision` dataclass, regex families):

```python
@dataclass(frozen=True)
class ScopeDecision:
    out_of_scope: bool
    category: str | None = None      # "math" | "code" | "flight"
```

Wired at the same place as `detect_jailbreak` in `process_chat_turn` (`session.py:929-956`),
which already has the guard-mode setting (`block` / `log` / `off`) — reuse it rather than
inventing a second toggle, so scope refusal can be shadow-tested in `log` mode first.

Deterministic first pass only. Categories:

| Category | Signals |
|---|---|
| `math` | equation/solve verbs plus operator or "phương trình", "đạo hàm", "tích phân", "giải bài" |
| `code` | "viết code", "hàm python", "sql", "regex", "debug", fenced code in the message |
| `flight` | "vé máy bay", "chuyến bay", "đặt vé", airline names, airport codes |

**False-positive guard is the hard part.** Travel planning is full of arithmetic and of the
word "đặt" (đặt phòng vs đặt vé). The pre-filter must require a *non-travel* object:
`đặt phòng`/`đặt khách sạn` must never hit the `flight` family. Build the negative cases
into the test table first, then write the patterns to pass them.

Second layer: an explicit refusal clause in `SUPERVISOR_PROMPT` / `SUPERVISOR_PROMPT_EN`
narrowing rule 4's "general questions" to travel-related ones.

## Related Code Files

- Create: `backend/src/guardrails/scope.py`
- Create: `backend/tests/test_scope_guardrail.py`
- Modify: `backend/src/agents/session.py` — wire beside `detect_jailbreak` (:929-956)
- Modify: `backend/src/agents/prompts.py` — refusal clause in both supervisor prompts
- Modify: `backend/src/config.py` — reuse `jailbreak_guard_mode` or add a parallel scope mode

## Implementation Steps

1. Write the **negative** test table first: travel messages that must NOT be refused —
   "chia 3 triệu cho 3 ngày", "đặt phòng khách sạn", "tính tổng chi phí chuyến đi",
   "khách sạn gần sân bay", "bay từ Hà Nội vào rồi đi Đà Nẵng 3 ngày".
2. Write the positive table: "giải phương trình x^2+2x+1=0", "viết hàm python đọc file",
   "đặt vé máy bay đi Đà Nẵng", "chuyến bay VN123 mấy giờ".
3. Implement `detect_out_of_scope` to pass both tables.
4. Wire into `process_chat_turn` beside the jailbreak check, honoring guard mode.
5. Add refusal clauses to both supervisor prompts.
6. Ship in `log` mode first; review logged hits before switching to `block`.

## Success Criteria

- [ ] "giải phương trình x²+2x+1=0" is declined, not solved
- [ ] "viết cho tôi hàm python đọc file csv" is declined, not written
- [ ] "đặt vé máy bay đi Đà Nẵng" is declined and states flights are not covered
- [ ] "đặt phòng khách sạn Đà Nẵng" proceeds normally — **not** refused
- [ ] "chia 3 triệu cho 3 ngày" proceeds as budget planning — **not** refused
- [ ] "khách sạn gần sân bay" proceeds normally — **not** refused
- [ ] Every refusal is one sentence plus an offer, with no moralising
- [ ] Refusals are logged with category
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| False positives block real travel requests | Negative test table written **before** the patterns; ship in `log` mode and review real hits before blocking |
| "đặt vé" vs "đặt phòng" collision | Flight family requires a flight object (vé máy bay / chuyến bay / airline / airport code); a bare "đặt" never triggers |
| Regex-only classification is brittle | Deliberate: a deterministic pre-filter plus a prompt clause. An LLM classifier would add a call per turn for a rare case — revisit only if the log shows real misses |
| Refusal tone reads as preachy | One sentence + nearest offer, asserted by test on the message text |
