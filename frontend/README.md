# V-OTA AI Travel Planner — Frontend Prototype

> ⚠️ **Prototype status** — no backend, no database. Every hotel, itinerary, chat
> reply and history entry you see is **mock data**. See "Adding a real backend
> later" below for how that boundary is designed.

## What this actually is

This project is not a plain HTML/JS app — it's a **`.dc.html` "Design
Component"** running on a small bundled runtime (`support.js`, generated,
**do not edit** — see the comment at the top of that file).

- A `.dc.html` file has two parts: an `<x-dc>` template (HTML-like markup with
  `{{ expr }}` bindings, `sc-for`, `sc-if`) and a `<script data-dc-script>`
  holding a `class Component extends DCLogic` (state + event handlers +
  computed values consumed by the template).
- The runtime lets one `.dc.html` **import another** as a component —
  `<dc-import name="HotelCard" .../>` fetches `./HotelCard.dc.html`.
  **This fetch is hardcoded to the project root** (`COMPONENT_DIR = "."` in
  support.js, and `name` is `encodeURIComponent`-ed as a whole, so a `/` in
  `name` cannot mean "subfolder"). Every `dc-import`ed component therefore
  lives as a **flat file next to `V-OTA Planner.dc.html`**, named
  descriptively per feature (`HotelCard.dc.html`, `ChatPanel.dc.html`, ...)
  instead of under a `components/` tree. `scripts/` and `styles/` are
  unaffected — those load through explicit `<script src>`/`<link href>`
  paths, not this name-based lookup.
- That fetch uses `fetch()`, which browsers block against `file://` URLs.
  **This is why the project needs to be served over `http://`, even just for
  local development.**
- **Prop naming gotcha:** a `dc-import` attribute name that starts with an
  uppercase letter (e.g. `L="{{ L }}"`) silently breaks — the browser's HTML
  parser lowercases attribute names before the runtime ever sees them, and
  the runtime's camelCase-preserving escape only fires for names matching
  `[a-z]+[A-Z]...` (lowercase first). The i18n dict prop is called `dict`
  everywhere in this project for exactly this reason — never `L`.

## Running it locally

No build step, no bundler, no framework install — just a static file server.

```bash
npm run dev
```

Then open the URL it prints (defaults to `http://localhost:5173/V-OTA%20Planner.dc.html`).

`server.js` is a ~50-line, zero-dependency Node static file server
(`http`/`fs` only) — it exists purely so `fetch()`-based component loading
works. It is **dev-only**; it is not meant to be how this is deployed, only
how it's previewed while building.

## Project layout

