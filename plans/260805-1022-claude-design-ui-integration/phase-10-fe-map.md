---
phase: 10
title: "[FE] Mapbox GL JS Map & Route"
status: done
priority: P2
effort: "2-2.5 ngày"
dependencies: [9]
track: frontend
---

# Phase 10: [FE] Mapbox GL JS Map & Route

> **10/08/2026 — thư viện đổi từ Leaflet sang Mapbox GL JS.** Bản đầu của phase này chỉ định
> Leaflet + Mapbox raster tiles, và ghi rõ "không chuyển sang Mapbox GL JS". Nhóm đã đảo
> quyết định đó (xem `plan.md` §Các quyết định đã chốt, mục 5, bản sửa 10/08/2026): dùng
> thẳng Mapbox GL JS (`mapbox-gl`, thuần, điều khiển qua ref), không dùng `react-map-gl`.
> Mọi phần **không phụ thuộc thư viện** dưới đây (toạ độ, fallback, legend, `curve()`) giữ
> nguyên từ bản Leaflet; mọi phần **đặc thù Leaflet** đã được viết lại cho GL JS.

## Tổng quan

Thay `MapPanel` placeholder bằng bản đồ Mapbox GL JS thật: marker, **route bám đường thật từ
Mapbox**, đồng bộ hover hai chiều với timeline và danh sách khách sạn.

**Đã có sẵn một bản chạy được để port thuật toán (không phải cách vẽ)**:
`backend/src/airflow/dashboard/templates/index.html` là dashboard Airflow đang hoạt động
(Leaflet), đã giải mã polyline và vẽ route nhiều màu theo ngày, kèm fallback đường thẳng.
Phase này port **thuật toán dựng segment và giải mã polyline** đó sang GL JS (`lib/polyline.ts`,
`lib/route-segments.ts`), không phải phát minh lại — nhưng cách vẽ (marker, layer, hover)
là thiết kế mới cho GL JS, khác hẳn `L.polyline`/`L.marker`/`L.divIcon`. Đọc
`index.html:769-1000` để hiểu thuật toán trước khi đọc phần Kiến trúc bên dưới.

## Yêu cầu

**Chức năng**
- Bản đồ Mapbox GL JS với style chính thức (`streets-v12`/`dark-v11`), chrome dạng glass theo design
- Stage `hotels`: marker cho từng khách sạn; hover card ↔ hover marker; click marker → mở
  Hotel Detail Focus Mode
- Stage `workspace` tab Tổng quan: route toàn chuyến, mỗi ngày một màu, có legend
- Stage `workspace` tab ngày: chỉ route của ngày đang chọn
- Hover item timeline → highlight marker + đoạn route liên quan, giảm opacity các đoạn khác
- Click marker → cuộn tới card/item tương ứng
- Marker khách sạn phân biệt rõ với marker số thứ tự điểm tham quan
- Animation khi route xuất hiện
- Chrome bản đồ (legend, nhãn, controls) được dịch

**Phi chức năng**
- Bản đồ thu gọn mượt khi vào focus mode, không remount
- Attribution Mapbox hiển thị đầy đủ theo điều khoản sử dụng (GL JS tự render qua
  `AttributionControl` mặc định — không cần markup tay như bản Leaflet)
- Đổi style bản đồ theo theme bằng style URL thật (`streets-v12`/`dark-v11`), không dùng bộ lọc
  CSS giả dark mode — với GL JS điều này **tự động đúng**, không phải việc phải làm thêm

## Kiến trúc

### Dependency

Thêm `mapbox-gl` (không thêm `@types/mapbox-gl` — từ v2 nó tự mang type định nghĩa; kiểm tra
field `"types"` trong `node_modules/mapbox-gl/package.json` trước khi cân nhắc thêm).

**Không** dùng `react-map-gl` — điều khiển Mapbox GL JS trực tiếp qua ref
(`hooks/use-mapbox-map.ts`), khớp quy ước hook hiện có của dự án và giữ đồng bộ hover đơn
giản, đúng tinh thần quyết định gốc (tránh thêm một lớp wrapper React không cần thiết).

