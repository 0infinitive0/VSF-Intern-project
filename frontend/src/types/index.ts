/**
 * types/index.ts — the app's type surface.
 *
 * Everything the backend sends is an alias into `wire.generated.ts`, which
 * `npm run openapi:gen` produces from the FastAPI schema. Nothing on the wire
 * is hand-written here any more: the previous `types.ts` said it had been
 * "verified against backend/src/services/trip_formatter.py" — true once, on
 * one day, and drifted afterwards. `duration_days`, `status`, `theme`,
 * `order_index`, `activity`, `created_at` and `updated_at` were all declared
 * required while the backend could return null for each, so TypeScript
 * cheerfully approved code that crashed on real payloads.
 *
 * Types the frontend owns — state shapes, view models, the SSE envelope —
 * stay hand-written below, because no backend schema describes them.
 *
 * Aliases exist so call sites keep importing friendly names rather than
 * `components['schemas']['SessionSummaryPayload']`.
 */

import type { components } from './wire.generated'

type Schemas = components['schemas']

// ── Wire types (generated — change the backend, then run openapi:gen) ────────

export type Suggestion = Schemas['SuggestionPayload']
export type HotelOption = Schemas['HotelOption']
export type PreferencePayload = Schemas['PreferencePayload']
export type AmenityCatalogOption = Schemas['AmenityCatalogPayload']
export type RouteInfo = Schemas['RouteInfoPayload']
export type DayItem = Schemas['ItineraryItem']
export type Day = Schemas['DayPlan']
export type Hotel = Schemas['TripPlanHotel']
export type TripPlan = Schemas['TripPlanPayload']
export type IntakeStatus = Schemas['IntakeStatus']
export type PlannerChatResponse = Schemas['PlannerChatResponse']
export type RoomPrice = Schemas['RoomPricePayload']
export type RoomDetail = Schemas['RoomDetailPayload']
export type HotelDetail = Schemas['HotelDetailPayload']
export type AttractionDetail = Schemas['AttractionDetailPayload']
export type SuggestedPlace = Schemas['SuggestedPlacePayload']
export type SessionSummary = Schemas['SessionSummaryPayload']
export type RestoredMessage = Schemas['RestoredMessagePayload']
export type SessionRestore = Schemas['SessionRestorePayload']
// Room-hold / checkout — real /api/v1/bookings* calls (use-room-hold.ts,
// api/booking-client.ts).
export type Booking = Schemas['BookingPayload']
export type BookingReservationRequest = Schemas['BookingReservationRequest']
export type BookingOwnershipRequest = Schemas['BookingOwnershipRequest']
export type BookingStatus = Booking['status']

// VNPay payment (plan 260818-vnpay-payment-and-email-confirmation) — real
// /api/v1/payments/vnpay* calls (api/payment-client.ts).
export type CreateVnpayPaymentRequest = Schemas['CreateVnpayPaymentRequest']
export type CreateVnpayPaymentResponse = Schemas['CreateVnpayPaymentResponse']
export type Payment = Schemas['PaymentPayload']
export type PaymentStatus = Payment['status']

// "Reopen a past session's booking" (plan 260818-vnpay-payment-and-email-
// confirmation's addendum 4) — GET /chat/{session_id}/booking-receipt,
// independent of roomHold (api/payment-client.ts's getBookingReceipt).
export type BookingReceipt = Schemas['BookingReceiptPayload']
export type BookingReceiptRoom = Schemas['BookingReceiptRoomPayload']

/** The backend's `ChatStage`, derived from the response rather than restated,
 * so a stage that loses its producer breaks the build here too. `null` is the
 * frontend's own addition: a locally-authored bubble (the greeting, the intake
 * question) has no server stage. */
export type Stage = PlannerChatResponse['stage'] | null

export type SessionStatus = SessionSummary['status']
export type TripStatus = TripPlan['status']

// ── Knowledge that outlived the hand-written types ──────────────────────────
// These notes describe real backend behavior that a schema cannot express.
// They were comments in the old types.ts; the fields they describe are now
// generated, so the notes live here rather than disappearing with the file.
//
// `coordinates` (HotelOption, Hotel, DayItem, NearbyPlace, AttractionDetail):
//   always a "lat,lng" string, never WKT. Verified against the DB column
//   (backend/scripts/database_schema.sql:12, e.g. '10.762622, 106.660172')
//   and both parsers (routing.py:parse_coordinates,
//   trip_scheduler.py:parse_coordinates), which only ever split on ",".
//
// `DayItem.route_from_hotel`: commonly null even when a route WAS computed at
//   generation time — ITEM_RPC_FIELDS (itinerary_store.py:47-60) does not
//   persist it, so it is dropped on the next DB round-trip. Expect null on
//   most saved itineraries; this is not a rare edge case.
//
// `RouteInfo` with {distance_km: 0, duration_mins: 0, polyline: ""} means
//   origin and destination coordinates were identical (routing.py's
//   get_route_to_next) — "no travel needed", which is distinct from
//   `route_to_next` being null (no route could be computed).
//
// `IntakeStatus.people`: a backend-formatted string ("2 người"), not a count.
//   Render verbatim; never re-parse it for display.
//
// `NearbyPlace.distance_text`: a pre-formatted Vietnamese string stored in the
//   DB. It is data, not a UI string — rebuild the km figure from `distance_km`
//   through Intl.NumberFormat so it honours the UI locale.
//
// `HotelOption.display_amenities`: preference-first, category-diverse, max 4
//   (schemas.py's _display_amenities) — what the hotel card renders.
//   `amenities` is the full raw list.
//
// `HotelOption.match_score` / `match_reasons`: 0..1 composite ranking score
//   (hotel_selection.py's _composite_score) and the parameters behind it.
//   `MatchReason.code` is an i18n key under matchReason.*; `value` is the raw
//   number the code describes — the backend never sends display strings.

