# Backend API Integration — Báo cáo

Tài liệu này tổng kết việc đưa toàn bộ truy cập dữ liệu qua Service Layer,
theo đúng 5 mục deliverables yêu cầu trong `Backend API Integration.md`. Bối
cảnh kiến trúc frontend tổng thể (feature-based, `dc-import`, quy tắc đặt tên
prop...) nằm ở `README.md` và `REFACTOR.md` — tài liệu này chỉ tập trung vào
tầng dữ liệu.

---

## 1. Sơ đồ luồng dữ liệu mới

```
Root Logic (UI)
     │  window.VOTA.Services.hotel.getHotels() v.v. — gọi hàm thường
     │  (không fetch(), không đụng MockData trực tiếp)
     ▼
scripts/services/*.js
     │  hiện đọc window.VOTA.MockData (đồng bộ — xem mục "Quyết định" bên dưới)
     │  → sau này: await window.VOTA.Api.http.get/post(...)
     ▼
scripts/api/http-client.js
     │  fetch() + base URL (scripts/constants/env.js) + headers + timeout +
     │  chuẩn hóa lỗi + hook Authorization token
     ▼
Backend REST API (.NET) — tương lai
     ▼
Database — tương lai
```

State của Root Logic (`this.state`, `this.hotels`, `this.days`, ...) tiếp tục
đóng vai trò "Store" trên thực tế — không có `hotel.store.js`/`itinerary.store.js`
riêng, đúng theo quyết định đã ghi trong comment của `app-store.js` (một
Redux-style store chung đã từng bị đánh giá là over-engineering cho app này).

**Quyết định quan trọng:** Service Layer đọc mock data **đồng bộ** trong đợt
này, không phải `async`/`Promise`. Root Logic dựng UI ngay trong constructor,
đồng bộ, không qua bước loading nào — đây là ràng buộc của chính dc-runtime,
không phải lựa chọn tùy ý. Khi backend thật xuất hiện, phần **duy nhất** cần
sửa ngoài Service Layer là constructor của Root Logic (chuyển sang load bất
đồng bộ + thêm loading state) — xem chi tiết ở mục 5.

---

## 2. Danh sách Service đã tạo / mở rộng

| File | Hàm export | Trạng thái |
|---|---|---|
| `scripts/services/hotel.service.js` | `getHotels()`, `getSearchLabels()` | **Mới** |
| `scripts/services/destination.service.js` | `getDestinationOptions()`, `getInterestOptions()`, `getLandmarks()` | **Mới** |
| `scripts/services/itinerary.service.js` | `getDays()`, `getDayHooks()`, `getOptimizationLabels()`, `getGenLabels()` | **Mới** |
| `scripts/services/history.service.js` | `getConversations()`, `getConversationMessages()` | **Mới** |
| `scripts/services/map.service.js` | `createBaseMap()` (đã có) + `fetchRouteGeometry(a, b, mode)` **mới** | Mở rộng |
| `scripts/services/chat.service.js` | `detectLang()`, `detectChange()`, `affectedOf()` | Không đổi — đã là điểm swap cho NLP/LLM thật từ trước |
| `scripts/api/http-client.js` | `get/post/put/del`, `setAuthToken()` | **Mới** — chưa nơi nào gọi tới |
| `scripts/constants/env.js` | `window.VOTA.Env.API_BASE_URL` | **Mới** |

`auth.service.js` / `user.service.js` **chưa tạo** — app hiện không có màn
hình đăng nhập/hồ sơ nào để hai service này phục vụ; tạo thêm bây giờ sẽ là
scaffolding chưa dùng tới (đi ngược nguyên tắc "chưa cần tối ưu Production"
của `Current Project Status.md`). Điểm gắn Authorization header
(`setAuthToken()`) đã có sẵn trong `http-client.js`, chỉ cần 2 file service
nhỏ khi có luồng đăng nhập thật.

---

## 3. API REST dự kiến cho từng Feature

