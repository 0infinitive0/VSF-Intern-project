/**
 * mock/server.js — ~60-line node:http mock for parallel development.
 *
 * Replays fixtures for the four contract endpoints:
 *   POST /api/v1/chat/session
 *   POST /api/v1/planner_chat
 *   GET  /api/v1/chat/:sid/plan
 *   DELETE /api/v1/chat/:sid
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
        { order_index: 1, start_time: '08:00', end_time: '09:30', activity: 'Ăn sáng tại nhà hàng khách sạn', kind: 'breakfast' },
        { order_index: 2, start_time: '10:00', end_time: '12:00', activity: 'Tắm biển Mỹ Khê', kind: 'attraction' },
        { order_index: 3, start_time: '12:30', end_time: '13:30', activity: 'Ăn trưa hải sản tươi Bến Thành Đà Nẵng', kind: 'lunch' },
        { order_index: 4, start_time: '15:00', end_time: '17:30', activity: 'Tham quan Bảo tàng Điêu khắc Chăm', kind: 'attraction' },
        { order_index: 5, start_time: '19:00', end_time: '21:00', activity: 'Dạo cầu Rồng, ngắm phun lửa cuối tuần', kind: 'evening' },
      ],
    },
    {
      day_number: 2,
      theme: 'Núi Ngũ Hành Sơn & Hội An cổ kính',
      items: [
        { order_index: 1, start_time: '07:30', end_time: '09:00', activity: 'Ăn sáng, check-in xe máy', kind: 'breakfast' },
        { order_index: 2, start_time: '09:30', end_time: '12:00', activity: 'Leo núi Ngũ Hành Sơn, thăm động Huyền Không', kind: 'attraction' },
        { order_index: 3, start_time: '12:30', end_time: '14:00', activity: 'Ăn trưa Cao Lầu Hội An', kind: 'lunch' },
        { order_index: 4, start_time: '14:30', end_time: '17:30', activity: 'Tham quan phố cổ Hội An, thả đèn hoa đăng', kind: 'attraction' },
        { order_index: 5, start_time: '19:00', end_time: '21:00', activity: 'Ăn tối Cơm Gà Bà Buội nổi tiếng', kind: 'dinner' },
      ],
    },
    {
      day_number: 3,
      theme: 'Bà Nà Hills & chia tay',
      items: [
        { order_index: 1, start_time: '08:00', end_time: '09:00', activity: 'Ăn sáng, trả phòng', kind: 'breakfast' },
        { order_index: 2, start_time: '09:30', end_time: '15:30', activity: 'Cáp treo Bà Nà Hills, Cầu Vàng, Fantasy Park', kind: 'attraction' },
        { order_index: 3, start_time: '16:00', end_time: '17:00', activity: 'Mua quà lưu niệm, chụp ảnh cầu Sông Hàn', kind: 'attraction' },
        { order_index: 4, start_time: '18:00', end_time: '19:30', activity: 'Ăn tối chia tay, đặc sản bánh mì Đà Nẵng', kind: 'dinner' },
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
  },
  {
    index: 2,
    id: 'hotel-2',
    name: 'Mường Thanh Luxury Đà Nẵng',
    star_rating: 4,
    description: 'Khách sạn 4 sao trung tâm, gần cầu Rồng, phù hợp gia đình.',
    matched_rooms: ['Deluxe City View', 'Family Suite'],
  },
  {
    index: 3,
    id: 'hotel-3',
    name: 'Fusion Maia Đà Nẵng',
    star_rating: 5,
    description: 'All-spa-inclusive resort yên tĩnh, spa vô hạn mỗi ngày.',
    matched_rooms: ['Pool Villa', 'Garden Pool Suite'],
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
    hotel_options: null,
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
    hotel_options: null,
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
    hotel_options: null,
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
    hotel_options: null,
    trip_plan: { ...TRIP_PLAN, status: 'Modified' },
  },
  6: {
    reply: '🎉 Lịch trình của bạn đã được chốt!\n\nChúc bạn có chuyến đi Đà Nẵng thật tuyệt vời! Nếu cần hỗ trợ thêm, hãy bắt đầu hội thoại mới nhé.',
    suggestions: [],
    stage: 'finalized',
    hotel_options: null,
    trip_plan: { ...TRIP_PLAN, status: 'Finalized' },
  },
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
      hotel_options: null,
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

  // DELETE /api/v1/chat/:sid
  if (req.method === 'DELETE' && path.match(/^\/api\/v1\/chat\/[^/]+$/)) {
    const sid = path.split('/')[4]
    delete turnCounters[sid]
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*' })
    res.end()
    return
  }

  // 404 fallthrough
  json(res, 404, { detail: 'Not found' })
})

server.listen(PORT, () => {
  console.log(`\n🌿 VSF Trip Planner mock server running at http://localhost:${PORT}`)
  console.log('   Endpoints: POST /api/v1/chat/session | POST /api/v1/planner_chat')
  console.log('              GET  /api/v1/chat/:sid/plan | DELETE /api/v1/chat/:sid')
  console.log('   Turn 3 (hotel options) and turn 4 (plan) have a 3-second delay')
  console.log('   to exercise the pending spinner.\n')
})