/** One ranking parameter behind "AI đề xuất vì…". Not a backend schema: the
 * wire sends `match_reasons` as free-form objects, and this is the shape the
 * UI reads out of them. */
export interface MatchReason {
  code: string
  value: number | string
}

/** Vehicle/profile code Mapbox Directions was actually called with — never a
 * display string; the frontend translates via routeProfile.<code>. 'driving'
 * is kept for forward-compat although only driving-traffic/walking/cycling are
 * called today (routing.py, Phase 12). */
export type RouteProfile = 'driving-traffic' | 'walking' | 'cycling' | 'driving'

const ROUTE_PROFILES: readonly string[] = ['driving-traffic', 'walking', 'cycling', 'driving']

/** Narrow the wire's free-form `profile` string to a profile this UI can label.
 *
 * The backend types it as a plain string, and that is accurate — it echoes
 * whatever profile the routing provider was called with. Anything unrecognised
 * becomes null so the caller falls back to a generic label instead of asking
 * i18n for a key that doesn't exist. A runtime check, not a cast: the whole
 * point of generating these types is to stop asserting things about payloads. */
export function asRouteProfile(value: string | null | undefined): RouteProfile | null {
  return value && ROUTE_PROFILES.includes(value) ? (value as RouteProfile) : null
}

export interface NearbyPlace {
  name?: string
  category?: string
  coordinates?: string | null
  distance_km?: number
  distance_text?: string
}

// ── Frontend-owned shapes (no backend schema describes these) ───────────────

export type MessageRole = 'user' | 'ai'

export interface ChatMessage {
  id: string
  role: MessageRole
  text: string
  stage: Stage
  isError?: boolean
  /**
   * Reveal this reply character by character.
   *
   * Set only for a reply that arrived complete, with no `delta` frames behind
   * it — a deterministic answer such as a hotel-search result, which has no
   * model producing tokens to stream. Never set on restored history: replaying
   * an old message on reload would be theatre, not feedback.
   */
  typewriter?: boolean
  /**
   * The steps behind this reply, as facts rather than sentences — the wording
   * is rebuilt here so it follows the reader's current language rather than the
   * one the turn ran in. Absent for every message written before the column
   * existed, which is most of history and the ordinary case.
   */
  thinkingTrace?: PhaseTraceEntry[]
  // Client-side ISO timestamp, stamped in the reducer at SEND_START/SEND_SUCCESS.
  // Only ever present for messages sent this session — restored history carries
  // the server's real `at` and must not be invented here.
  at?: string
}

export interface HotelFilterData {
  minPrice: number | null
  maxPrice: number | null
  hotelAmenities: AmenityCatalogOption[]
  allPreferences: PreferencePayload[]
  activePreferences: PreferencePayload[]
}

export interface ChatState {
  sessionId: string | null
  // Bumped on RESET/RESTORE — the reducer's guard against a stale in-flight
  // turn resolving after the user has switched sessions. sessionId alone
  // can't do this job: A→B→A leaves sessionId back at "A", but turnId only
  // ever increases, so a reply captured for the first "A" episode is still
  // recognizably stale during the second one.
  turnId: number
  messages: ChatMessage[]
  suggestions: Suggestion[]
  hotelOptions: HotelOption[]
  hotelFilterData: HotelFilterData
  // Set only on a turn whose worker wrote one — e.g. itinerary_node's
  // "list_nearby" search today, any future worker's own place suggestion
  // tomorrow (see applyPlannerResponse). Cleared like hotelOptions on every
  // other turn so a stale result never leaks onto the map. Map-visibility
  // toggle for these lives as transient component state in StageWorkspace,
  // not here.
  suggestedPlaces: SuggestedPlace[]
  tripPlan: TripPlan | null
  intake: IntakeStatus | null
  pending: boolean
  // True while the "đổi khách sạn" step-nav action (step-navigator.tsx) is
  // re-fetching hotel options via the dedicated /hotels/change endpoint.
  // Deliberately separate from `pending`: that flag belongs to the chat
  // turn machinery (message bubbles, elapsed timer, streaming) and this
  // isn't a chat turn — no message, no extraction, just a hotel-list fetch.
  hotelsLoading: boolean
  elapsedMs: number
  error: string | null
  // ── Streaming (transient — cleared by SEND_SUCCESS/SEND_ERROR) ──
  // Accumulated `delta` text for the in-flight turn; '' when not streaming.
  streamingText: string
  // Growing list of `phase` events received for the in-flight turn; never
  // pre-populated with placeholder steps — a branch that doesn't emit a key
  // simply never adds that row (contract §Streaming).
  phases: TurnPhase[]
  /**
   * The same turn's progress, folded into user-facing steps with sentences
   * built from each step's facts. Parallel to `phases`, not a replacement:
   * `phases` feeds the right-hand panel and keeps its own shape.
   */
  thinking: ThinkingGroup[]
}