```
Hotel
  GET   /api/hotels                  ~ hotel.service.getHotels()
  GET   /api/hotels/{id}
  POST  /api/hotels/search           filters (ngân sách, ngày, số người...)

Destination
  GET   /api/destinations            ~ destination.service.getDestinationOptions()
  GET   /api/destinations/{id}
  GET   /api/destinations/{id}/landmarks   ~ destination.service.getLandmarks()
  GET   /api/interests               ~ destination.service.getInterestOptions()

Itinerary
  GET   /api/itinerary               ~ itinerary.service.getDays()
  POST  /api/itinerary/generate
  PUT   /api/itinerary                (chỉnh sửa lịch trình)

History / Conversations
  GET   /api/conversations           ~ history.service.getConversations()
  GET   /api/conversations/{id}/messages   ~ history.service.getConversationMessages()
  POST  /api/conversations           (tạo chuyến đi mới)
  DELETE /api/conversations/{id}

Chat
  POST  /api/chat                    (gửi tin nhắn tới AI thật)
  GET   /api/chat/{conversationId}

Map
  (giữ nguyên OSRM public API cho route geometry — không phải backend của
  mình, xem mục 4)

Auth (chưa triển khai — chỉ có hook sẵn trong http-client.js)
  POST  /api/auth/login
  POST  /api/auth/refresh
  GET   /api/users/me
```

---

## 4. Mock Data đã chuyển sang Service Layer

| `window.VOTA.MockData.X` (đọc trực tiếp — trước) | Service function (sau) |
|---|---|
| `hotels` | `hotel.service.getHotels()` |
| `searchLabels` | `hotel.service.getSearchLabels()` |
| `dests` | `destination.service.getDestinationOptions()` |
| `interests` | `destination.service.getInterestOptions()` |
| `landmarks` | `destination.service.getLandmarks()` |
| `days` | `itinerary.service.getDays()` |
| `dayHooks` | `itinerary.service.getDayHooks()` |
| `optLabels` | `itinerary.service.getOptimizationLabels()` |
| `genLabels` | `itinerary.service.getGenLabels()` |
| `convos` | `history.service.getConversations()` |
| `convoChat` | `history.service.getConversationMessages()` |

Ngoài ra, lệnh gọi `fetch()` trực tiếp duy nhất trong toàn app — lấy geometry
đường đi thật từ OSRM trong `routeLeg()` — đã chuyển vào
`map.service.fetchRouteGeometry()`. Đây không phải backend của mình (là API
routing công khai của bên thứ ba) nên không đi qua `http-client.js`, nhưng
vẫn tuân thủ đúng quy tắc "không `fetch()` trực tiếp trong component".

`scripts/constants/mock-data.js` giữ nguyên là nguồn mock duy nhất (không
tách thành `mock/*.mock.js` theo từng feature như ví dụ trong doc) — các
service import thẳng từ đây. Việc tách file sau này, nếu muốn, chỉ là thao
tác cơ học, không ảnh hưởng UI hay service.

---

## 5. Vị trí cần sửa khi Backend (.NET) sẵn sàng

Từng service — chỉ sửa **phần thân hàm**, giữ nguyên chữ ký:

```javascript
// scripts/services/hotel.service.js — trước
getHotels() {
  return window.VOTA.MockData.hotels;
}

// sau
async getHotels() {
  return await window.VOTA.Api.http.get('/hotels');
}
```

Áp dụng tương tự cho `destination.service.js`, `itinerary.service.js`,
`history.service.js`, và `map.service.js` (phần OSRM đã sẵn `async`, không
cần sửa gì thêm).

`scripts/constants/env.js` — đổi `API_BASE_URL` sang domain backend thật.

**Ngoại lệ duy nhất — Root Logic constructor (`V-OTA Planner.dc.html:372-383`
hiện tại):** một khi các hàm service ở trên trở thành `async`, việc gọi chúng
trong constructor (vốn đồng bộ) sẽ không còn nhận trực tiếp mảng dữ liệu mà
nhận về `Promise`. Đây là giới hạn của chính dc-runtime (render đồng bộ ngay
sau constructor, không có cơ chế loading/suspense), không phải điều Service
Layer có thể che giấu hết được. Việc cần làm khi đó:

1. Giữ giá trị khởi tạo mặc định (mảng rỗng / object rỗng) cho `this.hotels`,
   `this.days`, `this.convos`, ... trong constructor, để lần render đầu tiên
   không crash.
2. Chuyển việc gọi các hàm `getX()` (giờ là `async`) sang `componentDidMount()`,
   dùng `Promise.all(...)` rồi `setState`/gán lại các property tương ứng khi
   dữ liệu về, kèm loading state phù hợp cho tab/panel liên quan.
3. Không cần sửa bất kỳ nơi nào khác trong file — mọi chỗ dùng `this.hotels`,
   `this.days`... ở phần render vẫn giữ nguyên tên và cấu trúc.

Đây là điểm sửa duy nhất ngoài tầng Service — được nêu rõ ở đây thay vì hứa
suông "UI không bao giờ phải sửa", đúng tinh thần trung thực về đánh đổi kỹ
thuật.
