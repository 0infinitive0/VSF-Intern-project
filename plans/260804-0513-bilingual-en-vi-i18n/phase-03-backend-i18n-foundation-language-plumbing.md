---
phase: 3
title: "Backend i18n Foundation & Language Plumbing"
status: pending
priority: P1
effort: "1d"
dependencies: [2]
---

# Phase 3: Backend i18n Foundation & Language Plumbing

## Overview

Build the backend translation mechanism (`gettext` + Babel catalogs, matching
the ecosystem-standard Python i18n lib the same way `react-i18next` is the
frontend's) and thread a `language` value from the HTTP request through
`TripSession`/`TripState` so Phase 4 has something to read. This phase adds
the plumbing and a `t()` helper; it does NOT translate any backend message
yet.

## Requirements

- Functional: `PlannerChatRequest.language` (optional, `"vi"` default) is
  accepted by `POST /api/v1/planner_chat` and stored on the session, so a
  message sent with `language="en"` is retrievable as `session.state["language"]`
  inside `process_chat_turn` and downstream.
- Functional: `t(key, language, **kwargs)` returns the `vi` catalog value
  when given `"vi"` or an unrecognized language, and the `en` value for
  `"en"` — mirroring `fallbackLng: 'vi'` on the frontend.
- Non-functional: zero behavior change yet — no caller of `t()` exists until
  Phase 4, so this phase must not alter any existing reply text.

## Architecture

### Library choice

Python's stdlib `gettext` module (paired with the `Babel` PyPI package for
the `pybabel extract/init/update/compile` CLI tooling) — the direct Python
analogue of what `react-i18next`/`i18next` is for JS: a compiled catalog per
locale (`.po` source, `.mo` compiled), looked up by message id at runtime.
This avoids inventing a bespoke dict-based catalog format and gives real
tooling (`pybabel extract` scans source for `_()`/`gettext()` calls and
regenerates the `.pot` template) once messages are marked in Phase 4.

`gettext.translation(...).install()` is **not** used — it mutates a global/
thread-shared translator, which is wrong for a server handling concurrent
requests in different languages. Instead, obtain a fresh bound `gettext`
callable per request from a small in-process cache keyed by language (`.mo`
files are tiny; loading is cheap, but caching avoids reparsing every call).

```
src/i18n/
  __init__.py      # t(key, language, **kwargs) — the only import surface
  catalog.py        # translation() cache + gettext binding
locales/
  en/LC_MESSAGES/messages.po   # (Phase 4 populates real msgid/msgstr pairs)
  en/LC_MESSAGES/messages.mo   # compiled, committed alongside .po
  vi/LC_MESSAGES/messages.po
  vi/LC_MESSAGES/messages.mo
babel.cfg          # pybabel extraction config (scans src/ for _() calls)
```

`src/i18n/catalog.py`:

```python
"""Per-language gettext translators, cached by language code.

Not gettext.install() — that mutates a process-global translator, which is
wrong for a server handling concurrent requests in different languages.
Each call to t() looks up (or lazily builds) a NullTranslations-falling-back
translator bound to one language.
"""
import gettext
from functools import lru_cache
from pathlib import Path

_LOCALE_DIR = Path(__file__).resolve().parent.parent.parent / "locales"
_DOMAIN = "messages"
SUPPORTED_LANGUAGES = ("vi", "en")
DEFAULT_LANGUAGE = "vi"

@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _translator(language: str) -> gettext.NullTranslations:
    try:
        return gettext.translation(
            _DOMAIN, localedir=str(_LOCALE_DIR), languages=[language]
        )
    except FileNotFoundError:
        return gettext.NullTranslations()  # returns msgid unchanged

def t(key: str, language: str | None, **kwargs: object) -> str:
    lang = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    translated = _translator(lang).gettext(key)
    return translated.format(**kwargs) if kwargs else translated
```

Vietnamese is the **source language** (the existing hardcoded strings ARE the
`msgid`s — no separate `vi.po` translation is strictly required if `msgid ==`
the Vietnamese text and `NullTranslations` returns the key unchanged). To
keep both languages structurally symmetric and future-proof (so a `msgid`
could later be a short English-ish key instead of full Vietnamese text), this
plan still generates a `vi/LC_MESSAGES/messages.po` with identity
`msgstr` == `msgid`, compiled to `.mo`, rather than relying on
`NullTranslations` fallback — this makes `DEFAULT_LANGUAGE` behave
identically whether or not the `.mo` file is present, and keeps `pybabel`'s
workflow (`extract` → `init`/`update` both locales → `compile`) uniform
across languages instead of special-casing Vietnamese.

### Language plumbing

`src/models/schemas.py:203-208` (`PlannerChatRequest`):
```python
class PlannerChatRequest(BaseModel):
    session_id: UUID = Field(...)
    message: str = Field(..., min_length=1, max_length=5000)
    language: Literal["vi", "en"] = Field("vi", description="UI language for this turn's reply")
```

`src/agents/state.py` (`TripState`): add `language: str` to the TypedDict;
`initial_state()` sets `language="vi"`.

`src/api/routes.py`'s `planner_chat()` handler: before calling
`process_chat_turn`, write the request's language onto the session state:
```python
session.state["language"] = request.language
```
placed right after `registry.get(session_id)` succeeds, inside the
`with session.lock:` block, before `process_chat_turn(session, request.message)`
is called (`src/api/routes.py:119-121`). This makes language a per-turn value
(a user can toggle mid-conversation and the next message picks it up) rather
than fixed at session creation — matches the confirmed "manual toggle,
default Vietnamese" UX without needing a new endpoint.

### Dynamic LLM prompt wiring (plumbing only — Phase 4 writes the actual EN prompt text)