### Toạ độ

`lib/geo.ts` là nơi duy nhất parse toạ độ (`parseCoordinates`, đã xác nhận `"lat,lng"` là
định dạng thật). Phase này bổ sung `toLngLat()` (chuyển `{lat,lng}` sang `[lng,lat]` —
**ngược thứ tự** với quy ước của chính file này và với Leaflet — bẫy kinh điển gây marker lệch
bán cầu) và `boundsOf()` (camera fitting).

Toạ độ không parse được → **bỏ điểm đó khỏi map**, không đặt marker ở `(0,0)`. Một marker
giữa Đại Tây Dương tệ hơn là không có marker.

Nếu một ngày có ít hơn 2 điểm parse được thì không vẽ route cho ngày đó — tự nhiên đúng vì
mỗi segment đều cần 2 điểm hợp lệ, không cần gate riêng.

### Route — polyline thật, fallback đường thẳng

Mỗi chặng vẽ theo đúng thứ tự ưu tiên mà dashboard Airflow đã dùng
(`index.html:871-876, 896-919`), port vào `lib/route-segments.ts`:

```
1. có route_to_next.polyline  → decodePolyline() → đường bám thật
2. không có / giải mã ra < 2 điểm → đường thẳng [điểm A, điểm B]
```

Bước 2 **bắt buộc**, không phải tuỳ chọn: routing API có thể lỗi, hết quota, hoặc backend
chưa cấu hình token — khi đó `route_to_next` là `null` và map vẫn phải vẽ được cái gì đó.

Một item thiếu toạ độ tạo ra khoảng trống thật ở cả hai phía — **không** nối tắt sang điểm
hợp lệ gần nhất.

**`route_from_hotel` gần như luôn `null`** sau round-trip DB (mục 15 bảng "Phần chưa làm" —
`ITEM_RPC_FIELDS` lọc nó ra trước khi persist). Chặng đầu mỗi ngày vì vậy thường là đường
thẳng. Đây là hành vi bình thường, không phải bug — đừng đi "sửa" nó ở frontend.

### Giải mã polyline

`polyline` là Google Encoded Polyline precision 1e5. **Port hàm `decodePolyline` từ
`index.html:769-795`** vào `lib/polyline.ts` — nó ngắn (~25 dòng), đã chạy đúng trong
production, và tránh được việc thêm dependency chỉ để làm một việc.

Không cài `@mapbox/polyline` — YAGNI, và bản port đã có sẵn.

Animation xuất hiện dùng `line-opacity-transition` có sẵn của GL JS (paint-property
transition), không phải keyframe CSS `stroke-dashoffset` — xem §Animation bên dưới.

Bảng màu theo ngày: `lib/map-colors.ts` (`DAY_COLORS`, đã có sẵn, dùng chung với
`timeline-item.tsx`/`DayCard`). Route dùng `dayColor(dayNumber)`, **không** dùng `LEG_COLORS`
(đó là màu pill từng chặng của timeline, cách dùng khác của cùng file).

### Legend — nói đúng sự thật

Legend liệt kê **màu theo ngày**, cộng phần chú giải phương tiện dựng từ các `profile`
**thực sự xuất hiện** trong lịch trình đang xem:

- `driving-traffic` → "ô tô" (nét liền)
- `walking` → "đi bộ" (nét đứt dày)
- chặng fallback (`null`) → "ước lượng" (nét đứt thưa, màu nhạt)

Chỉ render mục nào thật sự có trong dữ liệu — lịch trình toàn ô tô thì không hiện mục "đi bộ".

Design có **ba** mức: ô tô / đi bộ / **cáp treo**. Hai mức đầu là thật (Phase 12 gọi đúng
profile). **Cáp treo không ship** — Mapbox không có profile đó và DB không có dữ liệu nào
cho biết chặng nào đi cáp. Mục 1 bảng "Phần chưa làm".

Chặng fallback vẽ khác chặng thật (nét đứt thưa hơn + opacity thấp hơn + mảnh hơn), **cùng
màu ngày** — phân biệt bằng nét chứ không phải màu thứ hai.

