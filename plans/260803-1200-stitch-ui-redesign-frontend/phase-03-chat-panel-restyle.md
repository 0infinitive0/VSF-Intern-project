---
phase: 3
title: "Chat panel restyle"
status: completed
priority: P1
effort: "0.75d"
dependencies: [1, 2]
---

# Phase 3: Chat panel restyle

## Overview

Restyle the left column (`ChatPanel` → `MessageList` → `MessageBubble`/`Composer`/
`ElapsedSpinner`/`SuggestionChips`) to the Stitch "AI Assistant" look: renamed header,
rounder message bubbles with an AI avatar chip, pill-shaped composer. Convert all 6
touched files from `.jsx`/`.js` to `.tsx`/`.ts`, including `use-chat-session.js` since
its `ChatState` shape is what every other converted component types against.

**Explicitly not built** (per `plan.md` Decision 2): the "DeepDive Thinking" widget
(`assets/04-detailed-itinerary-chat.html`, fabricated step-by-step reasoning list with
hardcoded checkmarks like "Hotel Confirmed: The Grand View", "Analyzing location...").
`ElapsedSpinner` already shows real elapsed time honestly — it is restyled, not
replaced.

## Requirements

- Functional: panel header shows an `auto_awesome` icon + "AI Assistant" title. Add a
  new `chatPanelTitle` string — do **not** repoint `appTitle` (verified during plan
  validation: `S.appTitle` has 3 call sites — `App.jsx:31`, and `chat-panel.jsx:16`
  (`aria-label`) + `:21` (visible text) — Phase 2 already replaces `App.jsx`'s use with
  new top-nav branding copy, so once this phase also replaces both `chat-panel.jsx`
  sites, `appTitle` has zero remaining callers). <!-- Updated: Validation Session 1 -
  S.appTitle usage-site correction -->
- Functional: the chat panel's root `<section aria-label={S.appTitle}>`
  (`chat-panel.jsx:16`) must get an explicit replacement `aria-label` (e.g.
  `S.chatPanelTitle`, not left unset) — this is an accessibility regression risk
  flagged during validation, not just a visual change.
- Functional: message bubbles gain `rounded-2xl` with a sharp corner on the
  sender's side (`rounded-tr-sm` for user, `rounded-tl-sm` for AI) — a real Stitch
  detail, not fabricated content.
- Functional: AI messages get a small circular avatar chip (`bg-primary` circle with a
  white `auto_awesome` icon) ahead of the bubble, no label needed beyond what
  `strings.ts` (converted from `strings.js` in Phase 1) already has (do not invent a "V-OTA Assistant" caption not currently in
  the contract — the Stitch mock's caption is decorative chrome, the icon chip alone is
  sufficient and keeps this scoped).
- Functional: composer becomes a full-width pill input matching
  `assets/04-detailed-itinerary-chat.html`'s input styling (`rounded-full`,
  `bg-surface-muted`, `focus:ring-2 focus:ring-primary`) — keep the existing `<textarea>`
  (multi-line + auto-grow, `composer.jsx:41-51`) rather than switching to Stitch's
  single-line `<input type="text">`; the auto-grow behavior is real functionality Stitch
  doesn't model and must not be dropped.
- Functional: send button keeps the `send` icon (Stitch's mock shows `stop`, implying a
  streaming-cancel affordance this app does not have — do not adopt `stop`, that would
  imply fake streaming).
- Non-functional: `SuggestionChips` and `ElapsedSpinner` restyle to the new
  `border-subtle`/`surface-muted`/`primary` tokens already available; no behavior change.

## Architecture

Reference markup (`assets/04-detailed-itinerary-chat.html`), adapted per Requirements:

```html
<!-- Header -->
<div class="px-6 py-5 flex justify-between items-center bg-surface-background">
  <div class="flex items-center gap-2">
    <span class="material-symbols-outlined text-primary text-[22px]">auto_awesome</span>
    <h2 class="font-display text-lg font-bold text-on-surface">AI Assistant</h2>
  </div>
</div>

<!-- AI message -->
<div class="flex flex-col items-start gap-1">
  <div class="flex items-center gap-2 mb-1 pl-1">
    <div class="w-6 h-6 rounded-full bg-primary flex items-center justify-center">
      <span class="material-symbols-outlined text-on-primary text-[14px]">auto_awesome</span>
    </div>
  </div>
  <div class="bg-surface-container-low text-on-surface rounded-2xl rounded-tl-sm px-4 py-3 max-w-[85%] text-sm">
    ...
  </div>
</div>

<!-- Composer -->
<div class="relative flex items-center">
  <textarea class="w-full bg-surface-muted border-none rounded-full py-3.5 pl-5 pr-14 focus:outline-none focus:ring-2 focus:ring-primary text-sm placeholder:text-on-surface-variant" placeholder="Ask anything about the trip..." />
  <button class="absolute right-2 p-2 bg-primary text-on-primary rounded-full">
    <span class="material-symbols-outlined text-[20px]">send</span>
  </button>
</div>
```

