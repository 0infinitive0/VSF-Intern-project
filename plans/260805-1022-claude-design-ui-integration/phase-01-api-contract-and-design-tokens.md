---
phase: 1
title: "API Contract & Design Tokens"
status: done
priority: P1
effort: "1-1.5 ngày"
dependencies: []
track: chung
---

# Phase 1: API Contract & Design Tokens

## Tổng quan

Dựng hai thứ mà cả hai track phụ thuộc vào, rồi rút lui: **contract payload đóng băng**
(tài liệu + TypeScript types + mock fixtures) và **lớp design token** (`styles.css`). Sau
phase này, backend và frontend không bao giờ chặn nhau nữa.

Đây là phase duy nhất cả hai dev cùng sửa file chung. Nên làm cùng nhau trong một buổi và
merge xong trước khi bất kỳ track nào bắt đầu.

## Yêu cầu

**Chức năng**
- `docs/chat_api_contract.md` mô tả mọi endpoint cũ và mới kèm payload chính xác
- `frontend/src/types.ts` mirror contract 1:1, sau đó coi như đóng băng
- `frontend/mock/server.js` phục vụ fixture cho **tất cả** endpoint — kể cả 3 endpoint mới —
  để track frontend hoàn toàn không bị chặn
- `frontend/src/styles.css` mang hệ token của design cho cả theme sáng và tối

**Phi chức năng**
- Fixture mock dùng nội dung tiếng Việt thực tế và toạ độ Đà Nẵng hợp lý
- Tên token giữ nguyên hệ ngữ nghĩa hiện có (`--color-primary`, `--color-surface-*`,
  `--color-on-surface*`) để mọi `className` cũ vẫn resolve — chỉ chỉnh **giá trị**, và
  **thêm** token glass bên cạnh
- Phase này không sửa file component nào

## Kiến trúc

### Quy tắc đóng băng contract

`types.ts` là dạng máy kiểm tra được của `chat_api_contract.md`. Sau phase này:

> Mọi thay đổi `types.ts` đều là thay đổi contract. Phải có sự đồng ý của cả hai dev và
> phải sửa kèm `chat_api_contract.md` + `mock/server.js` trong **một commit duy nhất**.

### Lớp token

Token gốc của design (`V-OTA Planner.dc.html:22-43`) tiện cho inline style nhưng không hợp
với Tailwind. Ánh xạ vào `@theme` mà vẫn giữ tên ngữ nghĩa cũ:

| Token design | Token dự án | Ghi chú |
|---|---|---|
| `--t1` `--t2` `--t3` `--t4` | `--color-on-surface`, `--color-on-surface-variant`, `--color-on-surface-muted`, `--color-on-surface-faint` | 4 cấp chữ thay cho 2 cấp hiện tại |
| `--acc` / `--acc-soft` | `--color-primary` / `--color-primary-soft` | `#3A73DE` sáng, `#6C9BF0` tối |
| `--ok` `--warn` `--err` | `--color-success` `--color-warning` `--color-error` | kèm biến thể `-soft` / `-ink` |
| `--g0`…`--g3` | `--color-glass-0`…`--color-glass-3` | thang translucency phân lớp — **mới** |
| `--edge` `--gloss` `--sheen` `--line` `--stroke` `--fill` `--fill2` | cùng tên dưới tiền tố `--color-` | viền/nền glass — **mới** |
| `--btn` / `--btn-fg` | `--color-button` / `--color-on-button` | nút pill gần đen |
| `--page` | `--gradient-page` | gradient nền 165° |
| `--sh` | `--shadow-rgb` | kênh màu shadow, khác nhau theo theme |

Dark mode điều khiển bằng `body[data-theme="dark"]` đúng như file export. Đăng ký custom
variant của Tailwind để component viết được utility `dark:`:

```css
@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));
```

Thang typography theo `Typography & Color System.md` — 5 cấp, mỗi cấp khác nhau về size,
weight, letter-spacing, line-height **và** opacity:

| Cấp | Dùng cho | Size / weight / tracking |
|---|---|---|
| 1 | Hero, tiêu đề trang | 30-34px / 590 / -0.9px |
| 2 | Tiêu đề section | 21-22px / 590 / -0.7px |
| 3 | Tiêu đề card | 14-15px / 590 / -0.2px |
| 4 | Nội dung | 12.5-14px / 400-450 / -0.08px |
| 5 | Caption, metadata, timestamp | 9.5-11px / 450-530 / +0.04…+0.1em, viết hoa ở những chỗ design dùng hoa |

