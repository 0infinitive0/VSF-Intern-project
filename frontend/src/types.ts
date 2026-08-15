/**
 * types.ts — shared shapes for the chat/trip-plan contract.
 * Verified against backend/src/services/trip_formatter.py (backend payload field names).
 */

export interface Suggestion {
  label: string
  value: string
}

// One ranking parameter behind "AI đề xuất vì...". code is an i18n key under
// matchReason.*; value is the raw number/label the code is about — backend never
// sends pre-translated display strings (src/models/schemas.py's HotelOption docs
// the same principle for match_score).
export interface MatchReason {
  code: string
  value: number | string
}

export interface HotelOption {
  index: number
  id?: string
  name: string
  star_rating?: number
  description?: string
  matched_rooms?: string[]
  average_nightly_price?: number
  total_stay_price?: number
  stay_night_count?: number
  currency?: string
  // "lat,lng" string; verified against DB column (backend/scripts/database_schema.sql:12,
  // e.g. '10.762622, 106.660172') and both backend parsers
  // (routing.py:parse_coordinates, trip_scheduler.py:parse_coordinates), which only ever
  // split on "," — never WKT.
  coordinates?: string | null
  address?: string
  area_name?: string
  image_url?: string | null
  amenities?: string[]
  // Preference-first, category-diverse, max 4 (schemas.py:_display_amenities) —
  // what the hotel card renders. `amenities` above is the full raw list.
  display_amenities?: string[]
  review_score?: number // 0..10
  review_count?: number
  match_score?: number // 0..1, real composite ranking score (hotel_selection.py:_composite_score)
  match_reasons?: MatchReason[]
  city?: string | null
  preferences?: string[]
}

export interface PreferencePayload {
  id: string
  label: string
}

export interface AmenityCatalogOption {
  id: string
  label_vi: string
  label_en: string
  category: string
  icon_key?: string | null
}

export interface HotelFilterData {
  minPrice: number | null
  maxPrice: number | null
  allPreferences: PreferencePayload[]
  activePreferences: PreferencePayload[]
}

// Vehicle/profile code Mapbox Directions was actually called with — never a display
// string. Frontend translates via i18n key routeProfile.<code>. 'driving' kept for
// forward-compat even though only driving-traffic/walking/cycling are called today
// (routing.py, Phase 12).
export type RouteProfile = 'driving-traffic' | 'walking' | 'cycling' | 'driving'

export interface RouteInfo {
  distance_km: number
  duration_mins: number
  polyline: string // Google Encoded Polyline, precision 1e5
  // Optional, not just nullable: today's OSRM call sites (routing.py:44-48 success case,
  // :83-88 identical-coordinates case) don't emit this key at all — it only starts
  // appearing once Phase 12 (Mapbox) ships. Treat missing and null the same way.
  profile?: RouteProfile | null
}

export interface DayItem {
  order_index: number
  start_time: string | null
  end_time: string | null
  activity: string
  kind?: string | null
  reference_type?: string | null
  reference_id?: string | null
  // Already returned today by to_trip_plan_payload (backend/src/services/trip_formatter.py:320-323)
  // — this is a type-gap fix, not a new backend field.
  coordinates?: string | null
  // Attraction/hotel photo carried through from PlaceCandidate.image_url
  // (trip_scheduler.py) into the itinerary item and emitted at
  // trip_formatter.py:335 — already on the wire, just not typed until now.
  image_url?: string | null
  // Real routed distance/duration from routing.py (recalculate_itinerary_routes);
  // null when coordinates are missing on either end, routing failed/timed out, or no
  // route was found — render the straight-line fallback in all of those cases.
  // When origin and destination coordinates are identical, the backend instead
  // returns {distance_km: 0, duration_mins: 0, polyline: "", profile: null}
  // (routing.py:get_route_to_next) — treat that as "no travel needed", distinct from
  // route_to_next being null outright.
  route_to_next?: RouteInfo | null
  // Hotel -> first item of the day. Commonly null even when a route was computed at
  // generation time: ITEM_RPC_FIELDS (itinerary_store.py:47-60) does not persist
  // route_from_hotel, so it is dropped on the next DB round-trip. Not a rare edge
  // case — expect this on most saved/reloaded itineraries (plan.md "Phần chưa làm" #15).
  route_from_hotel?: RouteInfo | null
}

export interface Day {
  day_number: number
  theme: string
  items: DayItem[]
}

