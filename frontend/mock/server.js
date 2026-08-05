/**
 * mock/server.js — node:http mock for parallel development.
 *
 * Replays fixtures for all eight contract endpoints (docs/chat_api_contract.md):
 *   POST   /api/v1/chat/session
 *   POST   /api/v1/planner_chat
 *   GET    /api/v1/chat/:sid/plan
 *   DELETE /api/v1/chat/:sid
 *   GET    /api/v1/hotels/:id            (Phase 3, mocked here for frontend Phase 8)
 *   GET    /api/v1/attractions/:id       (Phase 3, mocked here for frontend Phase 9)
 *   GET    /api/v1/chat/sessions         (Phase 4, mocked here for frontend Phase 5)
 *   GET    /api/v1/chat/:sid/restore     (Phase 4, mocked here for frontend Phase 5)
 *
 * The planner_chat fixture walks through a scripted conversation:
 *   turn 1 → intake (guided question with chips)
 *   turn 2 → intake (budget question)
 *   turn 3 → hotel_options (3 hotels, 3s deliberate delay)
 *   turn 4 → planned (trip_plan populated, 3s delay)
 *   turn 5 → modified
 *   turn 6 → finalized
 *   turn 7+ → error bubble (to exercise that path)
 *
 * Start:  node mock/server.js   (or npm run mock)
 */

import { createServer } from 'node:http'

const PORT = 8000
const SESSION_ID = 'mock-session-00000000-0000-0000-0000-000000000001'

// ── Fixtures ─────────────────────────────────────────────────────────────────

