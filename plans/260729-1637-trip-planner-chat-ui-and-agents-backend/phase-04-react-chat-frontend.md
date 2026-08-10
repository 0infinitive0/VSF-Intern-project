---
phase: 4
title: "React chat frontend"
status: pending
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 4: React chat frontend

## Overview

A Vite + React chat app in `frontend/`: one conversation column, clickable hotel option
cards, and an itinerary panel rendering the structured `trip_plan`. Built against the
frozen contract and a mock server, so it runs in parallel with Phase 3.

Deliberately **not** the three-panel comp in `docs/design/v-ota-chat-ui/` — that remains
the master roadmap's phase-05. This is the simple version, borrowing only the design
tokens.

> The server-rendered `GET /chat` page shipped upstream and is the interim UI. D4 was
> reconfirmed 2026-07-30: React still happens; the Jinja page is retired in Phase 5.
> **Read `src/templates/chat.html` before starting** — it is a working reference client
> for the same contract, including how it renders `suggestions[]` chips and how it
> generates its `session_id`. Reuse its behaviour where it is already right.

## Requirements

- Functional: send a message, see the reply, keep history on screen.
- Functional: `session_id` obtained from `POST /chat/session`, kept in `sessionStorage`,
  sent every turn.
- Functional: `suggestions[]` render as tappable chips on every turn that returns them —
  this is the shipped contract and covers the guided hotel-preference questions, not
  only the hotel list.
- Functional: `stage="hotel_options"` additionally renders clickable hotel cards;
  clicking sends that option's `index` as the next message (D7).
- Functional: while in flight — disabled composer, spinner, live elapsed-seconds counter
  (D3; a plan build takes 30-60s).
- Functional: itinerary panel renders `trip_plan.days` as a timeline, with hotel summary
  and `adjustments`; empty state before the first plan.
- Functional: `stage="error"` renders as an in-thread error bubble, not a crash.
- Functional: "Tạo lại từ đầu" → `DELETE /chat/{sid}`, clear the thread, create a new session.
- Non-functional: works at 360px and desktop; no horizontal scroll.
- Non-functional: all user-facing strings in one module, ready for i18n.

## Architecture

```
frontend/
├── package.json
├── vite.config.js          # dev proxy /api -> http://localhost:8000
├── index.html
├── .env.example            # VITE_API_BASE=/api/v1
├── mock/server.js          # contract mock for parallel development
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── strings.js          # every VI string — the i18n seam
    ├── styles.css          # design tokens from DESIGN.md
    ├── api/chat-client.js  # createSession, sendMessage, getPlan, resetSession
    ├── hooks/use-chat-session.js
    └── components/
        ├── chat-panel.jsx
        ├── message-list.jsx
        ├── message-bubble.jsx
        ├── suggestion-chips.jsx    # renders suggestions[] on any turn
        ├── hotel-option-card.jsx   # the D7 pick step
        ├── composer.jsx
        ├── elapsed-spinner.jsx
        ├── itinerary-panel.jsx
        └── day-card.jsx
```

**Stack: plain JavaScript + JSX, plain CSS.** No TypeScript, no CSS Modules, no UI
library, no state manager. The app is one `useReducer` in `use-chat-session.js`.
`design_proposal.md` calls for CSS Modules — deviating for a single-column app; the CSS
is small enough that phase-05's rewrite can adopt them freely.

**Chips and cards are two views of one contract.** `suggestions[]` is server-declared
and already ships; it exists precisely because a UI that scans the reply text for lines
like "1. ..." cannot tell a real menu from the model's own prose — the model writes
numbered lists constantly, and those became chips that sent a bare "1" into a turn
expecting free text. That failure is documented in `suggestions_for`'s docstring.

So: **never infer options from reply text.** Render `suggestions[]` when present. When
`stage === "hotel_options"`, render `hotel_options[]` as richer cards *instead of* the
plain chips for that turn — same ordinals, more detail. Both post
`String(index)` / `suggestion.value` as an ordinary `message`; no new backend verb.
Keep the composer enabled throughout: typing a hotel name still works, and the backend
handles both.

**Design tokens** from `docs/design/v-ota-chat-ui/DESIGN.md`: primary `#00342b`,
secondary `#fed65b`, as CSS custom properties. Do **not** copy `design.html` — it pulls
Tailwind CDN, Google Fonts and remote placeholder images, all recorded there as caveats.

**Dev proxy over CORS.** `vite.config.js` proxies `/api` to `localhost:8000`, so the
browser sees one origin. `VITE_API_BASE` allows pointing at a remote backend.

**Mock server.** ~60 lines of `node:http` replaying fixtures for the four endpoints,
including the guided-preference turns, the `hotel_options` turn, and a deliberate 3s
delay on the plan turn so spinner and disabled states get exercised. This is why Phase 4
does not wait on Phase 3.

**State shape:**

```js
{ sessionId, messages: [{id, role, text, stage}], suggestions, hotelOptions, tripPlan,
  pending, elapsedMs, error }
```

## Related Code Files

