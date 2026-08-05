# Báo cáo Refactor — V-OTA Planner

Tài liệu này tổng kết toàn bộ quá trình refactor kiến trúc frontend, theo đúng
7 mục deliverables đã yêu cầu. Bối cảnh kỹ thuật đầy đủ (định dạng `.dc.html`,
ràng buộc `dc-import`, quy tắc đặt tên prop...) nằm ở `README.md` — tài liệu
này tập trung vào **kết quả** và **quyết định kiến trúc**.

---

## 1. Sơ đồ thư mục mới

```
V-OTA Planner.dc.html      # Root — layout khung, chuyển phase, state top-level
support.js                  # Runtime generated — không đụng vào
server.js, package.json     # Dev server tĩnh, zero-dependency
README.md, REFACTOR.md

*.dc.html (16 file, PHẲNG ở root — xem README mục "prop naming gotcha")
├── Sidebar.dc.html                  # brand, new-trip, history, lang/theme
├── HistoryRow.dc.html               # 1 dòng lịch sử hội thoại
├── ChatPanel.dc.html                # toàn bộ cột chat bên trái
│   ├── ChatMessage.dc.html          # 1 bong bóng chat
│   ├── PendingChangeCard.dc.html    # thẻ "yêu cầu đã thay đổi"
│   ├── DestinationPicker.dc.html    # chip chọn điểm đến
│   ├── PeoplePicker.dc.html         # segmented control số người
│   ├── DatePicker.dc.html           # lịch chọn ngày
│   ├── BudgetSlider.dc.html         # thanh trượt ngân sách 2 đầu
│   └── InterestPicker.dc.html       # chip chọn sở thích
├── HotelCard.dc.html                # 1 khách sạn trong danh sách
├── HotelDetail.dc.html              # panel chi tiết khách sạn (focus mode)
│   └── RoomCard.dc.html             # 1 phòng (nested dc-import)
├── PlaceDetail.dc.html              # panel chi tiết điểm tham quan (focus mode)
├── TimelineItem.dc.html             # 1 mốc trong timeline theo ngày
└── DayCard.dc.html                  # 1 dòng tóm tắt ngày (tab Tổng quan)

scripts/                    # JS thường (window.VOTA.*), nạp qua <script src>
├── constants/
│   ├── config.js            # màu theo ngày/leg, biên ngân sách
│   ├── i18n.js               # dict UI (vi/en), kịch bản hội thoại AI, map dịch nội dung mock
│   └── mock-data.js          # hotels, days, landmarks, convos, dests, interests...
├── services/
│   ├── chat.service.js       # detectLang/detectChange/affectedOf — "AI" giả lập
│   └── map.service.js        # khởi tạo Leaflet map dùng chung
├── store/
│   └── app-store.js          # persist theme + ngôn ngữ (localStorage)
└── utils/
    ├── formatters.js         # tiền tệ, ngày tháng, số
    └── geo.js                 # haversine, bezier curve, hash

styles/
├── variables.css   theme.css   global.css
├── typography.css  layout.css  animation.css
```

**So với đề xuất ban đầu:** không có thư mục `components/` (kỹ thuật của
runtime không cho phép — xem README), không có `store/` đầy đủ cho mọi
feature (chỉ 1 store nhỏ cho theme/lang, có lý do rõ ở mục 2).

---

## 2. Giải thích kiến trúc đã lựa chọn

Điểm khởi đầu quan trọng: đây **không phải** một ứng dụng HTML/JS thuần mà
build bằng bundler — nó chạy trên một runtime riêng (`support.js`) đọc file
`.dc.html` (template + 1 class logic), không hỗ trợ `import`/`export` ES
module, và có cơ chế tách component riêng (`dc-import`) với ràng buộc: **mọi
file bị import phải nằm phẳng ở thư mục gốc**, không nằm trong thư mục con
được (do `COMPONENT_DIR` viết cứng và tên bị `encodeURIComponent`).

Vì vậy kiến trúc cuối cùng là bản "dịch" của mô hình feature-based sang đúng
những gì runtime này hỗ trợ:

- **UI được tách theo `dc-import`** — cơ chế component hóa chính chủ của
  runtime — thay vì ES module `import`. Tên file mô tả rõ Feature
  (`HotelCard`, `ChatPanel`...) thay cho thư mục.
- **Dữ liệu/logic dùng chung tách thành `window.VOTA.*`** — namespace toàn
  cục qua `<script src>` thường, vì logic script của mỗi Design Component
  chạy qua `new Function(...)`, không hiểu `import`.
- **State vẫn tập trung ở Root** (không dựng Redux-style store cho mọi
  feature) — vì `dc-import` truyền dữ liệu 1 chiều qua props + callback,
  giống hệt mô hình props/children của React. Root vốn đã là "single source
  of truth" tự nhiên của framework này; components con nhận props, gọi
  callback lên cha. Chỉ tách riêng 1 store nhỏ (`app-store.js`) cho
  theme/ngôn ngữ vì đây là state thực sự được đọc/ghi **ngoài** cây UI
  (đọc trong constructor trước khi mount, ghi qua `document.body` side
  effect) — khác về bản chất với state chat/hotel/itinerary vốn đã chảy
  gọn gàng qua props.