export interface Hotel {
  id?: string
  name: string
  star_rating?: number
  description?: string
  matched_rooms?: string[]
  // "lat,lng" string (see HotelOption.coordinates above for the verification source) —
  // corrected from a prior comment here that claimed WKT; the DB column and every
  // backend parser only ever handle "lat,lng".
  coordinates?: string | null
  // Already emitted by to_trip_plan_payload (trip_formatter.py:358) — a type-gap fix.
  image_url?: string | null
  // 'agoda' | 'booking' — which OTA this row was crawled from; powers the handoff button.
  source_platform?: string | null
  // Original listing URL on the source OTA (backend/scripts/database_schema.sql:32).
  source_url?: string | null
}

export type TripStatus = string // backend sends free-text status, e.g. "Draft"

export interface TripPlan {
  status: TripStatus
  destination: string | null
  duration_days: number
  start_date: string | null
  end_date: string | null
  number_of_adults: number | null
  hotel: Hotel | null
  days: Day[]
  adjustments: string[]
}

export type MessageRole = 'user' | 'ai'
export type Stage = 'hotel_options' | 'error' | string | null

export interface ChatMessage {
  id: string
  role: MessageRole
  text: string
  stage: Stage
  isError?: boolean
  // Client-side ISO timestamp, stamped in the reducer at SEND_START/SEND_SUCCESS
  // (phase-06). Only ever present for messages sent this session — restored
  // history carries the server's real `at` (SessionRestore.restored_messages)
  // and must not be invented here.
  at?: string
}

// Snapshot of what the intake gate has collected so far (src/models/schemas.py:127-190).
// Populated during `intake`/`hotel_options` stages, before `trip_plan` exists (a hotel
// must be picked before the backend builds `trip_data` — see trip_planner.py's
// _generate_and_save_itinerary, only called from the select_hotel tool).
export interface IntakeStatus {
  destination: string | null
  duration: string | null
  start_date: string | null
  end_date: string | null
  people: string | null // formatted string, e.g. "2 người" — not a bare count
  preferences: string[] // travel-style labels (mirrors _PREFERENCE_LABELS)
  companions: string | null
  pace: string | null
  day_rhythm: string[]
  notes: string
  available_destinations: string[] // real destinations the intake picker may choose from
  budget_options: string[] // real budget/accommodation tier labels from hotel_selection
  min_price?: number | null // explicit budget.min slot (VND/night), when the user gave a range via chat
  max_price?: number | null // explicit budget.max slot (VND/night), when the user gave a range via chat
  budget_skipped?: boolean // true once the user explicitly opted out of a budget preference
  missing: string[]
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
  tripPlan: TripPlan | null
  intake: IntakeStatus | null
  pending: boolean
  // True while the "đổi khách sạn" step-nav action (step-navigator.tsx) is
  // re-fetching hotel options via the dedicated /hotels/change endpoint.
  // Deliberately separate from `pending`: that flag belongs to the chat
  // turn machinery (message bubbles, elapsed timer, streaming) and this
  // isn't a chat turn — no LLM call, no message, just a hotel-list fetch.
  hotelsLoading: boolean
  elapsedMs: number
  error: string | null
  // ── Streaming (Phase 5, transient — cleared by SEND_SUCCESS/SEND_ERROR) ──
  // Accumulated `delta` text for the in-flight turn; '' when not streaming.
  streamingText: string
  // Growing list of `phase` events received for the in-flight turn; never
  // pre-populated with placeholder steps — a branch that doesn't emit a key
  // simply never adds that row (contract §Streaming).
  phases: TurnPhase[]
}

export interface PlannerChatResponse {
  session_id: string
  reply: string
  suggestions: Suggestion[]
  stage: Stage
  hotel_options: HotelOption[]
  trip_plan: TripPlan | null
  intake?: IntakeStatus | null
  compound_min_price?: number | null
  compound_max_price?: number | null
  all_preferences?: PreferencePayload[]
  active_preferences?: PreferencePayload[]
}

// ── Phase 3 payloads — GET /hotels/{id}, GET /attractions/{id} ──────────────────
// All optional: these endpoints don't exist yet (Phase 3), so the frontend must
// render correctly against a fixture-only mock until then.

export interface RoomPrice {
  amount?: number | null
  currency?: string
  check_in_date?: string
  check_out_date?: string
  sold_out?: boolean
  package_details?: string | null
}

export interface RoomDetail {
  id?: string
  name?: string
  bed_description?: string
  room_size_sqm?: number
  max_guests?: number
  view?: string
  room_facilities?: string[]
  images?: string[]
  price?: RoomPrice | null // null when no room_prices row matches the requested stay
}

