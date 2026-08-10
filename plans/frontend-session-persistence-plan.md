# Frontend Plan: Session Persistence and History

## Scope

Implement the client-side work needed to restore a planner session, show saved
history, and keep the current planner UI synchronized with backend checkpoints.
This plan does not require frontend ownership of itinerary calculations or
session business state.

## Decisions

- The backend remains the source of truth for planner workflow state, selected
  hotel, itinerary data, and chat history.
- The frontend restores display-only chat history. Users cannot edit, replay,
  or delete an individual message.
- `GET /api/v1/chat/sessions?page=1&page_size=10` is consumed as paginated
  history with the response envelope `{ sessions, page, page_size, has_more }`.
- `GET /api/v1/chat/{session_id}/restore` initializes the entire active planner
  screen: messages, stage, hotel options, trip plan, intake status, and quick
  suggestions.
- The UI must not parse assistant text to reconstruct itinerary cards or
  workflow state; it uses structured response fields only.

## Phase 1: API client contracts

### Task 1: Add session-history and restore response types

**Description:** Define frontend types for the paginated history response and
the existing session-restore payload.

**Acceptance criteria:**

- [ ] History type contains `sessions`, `page`, `page_size`, and `has_more`.
- [ ] Restore type includes messages, stage, hotel options, trip plan, intake,
  and suggestions.
- [ ] No frontend type assumes editable messages or transcript metadata.

**Verification:**

- [ ] Type check passes.
- [ ] API fixture validates against both endpoint response shapes.

**Dependencies:** None.

## Phase 2: Active-session restoration

### Task 2: Add a `restoreSession(sessionId)` API call

**Description:** Fetch the restore payload and normalize it into the planner
store in one atomic state update.

**Acceptance criteria:**

- [ ] Loading a known session restores all visible messages in order.
- [ ] The restored stage selects the correct planner step/tab.
- [ ] Hotel cards and itinerary cards come from structured payload fields.
- [ ] Unknown or deleted sessions show a recoverable not-found state.

**Verification:**

- [ ] Unit test covers intake, hotel-selection, and completed-itinerary payloads.
- [ ] Manual refresh test preserves the selected hotel and itinerary display.

**Dependencies:** Task 1.

### Task 3: Prevent duplicate message rendering after restore

**Description:** Make restore replace the local transcript rather than append
to it. Subsequent normal POST/SSE responses append only their new visible pair.

**Acceptance criteria:**

- [ ] Refreshing or revisiting a session does not duplicate bubbles.
- [ ] A restored session can continue with a new message normally.
- [ ] Assistant itinerary prose is not rendered as a second plan beside the
  structured itinerary view.

**Verification:**

- [ ] Component/store test covers restore followed by a new chat response.

**Dependencies:** Task 2.

### Checkpoint: Restore flow

- [ ] Refresh works at intake, hotel selection, and completed itinerary stages.
- [ ] No frontend logic derives workflow state from natural-language chat text.

## Phase 3: Session history

### Task 4: Build the paginated session-history list

**Description:** Add a history panel/page that requests ten sessions at a time
and renders a compact session summary.

**Acceptance criteria:**

- [ ] Initial request uses `page=1&page_size=10`.
- [ ] “Load more” is shown only when `has_more` is true.
- [ ] Each row renders destination, duration, status, thumbnail, and dates when
  supplied.
- [ ] Selecting a row invokes the restore flow from Task 2.

**Verification:**

- [ ] UI test covers first page, final page, and a history row selection.

**Dependencies:** Tasks 1–2.

### Task 5: Add loading, empty, and failure states

**Description:** Make history and restoration resilient to slow networks and
backend failures without losing the active local UI.

**Acceptance criteria:**

- [ ] History has loading, empty, and retry states.
- [ ] Restore failure does not clear the currently visible session until a new
  restore succeeds.
- [ ] A deleted session row is removed/refreshed after a not-found response.

**Verification:**

- [ ] Component tests cover loading, empty, HTTP 404, and HTTP 500 states.

**Dependencies:** Tasks 2 and 4.

## Phase 4: End-to-end verification

### Task 6: Browser-level session continuity test

**Description:** Verify the real planner flow across a browser refresh.

**Acceptance criteria:**

- [ ] Create a session, complete intake, refresh, and continue.
- [ ] Choose a hotel, refresh, and see the same pending/completed state.
- [ ] Complete itinerary planning, refresh, and see hotel image plus itinerary
  item images from the structured trip-plan payload.
- [ ] History opens the same restored state in a fresh browser tab.

**Verification:**

- [ ] Run the browser integration test against the local backend.

**Dependencies:** Tasks 1–5 and deployed backend session persistence.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Old backend returns an array rather than the history envelope | Gate history UI on the new endpoint contract and show a recoverable error. |
| Restore payload is incomplete for an old session | Render available structured fields and provide “start a new trip”; do not infer missing data from chat prose. |
| Duplicate bubbles after hydration | Replace, never append, the transcript during restore. |
| Large chat transcript slows initial render | Render the latest messages first or virtualize only if measurement shows it is needed. |

## Out of scope

- Editing or replaying individual messages.
- Frontend itinerary routing, budgeting, hotel scoring, or persistence rules.
- Authentication, ownership controls, automatic expiry, and cross-session user profiles.
