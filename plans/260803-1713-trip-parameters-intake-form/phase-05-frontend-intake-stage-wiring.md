---
phase: 5
title: "Frontend intake-stage wiring"
status: completed
priority: P1
effort: "0.75d"
dependencies: [4]
---

# Phase 5: Frontend intake-stage wiring

## Overview

Wire `IntakeParametersForm` (Phase 4) into the live chat flow: always render it on
the last AI turn while `stage === 'intake'`, replacing the current sequential
`SuggestionChips` + free-text flow for that stage. `hotel_options` stage stays
untouched (existing `TripParametersCard` + `HotelOptionCards`).

## Requirements

- Functional: in `frontend/src/components/message-list.tsx`
  (current logic ~line 88-98: `stage === 'intake'` branch), replace the
  `<TripParametersCard .../><SuggestionChips .../>` pairing with
  `<IntakeParametersForm intake={intake} onSubmit={onSelect} disabled={pending} />`.
  `onSelect` is already the callback that sends a value as the next chat message
  (`message-list.tsx:32`) — the form's composed sentence is passed through the exact
  same path, no new prop plumbing needed at this layer.
- Functional: `hotel_options` branch (line ~79-87) is unchanged — still
  `TripParametersCard` (read-only) + `HotelOptionCards`.
- Functional: `intake` prop must reach `message-list.tsx` with the Phase 2-extended
  shape. Trace `frontend/src/hooks/use-chat-session.ts`'s reducer to confirm it
  already stores the full `PlannerChatResponse.intake` object as-is (likely just a
  reducer field assignment — verify, don't assume) — if so, no reducer change is
  needed, only the `types.ts` shape extension from Phase 4 is required for it to
  type-check.
- Functional: while `stage === 'intake'` but `intake` is still `null` (e.g. very
  first turn, before any backend response has arrived), render nothing new — the
  existing greeting/empty-state behavior (`message-list.tsx:54-65`) is unchanged.
- Non-functional: no change to `hotel_options`, `planned`, `modified`, `finalized`,
  or `error` stage rendering branches.

## Architecture

```
MessageList (stage === 'intake', last AI turn, !pending)
  BEFORE: <TripParametersCard .../> + <SuggestionChips .../>
  AFTER:  <IntakeParametersForm intake={intake} onSubmit={onSelect} disabled={pending} />

onSelect (existing, unchanged) → useChatSession.send(composedMessage)
  → sendMessage() [chat-client.ts, unchanged] → same endpoint, same request shape
```

## Related Code Files

- Modify: `frontend/src/components/message-list.tsx`
- Read (verify, edit only if needed): `frontend/src/hooks/use-chat-session.ts`,
  `frontend/src/App.tsx`

## Implementation Steps

1. Read `use-chat-session.ts`'s reducer end to end to confirm `intake` is stored
   verbatim from the response (no field allowlist that would silently drop the new
   Phase 2 fields).
2. Edit `message-list.tsx`: swap the `intake`-stage branch to render
   `IntakeParametersForm`, remove the now-unused `SuggestionChips` import from that
   branch only if it's not still needed elsewhere in the file (check the
   `hotel_options` branch doesn't also use it — confirm before removing the import).
3. Manually run the dev server (`npm run dev` or `npm run mock` per
   `frontend/mock/server.js`), start a fresh session, confirm the form renders
   immediately instead of a chat question.
4. Fill the form, submit, confirm the composed message appears as a normal user chat
   bubble and the reply advances the stage as expected.

## Success Criteria

- [ ] Fresh session at `intake` stage shows the form immediately, not a text
      question.
- [ ] Submitting the form sends exactly one message and the resulting AI turn
      reflects the backend's actual response (destination confirmed, etc.) — no
      client-side fabrication of a "success" state.
- [ ] `hotel_options` stage visual/behavior is byte-for-byte unchanged from before
      this phase (manual diff against current `main`/`dev`).
- [ ] `npx tsc --noEmit`, `oxlint`, `vite build` clean.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Removing `SuggestionChips` from the intake branch breaks a case where the backend still wants free-text follow-up (e.g. an ungrounded destination retry, per `next_question()`'s "Hiện mình có dữ liệu cho: ..." message) | The form's destination `<select>` is already constrained to `available_destinations`, so an ungrounded destination becomes structurally impossible from the form path; a plain-chat user who types an unsupported city still gets the existing text reply — that reply now renders as an AI message with the form re-shown below it (both can coexist, verify visually in step 3) |
| `intake` object shape mismatch between what Phase 2 actually ships and what Phase 4 assumed | Phase 6 adds an integration test hitting the real backend response shape, not just component-level fixtures |
