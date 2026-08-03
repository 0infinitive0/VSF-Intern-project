/**
 * types.ts — shared shapes for the chat/trip-plan contract.
 * Verified against src/services/trip_formatter.py:238-345 (backend payload field names).
 */

export interface Suggestion {
  label: string
  value: string
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
}

export interface DayItem {
  order_index: number
  start_time: string | null
  end_time: string | null
  activity: string
  kind?: string | null
  reference_type?: string | null
  reference_id?: string | null
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
  // WKT/string form from the backend (src/models/schemas.py:110), not {lat,lng} — do
  // not restructure it; the map phase is deferred and does not consume this field.
  coordinates?: string | null
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
}

// Snapshot of what the intake gate has collected so far (src/models/schemas.py:127-138).
// Populated during `intake`/`hotel_options` stages, before `trip_plan` exists (a hotel
// must be picked before the backend builds `trip_data` — see trip_planner.py's
// _generate_and_save_itinerary, only called from the select_hotel tool).
export interface IntakeStatus {
  destination: string | null
  duration: string | null
  start_date: string | null
  end_date: string | null
  people: string | null // formatted string, e.g. "2 người" — not a bare count
  missing: string[]
}

export interface ChatState {
  sessionId: string | null
  messages: ChatMessage[]
  suggestions: Suggestion[]
  hotelOptions: HotelOption[]
  tripPlan: TripPlan | null
  intake: IntakeStatus | null
  pending: boolean
  elapsedMs: number
  error: string | null
}

export interface PlannerChatResponse {
  session_id: string
  reply: string
  suggestions: Suggestion[]
  stage: Stage
  hotel_options: HotelOption[]
  trip_plan: TripPlan | null
  intake?: IntakeStatus | null
}