const TRIP_PLAN = {
  status: 'Draft',
  destination: 'Đà Nẵng',
  duration_days: 3,
  start_date: '2026-10-12T00:00:00',
  end_date: '2026-10-14T00:00:00',
  number_of_adults: 2,
  hotel: {
    id: 'hotel-1',
    name: 'Vinpearl Resort & Spa Đà Nẵng',
    star_rating: 5,
    description: 'Resort 5 sao ven biển Mỹ Khê, hồ bơi vô cực nhìn ra biển.',
    matched_rooms: ['Superior Ocean View', 'Deluxe Pool Access'],
    coordinates: '16.0544,108.2022',
  },
  days: [
    {
      day_number: 1,
      theme: 'Khám phá bãi biển Mỹ Khê',
      items: [
        // route_from_hotel: identical-coordinates case — {0, 0, "", profile: null},
        // not null. route_to_next: full driving-traffic route with a real polyline.
        {
          order_index: 1, start_time: '08:00', end_time: '09:30', activity: 'Ăn sáng tại nhà hàng khách sạn', kind: 'breakfast',
          coordinates: '16.0544,108.2022',
          route_from_hotel: { distance_km: 0, duration_mins: 0, polyline: '', profile: null },
          route_to_next: { distance_km: 5.8, duration_mins: 13.4, polyline: '_s~`BwflsSvBgc@fO_q@vGo}@kC_jAjHseA', profile: 'driving-traffic' },
        },
        // route_to_next: walking profile, short leg.
        {
          order_index: 2, start_time: '10:00', end_time: '12:00', activity: 'Tắm biển Mỹ Khê', kind: 'attraction',
          coordinates: '16.0490,108.2493',
          route_to_next: { distance_km: 1.9, duration_mins: 22.0, polyline: 'gq}`BcmusSwLjqB', profile: 'walking' },
        },
        // route_to_next: null — routing lookup failed/timed out; frontend must fall
        // back to a straight line between this item and the next.
        {
          order_index: 3, start_time: '12:30', end_time: '13:30', activity: 'Ăn trưa hải sản tươi Bến Thành Đà Nẵng', kind: 'lunch',
          coordinates: '16.0512,108.2310',
          route_to_next: null,
        },
        {
          order_index: 4, start_time: '15:00', end_time: '17:30', activity: 'Tham quan Bảo tàng Điêu khắc Chăm', kind: 'attraction',
          coordinates: '16.0678,108.2208',
          route_to_next: { distance_km: 2.6, duration_mins: 7.5, polyline: 'wfaaB_{osSfJwLrNoKrN{O', profile: 'driving-traffic' },
        },
        {
          order_index: 5, start_time: '19:00', end_time: '21:00', activity: 'Dạo cầu Rồng, ngắm phun lửa cuối tuần', kind: 'evening',
          coordinates: '16.0610,108.2277',
          route_to_next: { distance_km: 6.1, duration_mins: 15.8, polyline: 'g|_aBcfqsSnKbo@nK~p@jHnd@zEvV', profile: 'driving-traffic' },
        },
      ],
    },
    {
      day_number: 2,
      theme: 'Núi Ngũ Hành Sơn & Hội An cổ kính',
      items: [
        // route_from_hotel: null — the common post-round-trip state (ITEM_RPC_FIELDS
        // does not persist route_from_hotel; see docs/chat_api_contract.md), not a
        // routing failure.
        {
          order_index: 1, start_time: '07:30', end_time: '09:00', activity: 'Ăn sáng, check-in xe máy', kind: 'breakfast',
          coordinates: '16.0540,108.2030',
          route_from_hotel: null,
        },
        {
          order_index: 2, start_time: '09:30', end_time: '12:00', activity: 'Leo núi Ngũ Hành Sơn, thăm động Huyền Không', kind: 'attraction',
          coordinates: '15.9975,108.2630',
        },
        {
          order_index: 3, start_time: '12:30', end_time: '14:00', activity: 'Ăn trưa Cao Lầu Hội An', kind: 'lunch',
          coordinates: '15.8794,108.3350',
        },
        {
          order_index: 4, start_time: '14:30', end_time: '17:30', activity: 'Tham quan phố cổ Hội An, thả đèn hoa đăng', kind: 'attraction',
          coordinates: '15.8801,108.3380',
        },
        {
          order_index: 5, start_time: '19:00', end_time: '21:00', activity: 'Ăn tối Cơm Gà Bà Buội nổi tiếng', kind: 'dinner',
          coordinates: '15.8785,108.3357',
        },
      ],
    },
    {
      day_number: 3,
      theme: 'Bà Nà Hills & chia tay',
      items: [
        { order_index: 1, start_time: '08:00', end_time: '09:00', activity: 'Ăn sáng, trả phòng', kind: 'breakfast',
          coordinates: '16.0544,108.2022',
          route_from_hotel: null,
        },
        { order_index: 2, start_time: '09:30', end_time: '15:30', activity: 'Cáp treo Bà Nà Hills, Cầu Vàng, Fantasy Park', kind: 'attraction',
          coordinates: '15.9977,107.9967',
        },
        { order_index: 3, start_time: '16:00', end_time: '17:00', activity: 'Mua quà lưu niệm, chụp ảnh cầu Sông Hàn', kind: 'attraction',
          coordinates: '16.0678,108.2245',
        },
        { order_index: 4, start_time: '18:00', end_time: '19:30', activity: 'Ăn tối chia tay, đặc sản bánh mì Đà Nẵng', kind: 'dinner',
          coordinates: '16.0600,108.2260',
        },
      ],
    },
  ],
  adjustments: [
    'Thêm tour đêm phố cổ Hội An ngày 2 theo yêu cầu.',
    'Chuyển bữa trưa ngày 3 sang Bà Nà Hills để tiết kiệm di chuyển.',
  ],
}