### Ba layer thay vì một — vì sao

`line-dasharray` trong GL style spec **không hỗ trợ data-driven expression** (chỉ hỗ trợ
expression theo zoom), nên không thể dùng một layer với dasharray thay đổi theo từng feature.
Giải pháp: một GeoJSON source dùng chung, **ba `line-layer` có `filter` riêng** (filter thì
hỗ trợ data expression đầy đủ — khác cơ chế với paint property):

- `route-line-driving`: `isFallback=false && profile != 'walking'` → dasharray đặc (nét liền)
- `route-line-walking`: `isFallback=false && profile == 'walking'` → dasharray vừa
- `route-line-fallback`: `isFallback=true` → dasharray thưa + opacity/width thấp hơn

### Đồng bộ hover — `setFeatureState`, không cần `setPaintProperty` mỗi lần hover

Paint expression khai báo **một lần duy nhất** lúc tạo layer, dạng
`['case', ['boolean', ['feature-state','hovered'], false], <giá trị hover>, <giá trị mặc định>]`.
Sau đó **chỉ cần gọi `map.setFeatureState()`** mỗi lần hover đổi — GL JS tự re-evaluate paint
theo feature-state, đúng pattern "Create a hover effect" chính thức của Mapbox. Đơn giản hơn
(và tương đương hiệu năng) so với việc gọi `setPaintProperty` mỗi lần hover.

Một dòng timeline có **hai cạnh** (chặng đến + chặng đi) — hover một item highlight cả hai
segment liền kề, làm mờ phần còn lại xuống opacity 0.15 (khớp giá trị dimmed của dashboard
tham chiếu).

Click marker → `focusOn(id)` cuộn phần tử `[data-card="{id}"]` vào tầm nhìn
(`hooks/use-map-sync.ts`).

### Animation

Dùng `line-opacity-transition`/`line-width-transition` (paint-property transition có sẵn của
GL JS) cho hiệu ứng route mờ dần hiện ra khi layer được tạo (lần đầu, hoặc sau khi
`setStyle()` xoá và tạo lại layer do đổi theme) — không dùng `requestAnimationFrame` thủ công.

**Không port được** animation nét chạy (`vDash`/`v-flow` CSS cũ) — đó là keyframe trên
`stroke-dashoffset` của SVG DOM, vô nghĩa với route vẽ trên canvas WebGL của GL JS. Route
tĩnh (dasharray cố định) + fade-in opacity là đủ để thoả yêu cầu "chặng fallback nhìn khác
chặng thật" và "route có animation xuất hiện". Animation nét chạy thật là việc tiếp theo, ghi
rõ ở đây chứ không phải thiếu sót âm thầm. Tương tự, hiệu ứng shadow-line kép + mũi tên chỉ
hướng của dashboard tham chiếu (`index.html:976-1004`) không port ở v1 — GL JS đã anti-alias
sạch, không cần kỹ xảo halo của raster tile; ghi là việc tiếp theo.

### Thẻ chú thích trên map ở stage khách sạn

Design đặt một card glass ở góc trên trái map trong stage khách sạn: nhãn uppercase số khách
sạn + một dòng gợi ý đổi theo trạng thái chọn. Nội dung thật của dòng đó là
"Chọn một khách sạn để xem khoảng cách tới các điểm nổi bật" khi chưa chọn, và
"*Tên khách sạn* — điểm xuất phát & kết thúc mỗi ngày" khi đã chọn — cả hai đều là câu mô tả
trạng thái thật, không phải dữ liệu bịa, nên ship được. Nối vào cùng state chọn khách sạn của
Phase 8.

### Thu gọn khi focus — `ResizeObserver`, không phải `transitionend`

Map không unmount khi vào focus mode; nó bị thu về bề rộng 0 bằng transition flex. **Phải gọi
`map.resize()`** (tương đương `invalidateSize()` của Leaflet) sau khi kích thước thật sự đổi,
nếu không GL JS sẽ render sai kích thước khi mở lại.