// ── SSE streaming contract (POST /planner_chat/stream) ──────────────────────
// docs/chat_api_contract.md §Streaming. Not in the OpenAPI schema: FastAPI
// describes the endpoint's response as a stream, not its frame shapes, so
// these stay hand-written and must be kept in step with that document.

/** Opaque backend progress keys — each maps 1:1 to a real emission site
 * (`agents/graph/phase_keys.py` plus the in-service emits). Never rendered
 * raw; the frontend owns the i18n labels, and an unknown key is ignored
 * silently rather than displayed. */
export type PhaseKey =
  | 'received'
  | 'routing'
  | 'compacting_history'
  | 'intake_check'
  | 'hotel_search'
  | 'itinerary_build'
  | 'routing_legs'
  | 'persisting'
  | 'generating'

/** One entry of the growing progress list shown while a turn streams. */
export interface TurnPhase {
  key: PhaseKey
  at: number // epoch seconds from the backend
}

/**
 * Facts a `phase` frame may carry about the step that just ran.
 *
 * EVERY field is optional, and that is the contract rather than caution: a step
 * with nothing to report sends `key` and `at` alone. Field names come from
 * docs/chat_api_contract.md §Streaming; the backend whitelists them in
 * `agents/graph/phase_facts.py`, so no display text and no internal id appears
 * here — only keys, counts, and schema field paths.
 */
export interface PhaseFacts {
  /**
   * Which edge of the step this frame reports. `started` when the node begins,
   * `completed` when it returns; facts only ever ride `completed`. A phase
   * emitted from inside a service reports `started` and never completes — close
   * it when a later step opens, or at `final`.
   */
  status?: 'started' | 'completed'
  /** intake_check: how the message was classified. */
  intent?: string
  /** intake_check: travel-state field paths touched (`people`, `budget.target`). */
  fields?: string[]
  /** routing: node the supervisor picked. */
  worker?: string
  /** hotel_search: `ok`, `no_results`, `error`, … — what the search found,
   * which is not the step's own `status` above. */
  outcome?: string
  /** hotel_search: what the user asked for. */
  destination?: string
  /** hotel_search: present only when the user set one. */
  radius_km?: number
  /** hotel_search: amenity ids the user required. */
  amenities?: string[]
  /** hotel_search: options shown. */
  kept?: number
  /** routing_legs: days the route recalculation covers. */
  days?: number
}

/**
 * One completed step, as stored with the reply it helped produce.
 *
 * The wire type types `facts` as an open dict — OpenAPI cannot express the
 * whitelist `agents/graph/phase_facts.py` enforces — so `PhaseFacts` is layered
 * on here, where the fields are actually read.
 */
export type PhaseTraceEntry = Omit<Schemas['ThinkingTraceEntry'], 'facts'> & {
  facts: PhaseFacts
}

/** The user-facing steps the nine phase keys fold into. */
export type ThinkingGroupKey =
  | 'analyze'
  | 'route'
  | 'hotels'
  | 'itinerary'
  | 'save'
  | 'reply'

/** One step of the thinking block, with the sentences built for it. */
export interface ThinkingGroup {
  key: ThinkingGroupKey
  labelKey: string
  /** Sentences built from graph facts. Empty when the step reported none. */
  lines: string[]
  /**
   * The model's summary of its own reasoning, when it produced one.
   * Always English, often empty — see docs/chat_api_contract.md. It supplements
   * `lines` and must never be used to fill in for missing facts.
   */
  reasoning: string
  done: boolean
}

export type StreamEvent =
  | { event: 'phase'; data: { key: PhaseKey; at: number } & PhaseFacts }
  // Reply text, token by token — emitted only for the graph nodes that write
  // prose for the user (backend `STREAMING_NODES`).
  | { event: 'delta'; data: { text: string } }
  // The model's own reasoning summary. Never a prefix of `final.reply`, and a
  // valid turn may carry none of these frames at all.
  | { event: 'reasoning'; data: { text: string; key: PhaseKey } }
  | { event: 'final'; data: PlannerChatResponse } // same dict as POST /planner_chat
  | { event: 'error'; data: { detail: string } }

export type TerminalStreamEvent = Extract<StreamEvent, { event: 'final' | 'error' }>