const HOTEL_OPTIONS = [
  {
    index: 1,
    id: 'hotel-1',
    name: 'Vinpearl Resort & Spa Đà Nẵng',
    star_rating: 5,
    description: 'Resort 5 sao ven biển Mỹ Khê, hồ bơi vô cực, nhà hàng fine-dining.',
    matched_rooms: ['Superior Ocean View', 'Deluxe Pool Access'],
    average_nightly_price: 3200000,
    total_stay_price: 9600000,
    stay_night_count: 3,
    currency: 'VND',
    coordinates: '16.0544,108.2022',
    address: '5 Trường Sa, Bắc Mỹ Phú',
    area_name: 'Mỹ Khê',
    image_url: 'https://images.unsplash.com/photo-1571003123894-1f0594d2b5d9?w=800',
    amenities: ['Hồ bơi vô cực', 'Bãi biển riêng', 'Spa', 'Gym 24/7'],
    review_score: 8.9,
    review_count: 1284,
    match_score: 0.96,
    match_reasons: [
      { code: 'budget_fit', value: 0.39 },
      { code: 'high_rating', value: 8.9 },
      { code: 'amenity_match', value: 'Hồ bơi vô cực' },
    ],
  },
  {
    index: 2,
    id: 'hotel-2',
    name: 'Mường Thanh Luxury Đà Nẵng',
    star_rating: 4,
    description: 'Khách sạn 4 sao trung tâm, gần cầu Rồng, phù hợp gia đình.',
    matched_rooms: ['Deluxe City View', 'Family Suite'],
    average_nightly_price: 1450000,
    total_stay_price: 4350000,
    stay_night_count: 3,
    currency: 'VND',
    coordinates: '16.0668,108.2223',
    address: '25 Phạm Văn Đồng',
    area_name: 'Sơn Trà',
    image_url: 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=800',
    amenities: ['Hồ bơi ngoài trời', 'Nhà hàng buffet', 'Đưa đón sân bay'],
    review_score: 8.1,
    review_count: 903,
    match_score: 0.84,
    match_reasons: [
      { code: 'budget_fit', value: 0.82 },
      { code: 'high_rating', value: 8.1 },
    ],
  },
  {
    index: 3,
    id: 'hotel-3',
    name: 'Fusion Maia Đà Nẵng',
    star_rating: 5,
    description: 'All-spa-inclusive resort yên tĩnh, spa vô hạn mỗi ngày.',
    matched_rooms: ['Pool Villa', 'Garden Pool Suite'],
    average_nightly_price: 4100000,
    total_stay_price: 12300000,
    stay_night_count: 3,
    currency: 'VND',
    coordinates: '16.0330,108.2517',
    address: '278 Võ Nguyên Giáp',
    area_name: 'Ngũ Hành Sơn',
    image_url: null, // exercises the missing-image placeholder path
    amenities: ['Spa vô hạn', 'Villa riêng có hồ bơi', 'Yoga buổi sáng'],
    review_score: 9.2,
    review_count: 541,
    match_score: 0.91,
    match_reasons: [
      { code: 'high_rating', value: 9.2 },
      { code: 'amenity_match', value: 'Villa riêng có hồ bơi' },
    ],
  },
]

// ── Fixtures for the four new endpoints (Phase 3/4 backend, mocked in Phase 1) ─────

const HOTEL_DETAILS = {
  'hotel-1': {
    id: 'hotel-1',
    name: 'Vinpearl Resort & Spa Đà Nẵng',
    star_rating: 5,
    description: 'Resort 5 sao ven biển Mỹ Khê, hồ bơi vô cực nhìn ra biển, spa 5 sao.',
    address: '5 Trường Sa, Bắc Mỹ Phú', city: 'Đà Nẵng', area_name: 'Mỹ Khê',
    location_highlight: 'Ngay bãi biển Mỹ Khê, 10 phút tới trung tâm',
    coordinates: '16.0544,108.2022',
    image_url: 'https://images.unsplash.com/photo-1571003123894-1f0594d2b5d9?w=1200',
    images: [
      'https://images.unsplash.com/photo-1571003123894-1f0594d2b5d9?w=1200',
      'https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=1200',
    ],
    amenities: ['Hồ bơi vô cực', 'Bãi biển riêng', 'Spa', 'Gym 24/7'],
    amenity_groups: {
      'Hồ bơi & Spa': ['Hồ bơi vô cực', 'Spa', 'Xông hơi'],
      'Ăn uống': ['Nhà hàng fine-dining', 'Bar trên tầng thượng'],
    },
    review_score: 8.9, review_count: 1284,
    category_scores: { 'Vị trí': 9.4, 'Sạch sẽ': 9.0, 'Dịch vụ': 8.7 },
    check_in_time: '14:00', check_in_until: '22:00',
    check_out_time: '12:00', reception_open_until: '23:59',
    nearby_attractions: ['Bãi biển Mỹ Khê (2 phút đi bộ)', 'Cầu Rồng (10 phút lái xe)'],
    nearby_essentials: ['Vinmart+ (5 phút đi bộ)', 'Nhà thuốc Long Châu (7 phút đi bộ)'],
    lowest_price: 2200000, currency: 'VND',
    rooms: [
      {
        id: 'room-1a', name: 'Superior Ocean View', bed_description: '1 giường đôi lớn',
        room_size_sqm: 32, max_guests: 2, view: 'Hướng biển',
        room_facilities: ['Ban công riêng', 'Minibar', 'Điều hòa'],
        images: ['https://images.unsplash.com/photo-1590490360182-c33d57733427?w=1200'],
        price: { amount: 2200000, currency: 'VND', check_in_date: '2026-10-12', check_out_date: '2026-10-14', sold_out: false, package_details: null },
      },
      {
        id: 'room-1b', name: 'Deluxe Pool Access', bed_description: '2 giường đơn',
        room_size_sqm: 38, max_guests: 3, view: 'Hướng hồ bơi',
        room_facilities: ['Lối ra hồ bơi riêng', 'Bồn tắm', 'Minibar'],
        images: [],
        price: { amount: 3600000, currency: 'VND', check_in_date: '2026-10-12', check_out_date: '2026-10-14', sold_out: true, package_details: 'Bao gồm bữa sáng buffet' },
      },
    ],
  },
}