Dùng **`ResizeObserver`** gắn trên chính div chứa map, **không** dùng `transitionend` trên
wrapper cha. Cả `stage-hotels.tsx` và `stage-workspace.tsx` animate nhiều thuộc tính CSS với
thời lượng khác nhau trên wrapper đó (`flex .62s`, `opacity .36-.38s`, cộng `transform`/`filter`
ở workspace) — nghe một `transitionend` dễ bắt nhầm thuộc tính, hoặc vỡ âm thầm nếu chuỗi
transition inline bị sửa sau này. `ResizeObserver` phản ứng theo kích thước box thật, bất kể
nguyên nhân. Gom qua `requestAnimationFrame` trước khi gọi `resize()` để một transition ~600ms
không gọi `resize()` hàng chục lần.

### Style — Mapbox GL JS style thật, không phải raster + hack CSS

Dùng **style URL chính thức** của Mapbox:

```
light: mapbox://styles/mapbox/streets-v12
dark:  mapbox://styles/mapbox/dark-v11
```

Đổi style theo `theme` (đọc qua prop truyền từ `use-theme.ts`, không phải `MutationObserver`
— chỉ 2 bước truyền prop ngắn qua `stage-router.tsx`) bằng `map.setStyle()`. Vì đây là vector
style thật, **không cần** hack CSS `invert(.92) hue-rotate(180deg)` mà bản Leaflet+raster
từng cần — dark mode là style thật, không phải filter giả.

**Bẫy**: `map.setStyle()` xoá sạch mọi GeoJSON source/layer tự thêm (nhưng không xoá
`mapboxgl.Marker` — đó là DOM thuần, không phải GL layer). `use-mapbox-map.ts` expose
`styleVersion` (tăng mỗi lần `load`/`style.load`) để effect dựng route biết re-add
source/layer sau mỗi lần đổi theme.

**Token tile là token THỨ HAI**, khác token server của Phase 12:

| | Phase 12 (Directions) | Phase 10 (GL JS) |
|---|---|---|
| Loại | secret (`sk.`) | public (`pk.`) |
| Nơi dùng | backend | trình duyệt |
| Restriction | không | **bắt buộc có URL restriction** |
| Scope | directions | chỉ `styles:tiles`, `styles:read` |

Token GL JS **lộ ra trong bundle trình duyệt** — đó là bình thường và không tránh được, nên
URL restriction là biện pháp bảo vệ duy nhất. Đặt qua `VITE_MAPBOX_TOKEN` (tiền tố `VITE_`
nên nó cố ý đi vào bundle). **Tuyệt đối không** dùng token server ở đây.

**Thiếu `VITE_MAPBOX_TOKEN` — quyết định phạm vi có chủ đích, không phải thiếu sót.** Không
giống Leaflet+OSM (có tile miễn phí không cần token làm fallback trơn tru), Mapbox GL JS
**bắt buộc** cần token để load bất kỳ style chính thức nào — không có fallback tile miễn phí
tương đương mà không kéo thêm một engine thứ hai (vd MapLibre GL + style demo miễn phí), việc
đó là mở rộng phạm vi ngoài ý định phase này. Khi thiếu token: `MapView` hiện trạng thái trung
thực "map chưa cấu hình" (giữ tinh thần minh bạch của placeholder cũ), **không** cố fallback
sang provider khác.

## File liên quan