Font: `-apple-system, "SF Pro Display", "SF Pro Text", BlinkMacSystemFont, "Be Vietnam Pro", "Segoe UI", sans-serif`.
Be Vietnam Pro là fallback cho dấu tiếng Việt, phải preload trong `frontend/index.html`
(file export preconnect tới Google Fonts chính vì lý do này).

### Công thức glass

File export lặp lại một công thức panel khoảng 20 lần. Tách ra một class CSS dùng chung
thay vì lặp `className` dài khắp nơi:

```css
@utility glass-panel {
  background: var(--color-glass-1);
  backdrop-filter: blur(30px) saturate(1.7);
  -webkit-backdrop-filter: blur(30px) saturate(1.7);
  border: 1px solid var(--color-edge);
  box-shadow: 0 24px 56px -28px rgb(var(--shadow-rgb) / 0.34),
              inset 0 1px 0 var(--color-gloss);
}
```

Kèm `glass-card` (nhẹ hơn, bo 22px) và `glass-chip` (pill). Về accessibility: bọc phần blur
trong `@media (prefers-reduced-transparency: no-preference)`, ngược lại dùng nền đục.

### Token motion

File export dùng nhất quán hai easing — copy đúng, đừng tự chế thêm:

- `--ease-glide: cubic-bezier(.22, 1, .36, 1)` — chuyển layout (0.42s-0.62s)
- `--ease-spring: cubic-bezier(.34, 1.3, .64, 1)` — phản hồi tương tác (0.2s-0.3s)

Keyframes cần port nguyên văn từ `V-OTA Planner.dc.html:52-70`: `vRise`, `vPop`, `vFade`,
`vIn`, `vDot`, `vShimmer`, `vSpin`, `vPinIn`, `vHero`, `vSheen`, `vDash`, `vFloat`.
Mọi motion phải bị vô hiệu dưới `@media (prefers-reduced-motion: reduce)`.

## File liên quan

- Tạo: `docs/chat_api_contract.md` — **kiểm tra trước**, file cùng tên đã tồn tại; hãy mở
  rộng chứ đừng ghi đè
- Sửa: `frontend/src/types.ts` — thêm interface mới + các field `coordinates` còn thiếu
- Sửa: `frontend/mock/server.js` — fixture cho 3 endpoint mới
- Sửa: `frontend/src/styles.css` — toàn bộ lớp token, cả hai theme, utility glass, keyframes
- Sửa: `frontend/index.html` — preconnect/preload Be Vietnam Pro
- Tham chiếu (chỉ đọc): `data/design/V-OTA Planner.dc.html:22-76` — nguồn chuẩn của token

## Các bước thực hiện

1. Đọc `docs/chat_api_contract.md` hiện có rồi mở rộng; giữ nguyên cấu trúc của nó.
   Ghi lại: 4 endpoint cũ không đổi, `hotel_options[]` đã mở rộng, và 4 endpoint mới
   (`GET /hotels/{id}`, `GET /attractions/{id}`, `GET /chat/sessions`,
   `GET /chat/{id}/restore`). Kèm hành vi `404` cho từng cái.
2. Mở rộng `types.ts`:
   - thêm `coordinates?: string | null` vào `DayItem` (**backend đã trả về từ trước** —
     đây là lỗ hổng type, không phải field mới) và vào `HotelOption`
   - thêm `RouteInfo { distance_km: number; duration_mins: number; polyline: string;
     profile: RouteProfile | null }` với
     `type RouteProfile = 'driving-traffic' | 'walking' | 'cycling' | 'driving'`, và gắn
     `route_to_next?: RouteInfo | null`, `route_from_hotel?: RouteInfo | null` vào `DayItem`.
     **Lưu ý định dạng thật của backend**: hai điểm trùng toạ độ cho ra `{0, 0, "", null}`
     chứ không phải `null` (`routing.py:84-89`) — kiểu phải cho phép cả hai và comment phải
     ghi rõ sự khác biệt. `profile` là **mã**, frontend dịch qua khoá `routeProfile.*`
   - **kiểm tra định dạng `coordinates`**: `parse_coordinates` (`routing.py:57-70`) chỉ chấp
     nhận `"lat,lng"` hoặc tuple. Comment hiện tại ở `types.ts:46-48` nói `hotel.coordinates`
     là chuỗi WKT — **hai điều này mâu thuẫn nhau**. Xác định cái nào đúng trên dữ liệu thật
     và sửa comment sai; Phase 9 và 10 đều phụ thuộc vào kết luận này
   - thêm vào `HotelOption`: `address`, `area_name`, `image_url`, `amenities`,
     `review_score`, `review_count`, `match_score`, `match_reasons`
   - thêm interface `MatchReason`, `HotelDetail`, `RoomDetail`, `RoomPrice`,
     `AttractionDetail`, `SessionSummary`, `SessionRestore`
   - **mọi field mới đều optional (`?`)** — frontend phải render đúng ngay cả khi backend
     chưa lên phase 2-4