- **CSS**: chỉ tách phần thực sự global (design token, animation, reset) ra
  `styles/*.css`; style riêng từng phần tử **giữ nguyên dạng inline
  `style="{{ ... }}"`** vì đó là cách runtime này bind style động theo
  state — viết lại thành className + CSS rule sẽ đổi cách render và có rủi
  ro lệch UI/animation (bị cấm theo yêu cầu ban đầu).

Kết quả: Root từ **2613 dòng** (bao gồm cả template lẫn 100% business logic)
còn **1633 dòng** — giảm ~38%, phần còn lại chủ yếu là khung layout, điều
hướng phase, và các method tính toán/orchestration (không thể tách tiếp mà
không phá vỡ mô hình state-ở-Root nói trên).

---

## 3. Danh sách các module đã được tách

| Module | Chứa gì |
|---|---|
| `scripts/constants/config.js` | Bảng màu theo ngày/leg, biên ngân sách (500k–50tr) |
| `scripts/constants/i18n.js` | Dict UI đầy đủ (vi/en), kịch bản hội thoại AI, bảng dịch nội dung mock (vi→en) |
| `scripts/constants/mock-data.js` | Toàn bộ mock data: hotels, landmarks, dayHooks, convos, convoChat, days/itinerary, dests, interests, genLabels |
| `scripts/services/chat.service.js` | `detectLang`, `detectChange`, `affectedOf` — logic "hiểu" tin nhắn tự do, giả lập AI |
| `scripts/services/map.service.js` | `createBaseMap()` — khởi tạo Leaflet dùng chung cho 2 map |
| `scripts/store/app-store.js` | Đọc/ghi `localStorage` cho theme + ngôn ngữ |
| `scripts/utils/formatters.js` | `vnd/mny/mnyShort/fmtDate/fmtNights/num1/dmy/iso/countNights` |
| `scripts/utils/geo.js` | `hash`, `kmFrom` (haversine), `curve` (bezier route) |

Root Logic giữ nguyên **tên và chữ ký** của mọi method cũ (`this.vnd()`,
`this.detectLang()`...) dưới dạng wrapper 1 dòng gọi vào module tương ứng —
nên toàn bộ phần còn lại của class (hàng chục điểm gọi trong `renderVals()`)
**không cần sửa gì**, giảm tối đa rủi ro thay đổi hành vi.

---

## 4. Danh sách các component mới

16 Design Component (`.dc.html`), xem sơ đồ mục 1. Mỗi component đều verbatim
lift từ template gốc (không viết lại markup/style), chỉ thay tên biến `c`/`h`/
`it`/... thành prop nhận từ ngoài. Ba component lớn nhất — `ChatPanel` (55
props), `HotelDetail` (~130 dòng), `PlaceDetail` (~115 dòng) — đã qua kiểm
thử tương tác đầy đủ (xem mục Kiểm thử trong README/lịch sử commit).

`RoomCard` là component **nested** — được `HotelDetail` gọi bằng chính cơ chế
`dc-import`, xác nhận runtime hỗ trợ lồng component ở bất kỳ độ sâu nào.

---

## 5. Danh sách những đoạn code đã được gom lại (loại bỏ trùng lặp)

- **Bảng màu ngày/leg** (`this.C`, `this.LEG`) — trước đây là literal lặp lại
  ý tưởng ở nhiều chỗ ngầm định; nay có 1 định nghĩa duy nhất trong
  `config.js`.
- **Biên ngân sách** — `500000`/`50000000` từng lặp lại **3 lần** với 2 công
  thức hơi khác nhau (`budgetDrag`'s `MIN/MAX/STEP` cục bộ, và `bPct()`'s số
  hardcode `500000`/`49500000`) — nay chỉ 1 nguồn trong `config.js`.
- **Dead code thật sự**: class gốc có **2 method cùng tên `nights`**
  (`nights(a,b)` và `nights()` không tham số) — JS chỉ giữ định nghĩa sau
  cùng, nên bản 2-tham số (với công thức đếm đêm khác, thiếu `+1`) không
  bao giờ chạy được. Đã xoá bản chết, giữ lại bản đang thực sự dùng.
- **Bootstrap Leaflet** — đoạn `L.map(...).setView(...)` + tile layer + zoom
  control bị lặp y hệt giữa `ensureHotelMap()` và `ensureMap()` — nay dùng
  chung `map.service.js#createBaseMap()`.
- **localStorage cho theme/lang** — từng có 3 chỗ tự viết `try{...}catch{}`
  giống hệt nhau (constructor, `applyTheme`, `setLang`) — nay gọi chung
  `app-store.js`.

---

## 6. Những phần có thể tiếp tục mở rộng trong tương lai