- Tạo: `frontend/src/components/map-view.tsx` — component map thật
- Tạo: `frontend/src/components/map-legend.tsx` — legend dạng glass
- Tạo: `frontend/src/hooks/use-mapbox-map.ts` — vòng đời map, style theo theme, `resize()`
- Tạo: `frontend/src/hooks/use-map-sync.ts` — trạng thái hover/focus dùng chung
- Tạo: `frontend/src/lib/polyline.ts` — `decodePolyline`, port từ dashboard Airflow
- Tạo: `frontend/src/lib/route-segments.ts` — dựng segment theo ngày, fallback, `classifyRoute`
- Tạo: `frontend/src/lib/map-sync-id.ts` — id dùng chung giữa map/timeline/hotel card
- Sửa: `frontend/src/lib/geo.ts` — thêm `toLngLat()`, `boundsOf()`
- Sửa: `frontend/src/lib/leg.ts` — tách `classifyRoute()` để route-segments.ts dùng chung
- Sửa: `frontend/src/components/stage-hotels.tsx` — nối map + hover khách sạn + thẻ trạng thái
- Sửa: `frontend/src/components/stage-workspace.tsx` — nối map + hover timeline + segment theo tab
- Sửa: `frontend/src/components/stage-router.tsx`, `app-shell.tsx` — truyền `theme` xuống
- Sửa: `frontend/src/components/timeline-item.tsx` — phát sự kiện hover, `data-card`
- Sửa: `frontend/src/components/hotel-option-card.tsx` — phát sự kiện hover, `data-card`
- Sửa: `frontend/src/components/day-timeline.tsx` — chuyển tiếp prop hover
- Sửa: `frontend/src/styles.css` — `[data-hovered='true']` cho `.hotel-card`/`.timeline-item`
- Sửa: `frontend/package.json` — thêm `mapbox-gl`
- Sửa: `frontend/.env.example` — thêm `VITE_MAPBOX_TOKEN`
- Sửa: `frontend/src/i18n/locales/{en,vi}.json` — chuỗi map mới, xoá chuỗi placeholder cũ
- Xoá: `frontend/src/components/map-panel.tsx` — thay bằng `map-view.tsx`

## Các bước thực hiện

0. **Đọc `backend/src/airflow/dashboard/templates/index.html:769-1000` trước.** Port thuật
   toán (`decodePolyline`, thứ tự dựng segment, fallback), không port cách vẽ Leaflet.
1. Cài `mapbox-gl`. Import CSS `mapbox-gl/dist/mapbox-gl.css` ngay trong
   `use-mapbox-map.ts` (theo tiền lệ `intake-date-range.tsx` import CSS thư viện tại chỗ dùng,
   không phải trong `styles.css` — file đó dành riêng cho 3 file token chép nguyên văn).
   **Không** cài thư viện giải mã polyline.
2. `lib/geo.ts`: thêm `toLngLat()`, `boundsOf()` + test.
2b. `lib/polyline.ts`: port `decodePolyline` + test (chuỗi rỗng, chuỗi rác, chuỗi hợp lệ đã
   biết kết quả — dùng ví dụ mẫu của Google cộng một polyline thật từ `mock/server.js`).
3. `lib/leg.ts`: tách `classifyRoute()` từ logic same-place có sẵn trong `legBetween()`.
4. `lib/route-segments.ts`: `buildDaySegments`/`buildTripSegments` + test bằng fixture Đà Nẵng
   thật từ `mock/server.js` (bao phủ: same-place bị bỏ, route thật ô tô/đi bộ, `null` fallback,
   chặng cuối về khách sạn, khoảng trống không bị nối tắt, ngày <2 điểm không có route).
5. `lib/map-sync-id.ts`: `itemSyncId`, `hotelOptionSyncId`, `TRIP_HOTEL_SYNC_KEY`.
6. `use-mapbox-map.ts` — khởi tạo, style theo theme qua `setStyle()`, `styleVersion`,
   `ResizeObserver` + `requestAnimationFrame` cho `resize()`, dọn dẹp lúc unmount.
7. `use-map-sync.ts` — `{hoveredId, setHoveredId, focusOn}`, cấp stage (không phải context
   toàn app).
8. `map-view.tsx`: marker (`mapboxgl.Marker` + custom HTML, registry theo sync id, diff
   thêm/xoá/di chuyển thay vì dựng lại toàn bộ), route (source + 3 layer filtered, hover qua
   `setFeatureState`, fade-in qua `line-opacity-transition`), trạng thái thiếu token.
9. `map-legend.tsx` — chỉ hiện ngày/phương tiện thật sự có trong `segments` đang render.
10. Thêm hover + `data-card` vào `timeline-item.tsx`, `hotel-option-card.tsx`
    (+ `HotelOptionCards` forward), `day-timeline.tsx` (forward). Thêm rule
    `[data-hovered='true']` vào `styles.css` mirror với `:hover` hiện có.