3. Mở rộng `mock/server.js` với fixture cho các endpoint mới. Giữ nguyên kịch bản hội thoại
   7 lượt đang chạy; làm giàu fixture `hotel_options` ở lượt 3 với các field mới, và gán
   toạ độ Đà Nẵng thật cho các itinerary item để map có thể phát triển được.
   Fixture route phải phủ **cả năm** trạng thái để Dev F test được mọi nhánh:
   - route ô tô đầy đủ, `profile: "driving-traffic"`, `polyline` thật (lấy một chuỗi encoded
     thật từ Mapbox, đừng bịa ký tự)
   - route đi bộ, `profile: "walking"` — chặng ngắn, để test nhãn phương tiện thứ hai
   - `route_to_next: null` (routing lỗi) → frontend phải vẽ đường thẳng fallback
   - `{distance_km: 0, duration_mins: 0, polyline: "", profile: null}` (trùng toạ độ) →
     hiển thị khác `null`
   - `route_from_hotel: null` trên item đầu ngày → đây là trạng thái **thường gặp nhất** sau
     round-trip DB (mục 15 bảng "Phần chưa làm"), không phải ca hiếm
4. Viết lại khối `@theme` trong `styles.css` theo bảng ánh xạ. Giữ mọi tên token mà
   component đang tham chiếu; chỉnh giá trị; thêm token glass/motion.
5. Thêm custom variant `dark`, các utility glass, keyframes đã port, và cả hai guard
   reduced-motion + reduced-transparency.
6. Cập nhật `frontend/index.html` cho font stack.
7. Kiểm chứng: `npm run typecheck` pass, `npm run mock` phục vụ đủ mọi route đã ghi trong
   tài liệu, `npm run dev` render UI **hiện tại** không vỡ (màu sẽ đổi — điều đó đúng và
   mong đợi; layout thì không được vỡ).

## Tiêu chí hoàn thành

- [x] `docs/chat_api_contract.md` mô tả đủ 8 endpoint kèm shape request/response/error
- [x] `types.ts` compile được và mirror đúng contract; mọi field mới đều optional
- [x] `mock/server.js` phục vụ đủ 8 route; kịch bản 7 lượt vẫn chạy trọn
- [x] Fixture khách sạn mock có ảnh, tiện nghi, điểm đánh giá, toạ độ, match score
- [x] Itinerary item trong mock có toạ độ
- [x] Định nghĩa đủ hai theme; đặt `data-theme="dark"` trên `<body>` là đổi palette thấy rõ
- [x] Tôn trọng cả `prefers-reduced-motion` và `prefers-reduced-transparency`
- [x] `npm run typecheck` và `npm run lint` pass
- [ ] Cả hai dev đã review và chốt contract trước khi bất kỳ track nào bắt đầu
  (nhân bước này — cần review thủ công từ cả hai dev, không tự động hoá được)

Font stack thực tế dùng "Inter", "Be Vietnam Pro" — quyết định của người dùng, ghi đè
gợi ý SF Pro trong "Kiến trúc" ở trên. `--font-display` giữ nguyên Hanken Grotesk.

## Đánh giá rủi ro

**Contract sai giữa chừng.** Khả năng cao nhất là ở giá phòng — `room_prices` gắn theo
khoảng ngày và có thể không có dòng nào khớp kỳ nghỉ được hỏi. Giảm thiểu: quy định
`price` là nullable ngay từ đầu trong contract, và Dev B chạy nhanh một câu `SELECT` trên
bảng thật ngay trong phase này để xác nhận shape trước khi đóng băng.

**Đổi tên token làm vỡ component cũ.** Giảm thiểu bằng cách giữ nguyên mọi tên token ngữ
nghĩa và chỉ chỉnh giá trị. Kiểm chứng bằng cách chạy app hiện tại ngay sau bước 4 — trước
khi động vào bất kỳ component nào.

**`docs/chat_api_contract.md` đã tồn tại và có thể mâu thuẫn.** Đọc trước. Nếu nội dung
hiện tại trái với những gì quan sát được trong code thì **code thắng**; ghi lại phần hiệu
chỉnh vào tài liệu thay vì âm thầm viết đè.