const ATTRACTION_DETAILS = {
  'attraction-my-khe': {
    id: 'attraction-my-khe', name: 'Bãi biển Mỹ Khê', description: 'Một trong những bãi biển đẹp nhất hành tinh theo bình chọn của Forbes, cát trắng mịn và sóng êm.',
    category: 'Biển', is_tour: false, estimated_duration_minutes: 120,
    opening_time: '05:00', closing_time: '22:00',
    ticket_price_adult: 0, ticket_price_child: 0,
    rating: 4.6, review_count: 892,
    coordinates: '16.0490,108.2493',
    images: ['https://images.unsplash.com/photo-1519046904884-53103b34b206?w=1200'],
  },
  'attraction-ba-na': {
    id: 'attraction-ba-na', name: 'Bà Nà Hills', description: 'Khu du lịch trên núi với Cầu Vàng, ga cáp treo đạt kỷ lục Guinness, Fantasy Park.',
    category: 'Tour', is_tour: true, estimated_duration_minutes: 360,
    opening_time: '07:30', closing_time: '21:30',
    ticket_price_adult: 850000, ticket_price_child: 700000,
    rating: 4.5, review_count: 2310,
    coordinates: '15.9977,107.9967',
    images: ['https://images.unsplash.com/photo-1583417319070-4a69db38a482?w=1200'],
  },
}

const SESSIONS = [
  {
    session_id: SESSION_ID,
    title: 'Đà Nẵng – Hội An 4N3Đ',
    destination: 'Đà Nẵng', duration_days: 3,
    status: 'completed',
    created_at: '2026-08-01T09:12:00Z', updated_at: '2026-08-01T09:40:00Z',
    thumbnail_url: 'https://images.unsplash.com/photo-1571003123894-1f0594d2b5d9?w=400',
  },
  {
    session_id: 'mock-session-00000000-0000-0000-0000-000000000002',
    title: 'Nha Trang cuối tuần',
    destination: 'Nha Trang', duration_days: 2,
    status: 'draft',
    created_at: '2026-07-28T14:05:00Z', updated_at: '2026-07-28T14:20:00Z',
    thumbnail_url: null,
  },
]

// Intake snapshot served on the intake turns so the IntakeParametersForm has
// real lists to render (available_destinations / budget_options mirror the
// backend's Phase 2 schema).
const INTAKE_EMPTY = {
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
  available_destinations: ['Đà Nẵng', 'Nha Trang', 'Hội An'],
  budget_options: [
    'Tiết kiệm (dưới 800,000 VND/đêm)',
    'Tầm trung (800,000 - 2,500,000 VND/đêm)',
    'Cao cấp (trên 2,500,000 VND/đêm)',
    'Bỏ qua, không cần lọc theo giá',
  ],
  missing: ['destination', 'duration', 'start_date', 'people'],
}