`src/agents/graph.py:89-95` changes `prompt=SUPERVISOR_PROMPT` (a static
string) to `prompt=_dynamic_supervisor_prompt` (a callable). Per LangGraph
1.2.9's prebuilt `create_react_agent`, `prompt` accepts a function of the
graph state returning a message list:

```python
from langchain.messages import SystemMessage

def _dynamic_supervisor_prompt(state: TripState) -> list:
    language = state.get("language", "vi")
    system_text = SUPERVISOR_PROMPT_EN if language == "en" else SUPERVISOR_PROMPT_VI
    return [SystemMessage(system_text)] + state["messages"]
```

This phase renames `SUPERVISOR_PROMPT` → `SUPERVISOR_PROMPT_VI` in
`src/agents/prompts.py` (content unchanged) and adds a `SUPERVISOR_PROMPT_EN`
**placeholder** (can be a rough draft; Phase 4 owns getting the actual prompt
text right) so `graph.py` compiles against both names. Wiring
`build_trip_agent` to the callable happens in this phase; writing the final
English prompt copy is Phase 4's job — keeping "plumbing" and "content"
separate phases means a prompt wording review doesn't block the mechanical
wiring review.

## Related Code Files

- Create: `src/i18n/__init__.py`
- Create: `src/i18n/catalog.py`
- Create: `babel.cfg`
- Create: `locales/en/LC_MESSAGES/messages.po` (empty/near-empty scaffold; Phase 4 populates)
- Create: `locales/vi/LC_MESSAGES/messages.po` (empty/near-empty scaffold; Phase 4 populates)
- Modify: `src/models/schemas.py` (`PlannerChatRequest.language`)
- Modify: `src/agents/state.py` (`TripState.language`, `initial_state()`)
- Modify: `src/api/routes.py` (write `session.state["language"]` per turn)
- Modify: `src/agents/graph.py` (callable `prompt=`)
- Modify: `src/agents/prompts.py` (rename + EN placeholder)
- Modify: `requirements.txt` (add `Babel`)

## Implementation Steps

1. Add `Babel` to `requirements.txt`.
2. Create `babel.cfg`:
   ```
   [python: src/**.py]
   ```
3. Create `locales/` directory structure; run
   `pybabel extract -F babel.cfg -o locales/messages.pot src/` (will be
   near-empty until Phase 4 marks strings with `_()`/`t()` calls — acceptable
   for this phase, re-run in Phase 4) then
   `pybabel init -i locales/messages.pot -d locales -l en` and `-l vi`,
   `pybabel compile -d locales`.
4. Write `src/i18n/catalog.py` and `src/i18n/__init__.py`
   (`from src.i18n.catalog import t, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE`).
5. Add `language: Literal["vi", "en"] = "vi"` to `PlannerChatRequest`.
6. Add `language: str` to `TripState`; set `language="vi"` in `initial_state()`.
7. In `src/api/routes.py`'s `planner_chat()`, set
   `session.state["language"] = request.language` before `process_chat_turn`.
8. Rename `SUPERVISOR_PROMPT` → `SUPERVISOR_PROMPT_VI` in `prompts.py`
   (content unchanged); add a placeholder `SUPERVISOR_PROMPT_EN` (can literally
   be `SUPERVISOR_PROMPT_VI` copied for now, with a `# TODO(Phase 4)` comment
   — Phase 4 replaces it with real English wording).
9. Update `src/agents/graph.py`: add `_dynamic_supervisor_prompt`, pass it as
   `prompt=` to `create_react_agent`, remove the now-unused static import.
10. Run the existing test suite (`pytest`) — must be 100% green with zero
    changes, since `language` defaults to `"vi"` everywhere and
    `SUPERVISOR_PROMPT_VI`'s content is unchanged.

## Success Criteria

- [ ] `from src.i18n import t; t("Bạn muốn đi đâu?", "vi")` returns the input
      string unchanged (identity passthrough via the vi catalog).
- [ ] `PlannerChatRequest(session_id=..., message="hi")` still validates with
      no `language` field supplied (defaults to `"vi"`).
- [ ] Full existing `pytest` suite passes with no test file changes.
- [ ] `session.state["language"]` reflects the last `planner_chat` request's
      `language` field (add one new integration test for this in this phase,
      since it's genuinely new plumbing with no prior coverage).

## Risk Assessment

- **Risk:** `create_react_agent`'s callable-`prompt` signature/behavior
  differs subtly from what's documented for the pinned LangGraph version
  (1.2.9, confirmed via Context7 docs at plan time, but prebuilt-agent APIs
  do shift across minor versions). **Mitigation:** step 9 includes running
  the full existing test suite immediately after the swap — any signature
  mismatch surfaces as an import/runtime error, not a silent behavior change,
  since `SUPERVISOR_PROMPT_VI` content is byte-identical to before.
- **Risk:** per-language `lru_cache`d `gettext.translation()` object is not
  thread-safe if `gettext.NullTranslations.gettext()` itself mutates shared
  state. **Mitigation:** `gettext.gettext()` lookups are read-only dict
  access after the catalog is loaded; this is the standard multi-locale
  server pattern (Django/Flask-Babel use the same approach) and safe under
  FastAPI's thread-pool execution model (`planner_chat` already runs as a
  plain `def`, per `src/api/routes.py`'s own docstring, precisely because
  blocking calls run in a worker thread pool — no async/thread-safety
  surprises specific to this addition).
- **Risk:** adding `Babel` as a new backend dependency needs a maintainer
  decision if the project pins dependencies tightly. **Mitigation:** flag in
  PR description; `Babel` is a small, stable, widely-used package with no
  heavy transitive dependencies.