11. Truyền `theme` qua `app-shell.tsx` → `stage-router.tsx` → `stage-hotels.tsx`/
    `stage-workspace.tsx`. Nối `MapView` thay `MapPanel` ở cả hai stage — markers/segments
    tính bằng `useMemo` (deps KHÔNG gồm `hoveredId`, tránh decode lại polyline mỗi lần hover).
12. Thêm chuỗi map vào cả hai catalog i18n; xoá chuỗi placeholder cũ (`mapPlaceholder*`,
    `mapFilter*`, `mapSearchPlaceholder`, `mapControlDisabledHint`).
13. Xoá `map-panel.tsx` sau khi `MapView` chạy đúng ở cả hai stage.
14. Kiểm chứng: `npm run typecheck`/`lint`/`test`/`check:tokens` pass; qua `npm run mock`:
    marker đúng vị trí trên bản đồ Đà Nẵng; đổi tab ngày đổi route; hover đồng bộ hai chiều;
    vào/ra focus mode rồi map vẫn render đúng kích thước; đổi theme giữa phiên route/marker
    vẫn đúng sau `setStyle()`; thiếu `VITE_MAPBOX_TOKEN` hiện trạng thái trung thực.

## Tiêu chí hoàn thành

Rà 10/08/2026 (không mở trình duyệt thật — không có màn hình trong phiên này, theo đúng tiền
lệ đã ghi ở phase-08): các mục dưới đã đối chiếu trực tiếp với code + `npm run typecheck`/
`lint`/`test` (tất cả pass) + `npm run dev`/`npm run mock` khởi động sạch. Mục thị giác cần
người dùng tự kiểm bằng mắt trước khi coi phase đóng hoàn toàn.

- [x] Map Mapbox GL JS thật với style `streets-v12`/`dark-v11` theo theme và attribution GL JS mặc định
- [x] Marker vẽ từ `coordinates` thật; toạ độ hỏng bị bỏ, không có marker ở `(0,0)`
- [x] Route vẽ từ `polyline` Mapbox đã giải mã — **bám đường thật**, không phải đường thẳng
- [x] Fallback đường thẳng hoạt động khi `route_to_next` là `null` hoặc polyline hỏng
- [x] Chặng fallback vẽ khác chặng thật (dash/opacity/width) để phân biệt được bằng mắt
- [x] Chặng fallback là **đường thẳng**, không bị bẻ cong thành cung (`curve()` không được dùng)
- [x] `decodePolyline` port từ dashboard Airflow, có case kiểm tra; **không** thêm dependency giải mã
- [x] Route theo ngày, mỗi ngày một màu; tab Tổng quan hiện toàn chuyến, tab ngày chỉ ngày đó
- [x] Khách sạn là điểm đầu và cuối mỗi ngày khi có toạ độ
- [x] Chặng đầu ngày là đường thẳng khi `route_from_hotel` là `null` — đúng hành vi, không "sửa"
- [x] Hover đồng bộ hai chiều timeline ↔ map qua `setFeatureState`; các đoạn route khác giảm opacity
- [x] Click marker cuộn tới card tương ứng; click marker khách sạn (có `id`) mở Hotel Detail Focus Mode
- [x] Legend có ô tô và đi bộ khi dữ liệu thật sự có profile đó, cộng mục "ước lượng" cho
      chặng fallback; **không** có mục cáp treo
- [x] Map thu gọn/mở lại quanh focus mode mà vẫn đúng kích thước (`ResizeObserver` + `map.resize()`)
- [x] Đổi theme gọi `setStyle()`; route/marker re-add đúng sau khi source/layer bị xoá bởi style reload
- [x] Thiếu `VITE_MAPBOX_TOKEN` → hiện trạng thái "map chưa cấu hình" trung thực, không crash, không fallback provider khác
- [ ] Token GL JS là public + có URL restriction (thao tác thủ công trên Mapbox dashboard,
      ngoài phạm vi code — ghi ở "Đánh giá rủi ro"); **không** phải token server của Phase 12 —
      **chưa làm, cần người dùng tự tạo token trên Mapbox dashboard**
