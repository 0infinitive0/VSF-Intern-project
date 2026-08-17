/**
 * test-fixtures.ts — builders for wire payloads in tests.
 *
 * Wire types are generated from the backend's OpenAPI schema now, so they are
 * exact: a `HotelOption` literal must carry all 20-odd fields, not the three a
 * given test cares about. Spelling those out per fixture would bury the one
 * value under test in noise and make every backend field addition a
 * find-and-replace across the suite.
 *
 * Each builder fills the required shape and takes an override object, so a test
 * states only what it is actually about. Deliberately NOT `as HotelOption` on a
 * partial literal: that is the exact type lie this phase removed — a test that
 * lies about the payload shape stops testing the contract.
 */

import type {
  Day,
  DayItem,
  HotelDetail,
  HotelOption,
  IntakeStatus,
  SessionSummary,
  TripPlan,
} from './types'

export function hotelOption(overrides: Partial<HotelOption> = {}): HotelOption {
  return {
    index: 1,
    id: 'hotel-1',
    name: 'Hotel A',
    star_rating: null,
    description: null,
    matched_rooms: [],
    average_nightly_price: null,
    total_stay_price: null,
    stay_night_count: null,
    currency: null,
    coordinates: null,
    address: null,
    area_name: null,
    image_url: null,
    amenities: [],
    display_amenities: [],
    review_score: null,
    review_count: null,
    match_score: null,
    match_reasons: [],
    city: null,
    ...overrides,
  }
}

export function dayItem(overrides: Partial<DayItem> = {}): DayItem {
  return {
    order_index: 0,
    start_time: null,
    end_time: null,
    activity: null,
    kind: null,
    reference_type: null,
    reference_id: null,
    coordinates: null,
    image_url: null,
    route_to_next: null,
    route_from_hotel: null,
    ...overrides,
  }
}

export function day(overrides: Partial<Day> = {}): Day {
  return { day_number: 1, theme: '', items: [], ...overrides }
}

export function tripPlan(overrides: Partial<TripPlan> = {}): TripPlan {
  return {
    status: 'Draft',
    destination: null,
    duration_days: 1,
    start_date: null,
    end_date: null,
    number_of_adults: null,
    budget: null,
    budget_currency: 'VND',
    hotel: null,
    days: [],
    adjustments: [],
    ...overrides,
  }
}

export function intakeStatus(overrides: Partial<IntakeStatus> = {}): IntakeStatus {
  return {
    destination: null,
    duration: null,
    start_date: null,
    end_date: null,
    people: null,
    preferences: [],
    companions: null,
    pace: null,
    day_rhythm: [],
    notes: '',
    available_destinations: [],
    budget_options: [],
    min_price: null,
    max_price: null,
    budget_skipped: false,
    missing: [],
    ...overrides,
  }
}

export function sessionSummary(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    session_id: 'session-1',
    title: null,
    destination: null,
    duration_days: null,
    status: 'draft',
    created_at: null,
    updated_at: null,
    thumbnail_url: null,
    ...overrides,
  }
}

export function hotelDetail(overrides: Partial<HotelDetail> = {}): HotelDetail {
  return {
    id: 'hotel-1',
    name: 'Hotel A',
    star_rating: null,
    description: null,
    address: null,
    city: null,
    area_name: null,
    location_highlight: null,
    coordinates: null,
    image_url: null,
    images: null,
    amenities: null,
    amenity_groups: null,
    awards: null,
    warnings: null,
    review_score: null,
    review_count: null,
    category_scores: null,
    check_in_time: null,
    check_in_until: null,
    check_out_time: null,
    reception_open_until: null,
    nearby_attractions: null,
    nearby_essentials: null,
    lowest_price: null,
    currency: null,
    rooms: [],
    source_platform: null,
    source_url: null,
    ...overrides,
  }
}
