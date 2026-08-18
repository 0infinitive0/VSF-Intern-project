/**
 * map-sync-id.ts — the shared id vocabulary between the map (markers, route
 * segment endpoints), the timeline (TimelineItem), and the hotel list
 * (HotelOptionCard). Every place that needs to say "this is the same place
 * as that card" must go through these functions instead of inventing its
 * own key shape — otherwise hover/click sync between the map and the list
 * silently drifts apart the first time someone changes one side.
 */
import type { DayItem, HotelOption, SuggestedPlace } from '../types'

/**
 * Sync id for one itinerary item. Real attractions (openable, has a
 * reference_id) use their reference_id directly — the same id
 * Place Detail Focus Mode opens with. Non-openable items (meals, transport,
 * anything without reference_type 'Attraction' + reference_id) get a
 * synthetic per-position key so they can still be hovered/highlighted on the
 * map even though they don't open a detail panel.
 */
export function itemSyncId(dayNumber: number, item: DayItem, index: number): string {
  if (item.reference_type === 'Attraction' && item.reference_id) return item.reference_id
  return `day-${dayNumber}-item-${index}`
}

/** Sync id for one hotel option card — mirrors the card's own `key={hotel.id ?? hotel.index}`. */
export function hotelOptionSyncId(hotel: HotelOption): string {
  return String(hotel.id ?? hotel.index)
}

/** The hotel pin shown for the workspace overview — no card, no hover target on the list side. */
export const TRIP_HOTEL_SYNC_KEY = 'hotel'

/** Sync id for a chatbot-suggested place pin — prefixed so it can never
 * collide with a real itinerary item's `reference_id` (itemSyncId above). */
export function suggestedPlaceSyncId(place: SuggestedPlace): string {
  return `suggested-${place.id}`
}