- **Map**: hiện chỉ dùng chung phần khởi tạo map; phần vẽ marker/route/label
  và đồng bộ hover vẫn lặp lại giữa 2 màn hình. Đây là phần code trùng lặp
  lớn nhất còn sót — xem mục 7 để biết vì sao chưa gộp tiếp trong lần này.
- **Shared primitives** (Button/Card/Badge/Modal...) chưa tách thành thư
  viện dùng chung — xem mục 7.
- **`getDays()`, `hotelDetailData()`, `roomsOf()`, `detailData()`** trong
  Root vẫn là các "view-model builder" lớn, trộn dữ liệu mock + dịch i18n +
  closure callback. Khi tách tiếp `TripMap`/gộp thêm logic hotel, đây là nơi
  tự nhiên để chuyển logic tính toán thuần (không đụng closure) vào
  `services/hotel.service.js` / `services/itinerary.service.js`.
- **`trUnits`/`trKind`/`trView`/`tx`/`trMsg`** (dịch nội dung theo câu) vẫn
  là method của Root — có thể tách sang `scripts/utils/i18n-format.js` theo
  đúng pattern đã dùng cho `formatters.js`, nhưng bị hoãn vì độ ưu tiên thấp
  hơn so với việc tách component trong lần refactor này.
- **`quickActions`** (3 nút gợi ý nhanh cuối chat) vẫn nằm trong `ChatPanel`
  — quá nhỏ để tách riêng ở thời điểm này, nhưng nếu số lượng biến thể tăng
  lên thì đáng tách thành `QuickActionChip.dc.html`.

---

## 7. Đề xuất cải thiện kiến trúc nếu project tiếp tục phát triển

1. **Gộp Map triệt để hơn** — nếu muốn làm tiếp: tạo `TripMap.dc.html` nhận
   `mode="hotels"|"itinerary"` + dữ liệu điểm (hotels hoặc day items) qua
   props, và **2 callback** duy nhất lên Root: `onHover(id)`/`onPick(id)`.
   Root vẫn giữ `hoverHotel`/`hovered`/`selected` trong state của mình (để
   List/Timeline đọc), chỉ truyền xuống map để tô marker — tránh phải đảo
   ngược luồng dữ liệu. Rủi ro chính là 2 map hiện dùng thuật toán vẽ route
   khác nhau (OSRM + fallback bezier cho itinerary; đường thẳng nét đứt cho
   hotel-tới-landmark) — cần giữ đúng 2 nhánh vẽ, không ép về 1 khuôn.
2. **Button/Chip dùng chung** — điểm khởi động an toàn nhất là 4 nút điều
   hướng lịch (`«`/`‹`/`›`/`»`) trong `DatePicker.dc.html`, đang **giống hệt
   nhau 100%** ngoại trừ `onClick`/`title`/label — tách thành
   `CalendarNavButton.dc.html` trước, rồi mở rộng dần sang các nhóm nút khác
   khi thấy đúng là trùng lặp thật (không phải chỉ "trông giống nhau").
3. **Nếu project đủ lớn để cần TypeScript/bundler thật sự** (không chỉ dừng
   ở runtime `.dc.html` này), đó là lúc đáng cân nhắc chuyển hẳn sang
   Vite + React với ES module thật — lúc đó toàn bộ `scripts/constants` và
   `scripts/services` gần như copy-paste thẳng sang (đã là các module thuần
   theo domain), chỉ cần đổi `window.VOTA.X` thành `export`.
4. **Test tự động**: hiện việc kiểm thử refactor này dựa vào Playwright chạy
   thủ công qua từng luồng. Nếu tiếp tục phát triển, đáng đầu tư một bộ
   smoke-test cố định (Playwright hoặc tương đương) chạy lại đúng luồng
   "intake → hotels → workspace" sau mỗi thay đổi, thay vì viết lại kịch bản
   kiểm thử mỗi lần.
5. **`hotelDetailData()`/`getDays()` cache**: 2 hàm này có cơ chế memo hoá
   thủ công (`this._dk`/`this._dv`) khá tinh vi (phụ thuộc hotel id + ngôn
   ngữ). Nếu tách thành service thuần, nên cân nhắc dùng lại đúng key cache
   đó thay vì tính lại mỗi lần — tránh hồi quy hiệu năng.

---

## Xác nhận cuối cùng

- Toàn bộ mock data, animation, user flow **giữ nguyên 100%** — không sửa
  hành vi, không sửa UI (đúng ràng buộc "Current Project Status").
- Mỗi Phase đều được: verify qua dev server thật (Playwright) hoặc harness
  Node cô lập chạy trực tiếp class Logic, rồi mới `git commit` — lịch sử
  commit (`git log`) chính là nhật ký chi tiết cho từng quyết định.
- Phát hiện và sửa 1 lỗi thật trong lúc refactor (prop tên `L` bị trình
  duyệt hạ chữ thường, phá vỡ 3 component) — xem README + commit
  `4264c97` để biết chi tiết.