// Shape confirmed 06/08/2026 against real DB rows: objects, not free strings.
// distance_text/category are pre-formatted VI strings stored in the DB — data,
// not UI strings: pass category through as-is, but rebuild the km figure from
// distance_km via Intl.NumberFormat so it honours the UI locale. Never render
// distance_text directly (phase-08 §distToSights — same trap as intake.people).
export interface NearbyPlace {
  name?: string
  category?: string
  coordinates?: string | null // "lat,lng" — see HotelOption.coordinates
  distance_km?: number
  distance_text?: string
}

export interface HotelDetail {
  id?: string
  name?: string
  star_rating?: number
  description?: string
  address?: string
  city?: string
  area_name?: string
  location_highlight?: string
  coordinates?: string | null // "lat,lng" — see HotelOption.coordinates
  image_url?: string | null
  images?: string[]
  amenities?: string[]
  amenity_groups?: Record<string, string[]>
  review_score?: number
  review_count?: number
  category_scores?: Record<string, number>
  check_in_time?: string
  check_in_until?: string
  check_out_time?: string
  reception_open_until?: string
  nearby_attractions?: NearbyPlace[]
  nearby_essentials?: string[] // shape not re-confirmed; unused by the UI so far
  lowest_price?: number
  currency?: string
  rooms?: RoomDetail[]
  // 'agoda' | 'booking' — which OTA this row was crawled from; powers the handoff button.
  source_platform?: string | null
  // Original listing URL on the source OTA (backend/scripts/database_schema.sql:32).
  source_url?: string | null
}

export interface AttractionDetail {
  id?: string
  name?: string
  description?: string
  category?: string
  is_tour?: boolean
  estimated_duration_minutes?: number
  opening_time?: string
  closing_time?: string
  ticket_price_adult?: number
  ticket_price_child?: number
  rating?: number
  review_count?: number
  coordinates?: string | null
  images?: string[]
}

// ── Phase 4 payloads — GET /chat/sessions, GET /chat/{id}/restore ──────────────

export type SessionStatus = 'draft' | 'completed'

export interface SessionSummary {
  session_id: string
  title?: string // inferred, e.g. "Đà Nẵng – Hội An 4N3Đ"
  destination?: string | null
  duration_days?: number | null
  status: SessionStatus
  created_at: string
  updated_at: string
  thumbnail_url?: string | null // chosen hotel's image_url, or null
}

export interface RestoredMessage {
  role: 'assistant' | 'user' // wire value (session_store.py); map to MessageRole at the client
  text: string
  stage: Stage
  at: string
}

export interface SessionRestore {
  session_id: string
  messages: RestoredMessage[]
  suggestions: Suggestion[]
  stage: Stage
  hotel_options: HotelOption[]
  trip_plan: TripPlan | null
  intake?: IntakeStatus | null
}

// ── SSE streaming contract (POST /planner_chat/stream) ──────────────────────
// Frozen in docs/chat_api_contract.md §Streaming (plan 260806-1602-streaming-chat-messages,
// Phase 1). Event names are the shipped subset; `cancelled` exists in the plan but is
// NOT shipped (turn cancellation / phase-04 is paused), so it is intentionally absent.

// Opaque backend progress keys — each maps 1:1 to a real code position (see the
// contract's phase key table). Never rendered raw; the frontend owns the i18n
// labels (own the keys: unknown keys must be ignored silently).
export type PhaseKey =
  | 'received'
  | 'routing'
  | 'route_decided'
  | 'compacting_history'
  | 'intake_check'
  | 'hotel_search'
  | 'tool_start'
  | 'tool_end'
  | 'itinerary_build'
  | 'routing_legs'
  | 'persisting'
  | 'generating'

// One entry of the growing progress list shown while a turn streams.
export interface TurnPhase {
  key: PhaseKey
  at: number // epoch seconds from the backend
}

export type StreamEvent =
  // `tool` present on hotel_search/tool_start/tool_end; `route` on route_decided.
  | { event: 'phase'; data: { key: PhaseKey; at: number; tool?: string; route?: string } }
  | { event: 'delta'; data: { text: string } } // only on the agent-chat branch
  | { event: 'reset'; data: { reason: string } } // discard buffered delta text
  | { event: 'final'; data: PlannerChatResponse } // same dict as POST /planner_chat
  | { event: 'error'; data: { detail: string } }

// Every stream ends with exactly one of these terminal events.
export type TerminalStreamEvent = Extract<StreamEvent, { event: 'final' | 'error' }>