`use-chat-session.js`'s state shape (`use-chat-session.js:24-33`) becomes `ChatState`
from `types.ts` (Phase 1) — the reducer's `action` union should be typed as a discriminated
union keyed on `type`, matching the existing `A` constants (`use-chat-session.js:37-44`).

## Related Code Files

- Modify: `frontend/src/types.ts` (add `PlannerChatResponse` per Step 1)
- Modify: `frontend/src/components/chat-panel.jsx` → `chat-panel.tsx`
- Modify: `frontend/src/components/message-list.jsx` → `message-list.tsx`
- Modify: `frontend/src/components/message-bubble.jsx` → `message-bubble.tsx`
- Modify: `frontend/src/components/composer.jsx` → `composer.tsx`
- Modify: `frontend/src/components/elapsed-spinner.jsx` → `elapsed-spinner.tsx`
- Modify: `frontend/src/components/suggestion-chips.jsx` → `suggestion-chips.tsx`
- Modify: `frontend/src/hooks/use-chat-session.js` → `use-chat-session.ts`
- Modify: `frontend/src/api/chat-client.js` → `chat-client.ts` (typed request/response
  using `types.ts` shapes; check its current fetch calls before typing return values —
  read the file first, don't assume the shape)
- Modify: `frontend/src/strings.ts` (add `chatPanelTitle` if needed per Requirements)

## Implementation Steps

1. `chat-client.js` (read in full for this plan) exports `createSession()`,
   `sendMessage(sessionId, message)`, `getPlan(sessionId)`, `resetSession(sessionId)`,
   all built on one `request(method, path, body)` helper (`chat-client.js:11-38`).
   `sendMessage`'s response includes an `intake` field (`chat-client.js:51`) not yet in
   `types.ts` — add `intake?: unknown` to a `PlannerChatResponse` interface in
   `types.ts` (not consumed by any current component, so `unknown` is correct — do not
   guess its shape). Note: `getPlan()` exists but is unused by any component —
   `use-chat-session.js:147` does its own raw `fetch` to the same endpoint during
   bootstrap instead of calling `getPlan()`. Leave this as-is; deduplicating it is out
   of scope for a visual-redesign plan.
2. Convert `use-chat-session.js` → `.ts` first (everything else depends on its exported
   `ChatState`/`send`/`reset` types). Type the reducer's `action` parameter as a
   discriminated union over the 5 `A` constants; type `dispatch` calls accordingly.
3. Convert `chat-client.ts`, typing responses against `TripPlan`/`HotelOption`/
   `Suggestion` from `types.ts`.
4. Convert `elapsed-spinner.tsx`, `suggestion-chips.tsx`, `message-bubble.tsx` —
   restyle per Requirements, type props explicitly (e.g.
   `{ elapsedMs: number }`, `{ message: ChatMessage }`).
5. Convert `message-list.tsx`, `composer.tsx`, `chat-panel.tsx` — restyle container/
   header per Architecture; wire the new pill composer to the existing `onSend`/
   `disabled` props unchanged. Replace both `S.appTitle` call sites
   (`chat-panel.jsx:16,21`) with `S.chatPanelTitle`; confirm `App.tsx` (Phase 2) no
   longer references `appTitle` either, then delete the now-dead `appTitle` key from
   `strings.ts`.
6. Run `npx tsc --noEmit` — fix any strict-mode errors surfaced by the newly typed hook
   (expected, per Phase 1's risk note).
7. Manual check: send a message, confirm bubbles/avatar chip/composer render per the
   Stitch reference, elapsed spinner still ticks, suggestion chips still clickable, and
   `grep -rn "appTitle" frontend/src/` returns nothing.

## Success Criteria

- [x] All 8 listed files converted to `.tsx`/`.ts`; no `.jsx`/`.js` remain in
      `components/`, `hooks/`, or `api/`.
- [x] Chat panel visually matches the Stitch reference bubble/avatar/composer styling.
- [x] No DeepDive-Thinking-style fabricated content anywhere in the chat panel.
- [x] `npx tsc --noEmit` clean; `npm run dev` chat flow (send → reply → chips/cards)
      unchanged in behavior.
- [x] `appTitle` key removed from `strings.ts`; zero remaining references anywhere in `frontend/src/`.

## Risk Assessment

- **Risk:** typing `use-chat-session.ts`'s reducer strictly may surface real latent bugs
  (e.g. a field assumed non-null that the backend can send as `null`) that plain JS
  silently tolerated. **Mitigation:** treat these as real findings, not noise — fix the
  null-handling rather than casting them away with `as any`/`!`.
- **Risk:** `chat-client.js` was not read during plan research (deferred to this phase's
  step 1) — its actual shape could differ from assumptions in `types.ts`.
  **Mitigation:** step 1 explicitly requires reading it first and reconciling
  `types.ts` if it disagrees, before converting anything else.