- Create: everything under `frontend/` (tree above)
- Read only: `docs/chat_api_contract.md` (Phase 1),
  `docs/design/v-ota-chat-ui/DESIGN.md`,
  `src/templates/chat.html` (working reference client),
  `src/services/…/suggestions_for` docstring (why chips are server-declared)
- Modify: `.gitignore` — add `frontend/node_modules/`, `frontend/dist/`

## Implementation Steps

1. Read `src/templates/chat.html` end to end. Record: how it creates and stores
   `session_id`, how it renders `suggestions[]`, and how it handles a `SYSTEM ERROR:`
   reply. Anything it already gets right is the default here.
2. `npm create vite@latest frontend -- --template react`; strip the demo assets.
3. Add the dev proxy to `vite.config.js` and `.env.example`.
4. Write `src/strings.js` first — every label, placeholder, empty state and error string
   as a flat export. Nothing hardcodes a string in JSX afterwards. This is the cheap seam
   that turns BR-10's bilingual retrofit into a translation task rather than a codebase
   sweep.
5. Port the design tokens into `styles.css`, with light/dark pairs.
6. Build `api/chat-client.js` — it owns fetch, JSON parsing and error normalization. No
   component calls `fetch` directly.
7. Build `hooks/use-chat-session.js` — one reducer, the `POST /chat/session` bootstrap,
   the `sessionStorage` round-trip, and the elapsed-timer interval cleared in a `finally`.
   Handle a 404 from a stale stored `session_id` by creating a fresh session, not by
   erroring — the server restarts and loses all sessions (D1).
8. Build the message components. `message-bubble.jsx` renders the backend's
   pre-formatted text with preserved line breaks — the server already formats
   itineraries; the client does not re-parse them.
9. Build `suggestion-chips.jsx` from `suggestions[]`, posting `suggestion.value`.
10. Build `hotel-option-card.jsx` and wire the click → `sendMessage(String(index))`.
    Render cards in place of chips when `stage === "hotel_options"`.
11. Build `itinerary-panel.jsx` from `trip_plan.days` — one `day-card.jsx` per day with
    theme heading and a time → activity list; hotel summary above, adjustments below.
12. Write `mock/server.js` with fixtures captured from a real CLI or `GET /chat` run, and
    an `npm run mock` script.
13. Verify against the mock: intake question → guided preference chips → hotel options →
    card click → plan → modify → finalize, plus error, stale-session and reset paths.
    Re-verify against the real backend once Phase 3 lands.

## Success Criteria

- [ ] `npm run dev` + `npm run mock` completes the full flow with no console errors
- [ ] `suggestions[]` chips render on the guided preference turns, not only the hotel list
- [ ] Hotel cards render at `stage="hotel_options"`; clicking one advances to a plan
- [ ] No component derives options by parsing reply text — options come only from
      `suggestions[]` or `hotel_options[]`
- [ ] Typing a hotel name instead of clicking still works
- [ ] Composer disabled and spinner counting while pending; re-enabled on failure
- [ ] `sessionStorage` survives a refresh; a 404 on a stale id silently starts a new session
- [ ] Itinerary panel shows every day with theme, times and activities
- [ ] `stage="error"` shows an inline error bubble; the app stays usable
- [ ] No horizontal scroll at 360px
- [ ] No hardcoded VI copy in components, enforced by an **ESLint rule**
      (`eslint-plugin-i18next`'s `no-literal-string` or equivalent), not a grep.
      A `grep "\"[A-ZÀ-Ỹ]"` misses single-quoted strings, template literals, and bare
      JSX text nodes (`<button>Chọn</button>`) — which is how copy actually leaks into
      JSX, so it would give false confidence that the i18n seam holds

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Mock and real backend diverge → integration surprise in Phase 5 | Fixtures come from a real run; `docs/chat_api_contract.md` is the single source both sides read |
| **Options inferred from reply text**, reproducing the bug `suggestions[]` exists to fix | Step 1 makes the failure explicit; a success criterion forbids it. The model emits numbered prose constantly, so this looks reasonable and is not |
| Chips treated as hotel-only, so guided preference turns lose their menu | `suggestions[]` is rendered generically in step 9; cards are a `stage`-specific enhancement layered on top |
| Hotel-pick contract misunderstood — client invents a new endpoint | The click sends an ordinal as a normal `message`; no new backend verb. Stated in the contract |
| Stale `session_id` in `sessionStorage` after a server restart shows a dead app | Step 7 handles 404 by re-bootstrapping; it has its own success criterion |
| Scope creep toward the 3-panel comp | Non-goals are explicit in `plan.md`; the comp is phase-05's target |
| 60s request looks like a hang | Elapsed counter plus staged copy ("đang tìm khách sạn…") after 10s — the visible timer is why D3 is acceptable |
| Vietnamese diacritics mangled in fixtures | Fixtures written as UTF-8 JSON; one accented string asserted in the flow check |
| `npm create vite` scaffolds newer React with different idioms | Pin the scaffolded versions in `package.json`; record the React version in the phase notes |