- [x] Legend chỉ hiện phương tiện thật sự có trong dữ liệu; không có mục cáp treo
- [x] `map-panel.tsx` đã xoá, chuỗi i18n placeholder cũ đã xoá theo
- [x] `npm run typecheck`, `npm run lint`, `npm run test` pass. `npm run check:tokens`
      **fail vì lý do có từ trước, không phải phase này**: thư mục so khớp
      `data/trip_planner/trip_planner_components/styles/` không tồn tại trong working tree
      (gitignored, chưa giải nén ở máy này) — `git status` xác nhận 3 file token không hề bị sửa
- [ ] `design-fidelity-checklist.md` §Phase 10 đã tick hết (khung map, thẻ chú thích) —
      **chưa tick, cần kiểm bằng mắt qua `npm run dev` + `npm run mock` trước khi tick**

## Đánh giá rủi ro

**Định dạng toạ độ là rủi ro số một của phase này.** Nếu `parseCoordinates` hiểu sai định
dạng, marker sẽ nằm sai chỗ **một cách âm thầm** — không có lỗi, chỉ là bản đồ sai. Đã xác
nhận `"lat,lng"` là định dạng thật (Phase 1/9); rủi ro còn lại là thứ tự `[lng,lat]` khi đưa
vào GL JS (`toLngLat()`) — đảo ngược thứ tự này cũng cho lỗi âm thầm tương tự, marker rơi
sai bán cầu.

**`map.resize()` bị quên là lỗi kinh điển khi map nằm trong layout động** (di sản từ Leaflet's
`invalidateSize()`, vẫn đúng với GL JS). Map thu về 0 rồi mở lại sẽ hiện tile xám hoặc lệch
nếu không gọi `resize()` đúng lúc. Dùng `ResizeObserver`, không phải `setTimeout` đoán mò.

**`setStyle()` xoá source/layer khi đổi theme.** Nếu effect dựng route không đọc đúng
`styleVersion`, route sẽ biến mất mỗi lần người dùng bật/tắt dark mode. Đây là rủi ro mới,
không tồn tại ở bản Leaflet (raster tile không có khái niệm "xoá layer khi đổi URL").

**Token tile lộ trong bundle.** Không tránh được với bản đồ phía trình duyệt. URL restriction
là biện pháp bảo vệ duy nhất và **bắt buộc** phải bật trên Mapbox dashboard trước khi deploy —
thao tác thủ công, ngoài phạm vi code của phase này.

**Thiếu fallback tile miễn phí khi chưa cấu hình token** — khác biệt so với bản Leaflet+OSM.
Chấp nhận được vì là quyết định phạm vi có chủ đích (xem §Style), không phải thiếu sót.

**Cám dỗ thêm nhãn cáp treo cho "đủ giống design".** Ô tô và đi bộ là thật vì Phase 12 gọi
đúng profile tương ứng. Cáp treo thì không có profile, không có dữ liệu — thêm vào là suy
đoán. Mục 1 bảng "Phần chưa làm"; tiêu chí hoàn thành nêu tường minh.

**Route có thể vắng trong môi trường dev.** Nếu backend chưa cấu hình `MAPBOX_ACCESS_TOKEN`
thì mọi `route_to_next` là `null` và toàn bộ map chạy nhánh fallback đường thẳng. Đường
fallback không phải nhánh hiếm — phải test kỹ như nhánh chính.

**Hiệu năng khi hover.** `hoveredId` đổi theo từng chuyển động chuột. `segments`/`markers`
tính bằng `useMemo` với deps KHÔNG gồm `hoveredId` (chỉ phụ thuộc dữ liệu thật), nên hover
không kích hoạt giải mã polyline lại; highlight chỉ gọi `setFeatureState` + toggle một
`data-hovered` attribute trên marker DOM, không render lại cây React của map.