```
V-OTA Planner.dc.html    Root Design Component — screen/phase switching
                          (intake → generating → hotels → workspace), top-level
                          state (theme, language, active conversation/hotel/day/
                          tab, calendar, budget slider), and the <dc-import>
                          calls that assemble Sidebar + ChatPanel + each screen.
support.js                Generated dc-runtime. Do not edit — rebuilt upstream.

*.dc.html                 Every other .dc.html file in the project root is a
                           dc-imported Design Component, flat (see the prop-
                           passing constraint above):
  Sidebar                   brand, new-trip, history list, language/theme toggle
  HistoryRow                one conversation row in the sidebar
  ChatPanel                 the whole persistent chat column
  ChatMessage                one chat bubble
  PendingChangeCard          "your request changed" prompt
  DestinationPicker, PeoplePicker, DatePicker, BudgetSlider, InterestPicker
                              the progressive-disclosure quick-input widgets
  HotelCard                 one hotel in the list
  HotelDetail                the hotel focus/detail panel
  RoomCard                   one room inside HotelDetail (nested dc-import)
  PlaceDetail                the sightseeing-item focus/detail panel
  TimelineItem               one stop in a day's itinerary timeline
  DayCard                    one day's summary row in the overview tab

scripts/                  Plain global-scope JS (no bundler → no ES modules
                           inside dc-script; these attach to `window.VOTA.*`
                           and load via <script src> from the real document
                           <head> — see the comment there for why not the
                           <helmet> block).
  constants/                 config.js (colors, budget bounds), env.js (API
                              base URL — the one non-hard-coded config point),
                              i18n.js (UI dict + scripted AI lines + VI->EN
                              content map), mock-data.js (hotels/days/
                              history/etc.)
  api/                        http-client.js — shared fetch wrapper (base URL,
                              headers, timeout, auth-token hook) for our own
                              backend. Not called by anything yet — no real
                              endpoint exists — see BACKEND_INTEGRATION.md.
  services/                  The sole data-access boundary — Root Logic never
                              reads window.VOTA.MockData or calls fetch()
                              directly, always a services/*.js function.
                              hotel.service.js, destination.service.js,
                              itinerary.service.js, history.service.js — each
                              wraps the matching mock-data.js slice behind a
                              function; swapping to a real backend means
                              editing only these (see BACKEND_INTEGRATION.md).
                              chat.service.js — the mock "AI" text analysis
                              (detectLang/detectChange/affectedOf); this is
                              the intended swap point for a real NLP/LLM call.
                              map.service.js — shared Leaflet bootstrap plus
                              fetchRouteGeometry() (the one real network call
                              in the app today, OSRM's public routing API —
                              see "Known scope" below for what's NOT unified).
  store/                     app-store.js — theme + language persistence,
                              the one piece of state genuinely used outside
                              the component tree. See the file's own comment
                              for why nothing else got this treatment.
  utils/                     formatters.js (currency/date), geo.js (haversine,
                              bezier route curve, string hash).

styles/                   Global CSS tokens (variables, theme, animation,
                           typography, layout) shared by every component.
                           Per-component visual styling stays inline in each
                           component's template — the app renders everything
                           through dynamic inline `style="{{ ... }}"`
                           bindings, which is how this runtime is designed to
                           be styled; rewriting that to className + CSS
                           rules would risk visual drift for no functional
                           gain (see REFACTOR.md).
```

## Adding a real backend later

Per the current project constraints, this stays mock-data-only for now, but
the service layer described above is already real (not just documented
intent): Root Logic calls `window.VOTA.Services.<feature>.getX()` everywhere,
never `window.VOTA.MockData` or `fetch()` directly. The integration point is
`scripts/services/*.js` — swap the mock implementation for real API calls
(via `scripts/api/http-client.js`) there; UI components consume services
through the same function signatures, so they shouldn't need to change.
`scripts/constants/mock-data.js` is the other half of that boundary — the
hotel/itinerary/history data it exports is exactly what a real API response
should shape into. See `BACKEND_INTEGRATION.md` for the full data-flow
diagram, the planned REST API per feature, and the one flagged exception
(Root Logic's constructor reads data synchronously today, since dc-runtime
renders synchronously right after construction with no loading/suspense
mechanism — moving to a real async backend will need one follow-up edit
there to add a loading state).

## Known scope / deliberately deferred

- **Map duplication is only partly unified.** The hotels-screen map and the
  trip-workspace map share their Leaflet bootstrap (`scripts/services/
  map.service.js`) but still duplicate marker/route drawing and each own
  hover-sync logic in Root. See `REFACTOR.md` for why a full shared `TripMap`
  component was evaluated and intentionally not forced through this pass.
- **Shared UI primitives** (a generic Button/Card/Badge/Modal library) were
  not built as a separate layer. The app's ~34 buttons are each styled for
  their specific context (segmented controls, pill chips, primary CTAs, icon
  circles) with real differences, not copy-paste duplicates; inventing a
  unified variant system risked visual drift for limited reuse value. See
  REFACTOR.md for a concrete, lower-risk starting point if this is wanted
  later (the 4 identical calendar-nav buttons in DatePicker.dc.html).

## Architecture notes / deliberate deviations from a textbook setup

See `REFACTOR.md` for the full rationale on where this diverges from a
standard "feature folder + ES modules + Redux-style store" layout, and why.
