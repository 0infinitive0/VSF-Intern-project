# Migration note — UI swapped to the dc-runtime prototype

**Nếu bạn vừa pull nhánh này và thấy `frontend/` hoàn toàn khác hôm qua, đọc file này trước.**

## Chuyện gì đã xảy ra

Toàn bộ code React cũ (`src/App.tsx`, `src/components/*`, `src/api/chat-client.ts`, `src/hooks/*`, ...) đã được
thay bằng một bộ UI khác — định dạng `.dc.html` "Design Component" (xem `README.md` trong thư mục này để hiểu
kiến trúc mới). Lý do: giao diện mới có thiết kế/thẩm mỹ tốt hơn bản React cũ.

**Không có gì bị mất** — code cũ vẫn còn nguyên:
- Tag `pre-ui-swap-frontend-2026-08-05` trên commit trước khi đổi.
- Branch `dev` (nhánh này tách ra từ đó, chưa merge lại) và `main` đều chưa đụng tới.

## Điều quan trọng nhất: UI mới CHƯA nối được backend thật

Bản `.dc.html` này 100% chạy bằng mock data (`scripts/constants/mock-data.js`), **không gọi** FastAPI/LangGraph
backend thật. Chat không gửi tin nhắn đi đâu cả, chọn khách sạn không lưu server-side, lịch trình là dữ liệu giả lập
sẵn trong code. Đây là đánh đổi đã biết trước, chấp nhận tạm thời để có giao diện đẹp trước, nối backend sau như
một việc riêng.

`scripts/services/*.js` trong bản mới đã được viết theo đúng mẫu Service Layer (xem `BACKEND_INTEGRATION.md`)
— nghĩa là việc nối backend thật sau này chỉ cần sửa các file trong `scripts/services/`, không phải sửa UI.

## Hợp đồng API thật (đã có, đừng thiết kế lại — chỉ cần trỏ vào)

Team đã xây dựng và verify contract này với backend thật (`backend/src/services/trip_formatter.py`,
`backend/src/models/schemas.py`) trong bản React cũ, trước khi bị xóa ở đây. Chép lại nguyên văn để không mất
kiến thức khi cần nối lại:

Base URL: `(VITE_API_BASE || '') + '/api/v1'` — dev dùng Vite proxy tới `localhost:8000`, production nginx proxy
tới container `backend:8000`.

```
POST   /chat/session                         → { session_id, created_at }
POST   /planner_chat                         body: { session_id, message, language } → PlannerChatResponse
GET    /chat/:sessionId/plan                 → { trip_plan: TripPlan | null }  (throw trên 404)
DELETE /chat/:sessionId                      → null trên 204
```

Shape chính xác (TypeScript, từ `src/types.ts` bản cũ):

```ts
interface PlannerChatResponse {
  session_id: string
  reply: string
  suggestions: { label: string; value: string }[]
  stage: 'hotel_options' | 'error' | string | null
  hotel_options: HotelOption[]
  trip_plan: TripPlan | null
  intake?: IntakeStatus | null
}

interface HotelOption {
  index: number; id?: string; name: string; star_rating?: number; description?: string
  matched_rooms?: string[]; average_nightly_price?: number; total_stay_price?: number
  stay_night_count?: number; currency?: string
}

interface TripPlan {
  status: string  // free text, vd "Draft"
  destination: string | null; duration_days: number
  start_date: string | null; end_date: string | null; number_of_adults: number | null
  hotel: { id?: string; name: string; star_rating?: number; description?: string
           matched_rooms?: string[]; coordinates?: string | null } | null  // coordinates là WKT string, không phải {lat,lng}
  days: { day_number: number; theme: string
           items: { order_index: number; start_time: string|null; end_time: string|null
                     activity: string; kind?: string|null; reference_type?: string|null; reference_id?: string|null }[] }[]
  adjustments: string[]
}

interface IntakeStatus {
  destination: string | null; duration: string | null; start_date: string | null; end_date: string | null
  people: string | null              // chuỗi đã format sẵn, vd "2 người" — không phải số
  preferences: string[]; companions: string | null; pace: string | null; day_rhythm: string[]
  notes: string; available_destinations: string[]; budget_options: string[]; missing: string[]
}
```

Chọn khách sạn: gửi `String(hotelOption.index)` như một tin nhắn chat bình thường qua `/planner_chat` (đúng
contract `select_hotel` tool phía backend) — không phải endpoint riêng.

Bản React cũ (tag `pre-ui-swap-frontend-2026-08-05`) còn 1 file mock server tham khảo được — `mock/server.js`
— replay đúng 4 endpoint trên với kịch bản hội thoại 7 lượt tiếng Việt, hữu ích khi test lại UI mới mà chưa cần
backend thật chạy.

## Việc cần làm khi nối lại backend thật

1. Đọc `BACKEND_INTEGRATION.md` — từng service (`hotel`, `destination`, `itinerary`, `history`) đang trả mock,
   cần đổi sang gọi `window.VOTA.Api.http` (`scripts/api/http-client.js`) theo đúng endpoint/shape ở trên.
2. Chat thật sự khác nhiều so với luồng chat mô phỏng hiện tại của UI mới (client tự viết kịch bản hội thoại) —
   cần thiết kế lại phần gọi `/planner_chat` cho khớp luồng multi-turn thật + `stage`/`suggestions`/`intake` từ
   server, không chỉ đổi nguồn dữ liệu tĩnh.
3. `scripts/constants/env.js` — đổi `API_BASE_URL` sang backend thật (`http://localhost:8000/api/v1` khi dev).
4. Dockerfile/nginx.conf/CI cũ (đã xóa ở bước này, còn trong tag cũ) được viết cho build Vite — cần dựng lại
   pipeline build/deploy phù hợp cho app `.dc.html` tĩnh (hoặc tích hợp `.dc.html` vào một bước build thật nếu
   team muốn, tuỳ quyết định sau).