// Scripted conversation turns (keyed by turn index 1-based)
const TURNS = {
  1: {
    reply: 'Chào bạn! Tuyệt vời, Đà Nẵng là điểm đến tuyệt vời! 🌊\n\nBạn dự định đi trong bao nhiêu ngày và đi cùng ai?',
    suggestions: [
      { label: '3 ngày 2 đêm', value: '3 ngày 2 đêm' },
      { label: '5 ngày 4 đêm', value: '5 ngày 4 đêm' },
      { label: 'Chỉ cuối tuần (2 ngày)', value: '2 ngày 1 đêm' },
    ],
    stage: 'intake',
    hotel_options: [],
    trip_plan: null,
    intake: INTAKE_EMPTY,
  },
  2: {
    reply: 'Thông tin tuyệt vời! 3 ngày 2 người là lý tưởng để khám phá Đà Nẵng — Hội An và Bà Nà Hills.\n\nBạn có ưu tiên phong cách lưu trú nào không?',
    suggestions: [
      { label: '⭐⭐⭐⭐⭐ Sang trọng (5 sao)', value: '5 sao' },
      { label: '⭐⭐⭐⭐ Tiêu chuẩn (4 sao)', value: '4 sao' },
      { label: '💰 Tiết kiệm / Budget', value: 'budget' },
    ],
    stage: 'intake',
    hotel_options: [],
    trip_plan: null,
    intake: {
      ...INTAKE_EMPTY,
      destination: 'Đà Nẵng',
      missing: ['duration', 'start_date', 'people'],
    },
  },
  3: {
    reply: 'Dựa trên sở thích của bạn, tôi tìm được 3 khách sạn phù hợp tại Đà Nẵng:\n\nHãy chọn khách sạn bạn muốn và tôi sẽ lên lịch trình chi tiết ngay!',
    suggestions: [
      { label: '1. Vinpearl Resort & Spa Đà Nẵng', value: '1' },
      { label: '2. Mường Thanh Luxury Đà Nẵng', value: '2' },
      { label: '3. Fusion Maia Đà Nẵng', value: '3' },
    ],
    stage: 'hotel_options',
    hotel_options: HOTEL_OPTIONS,
    trip_plan: null,
    _delay: 3000,
  },
  4: {
    reply: 'Tuyệt vời! Bạn đã chọn Vinpearl Resort & Spa Đà Nẵng ⭐⭐⭐⭐⭐\n\nTôi đã lên lịch trình 3 ngày chi tiết cho bạn. Xem ở bảng bên phải nhé! 🗺️\n\nBạn có muốn điều chỉnh gì không? Ví dụ: thêm tour, thay đổi nhà hàng hoặc thêm hoạt động.',
    suggestions: [
      { label: '✅ Chốt lịch trình này', value: 'chốt lịch trình' },
      { label: '✏️ Thêm tour đêm Hội An', value: 'thêm tour đêm Hội An ngày 2' },
      { label: '🍜 Đổi nhà hàng ăn trưa', value: 'đổi nhà hàng ăn trưa ngày 1' },
    ],
    stage: 'planned',
    hotel_options: [],
    trip_plan: TRIP_PLAN,
    _delay: 3000,
  },
  5: {
    reply: 'Đã thêm tour đêm phố cổ Hội An vào ngày 2! 🏮\n\nLịch trình đã được cập nhật. Bạn có muốn chỉnh thêm gì không?',
    suggestions: [
      { label: '✅ Chốt lịch trình này', value: 'chốt lịch trình' },
      { label: '🔄 Thay đổi khác', value: 'tôi muốn thay đổi thêm' },
    ],
    stage: 'modified',
    hotel_options: [],
    trip_plan: { ...TRIP_PLAN, status: 'Modified' },
  },
  6: {
    reply: '🎉 Lịch trình của bạn đã được chốt!\n\nChúc bạn có chuyến đi Đà Nẵng thật tuyệt vời! Nếu cần hỗ trợ thêm, hãy bắt đầu hội thoại mới nhé.',
    suggestions: [],
    stage: 'finalized',
    hotel_options: [],
    trip_plan: { ...TRIP_PLAN, status: 'Finalized' },
  },
}

const SESSION_RESTORE = {
  session_id: SESSION_ID,
  messages: [
    { role: 'user', text: 'Tôi muốn đi Đà Nẵng 3 ngày', stage: 'intake', at: '2026-08-01T09:12:00Z' },
    { role: 'ai', text: TURNS[1].reply, stage: 'intake', at: '2026-08-01T09:12:05Z' },
    { role: 'user', text: '3 ngày 2 đêm, đi 2 người', stage: 'intake', at: '2026-08-01T09:13:00Z' },
    { role: 'ai', text: TURNS[4].reply, stage: 'planned', at: '2026-08-01T09:14:30Z' },
  ],
  suggestions: TURNS[4].suggestions,
  stage: 'planned',
  hotel_options: [],
  trip_plan: TRIP_PLAN,
  intake: { ...INTAKE_EMPTY, destination: 'Đà Nẵng', missing: [] },
}

// ── Turn counter (in-memory per session for mock) ─────────────────────────────

const turnCounters = {}

// ── JSON helpers ──────────────────────────────────────────────────────────────

function json(res, status, body) {
  const payload = JSON.stringify(body, null, 2)
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  })
  res.end(payload)
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString() || '{}'))
      } catch {
        resolve({})
      }
    })
  })
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

// ── Router ────────────────────────────────────────────────────────────────────

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`)
  const path = url.pathname

  // CORS preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    })
    res.end()
    return
  }

  // POST /api/v1/chat/session
  if (req.method === 'POST' && path === '/api/v1/chat/session') {
    json(res, 200, {
      session_id: SESSION_ID,
      created_at: new Date().toISOString(),
    })
    return
  }

  // POST /api/v1/planner_chat
  if (req.method === 'POST' && path === '/api/v1/planner_chat') {
    const body = await readBody(req)
    const sid = body.session_id || SESSION_ID

    if (!turnCounters[sid]) turnCounters[sid] = 0
    turnCounters[sid]++
    const turn = turnCounters[sid]

    const fixture = TURNS[turn] || {
      reply: 'SYSTEM ERROR: Lịch trình đã hoàn tất. Hãy bắt đầu hội thoại mới để lên kế hoạch chuyến đi tiếp theo!',
      suggestions: [],
      stage: 'error',
      hotel_options: [],
      trip_plan: null,
    }

    if (fixture._delay) await sleep(fixture._delay)

    const { _delay, ...response } = fixture
    json(res, 200, {
      session_id: sid,
      ...response,
    })
    return
  }

  // GET /api/v1/chat/:sid/plan
  if (req.method === 'GET' && path.match(/^\/api\/v1\/chat\/[^/]+\/plan$/)) {
    const sid = path.split('/')[4]
    if (sid === SESSION_ID && turnCounters[sid] >= 4) {
      json(res, 200, { trip_plan: TRIP_PLAN })
    } else {
      json(res, 404, { detail: 'No plan yet' })
    }
    return
  }

  // GET /api/v1/chat/sessions
  if (req.method === 'GET' && path === '/api/v1/chat/sessions') {
    json(res, 200, { sessions: SESSIONS })
    return
  }

  // GET /api/v1/chat/:sid/restore
  if (req.method === 'GET' && path.match(/^\/api\/v1\/chat\/[^/]+\/restore$/)) {
    const sid = path.split('/')[4]
    if (sid === SESSION_ID) {
      json(res, 200, SESSION_RESTORE)
    } else {
      json(res, 404, { detail: 'No saved session' })
    }
    return
  }

  // DELETE /api/v1/chat/:sid
  if (req.method === 'DELETE' && path.match(/^\/api\/v1\/chat\/[^/]+$/)) {
    const sid = path.split('/')[4]
    delete turnCounters[sid]
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*' })
    res.end()
    return
  }

  // GET /api/v1/hotels/:id
  if (req.method === 'GET' && path.match(/^\/api\/v1\/hotels\/[^/]+$/)) {
    const id = path.split('/')[4]
    const detail = HOTEL_DETAILS[id]
    if (detail) {
      json(res, 200, detail)
    } else {
      json(res, 404, { detail: 'Hotel not found' })
    }
    return
  }

  // GET /api/v1/attractions/:id
  if (req.method === 'GET' && path.match(/^\/api\/v1\/attractions\/[^/]+$/)) {
    const id = path.split('/')[4]
    const detail = ATTRACTION_DETAILS[id]
    if (detail) {
      json(res, 200, detail)
    } else {
      json(res, 404, { detail: 'Attraction not found' })
    }
    return
  }

  // 404 fallthrough
  json(res, 404, { detail: 'Not found' })
})

server.listen(PORT, () => {
  console.log(`\n🌿 VSF Trip Planner mock server running at http://localhost:${PORT}`)
  console.log('   Endpoints: POST /api/v1/chat/session | POST /api/v1/planner_chat')
  console.log('              GET  /api/v1/chat/:sid/plan | DELETE /api/v1/chat/:sid')
  console.log('              GET  /api/v1/hotels/:id | GET /api/v1/attractions/:id')
  console.log('              GET  /api/v1/chat/sessions | GET /api/v1/chat/:sid/restore')
  console.log(`   Hotel detail: hotel-1 | Attraction details: attraction-my-khe, attraction-ba-na`)
  console.log('   Turn 3 (hotel options) and turn 4 (plan) have a 3-second delay')
  console.log('   to exercise the pending spinner.\n')
})
