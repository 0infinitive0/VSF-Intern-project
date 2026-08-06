---
phase: 5
title: "[FE] Design System & App Shell"
status: done
priority: P1
effort: "2-2.5 ngày"
dependencies: [1]
track: frontend
---

# Phase 5: [FE] Design System & App Shell

## Tổng quan

Thay layout 3 panel phẳng hiện tại bằng shell của design: **sidebar rail thu gọn được →
chat cố định → stage bên phải**, thêm chuyển theme, và dựng các primitive glass dùng chung
mà mọi phase sau sẽ lắp ghép từ đó.

Đây là phase cấu trúc. Phase 6-10 chỉ điền vào các vùng mà phase này tạo ra; không phase nào
trong số đó phải sửa lại `App.tsx` nữa.

## Yêu cầu

**Chức năng**
- Sidebar rail: logo, "Chuyến đi mới", chỗ dành cho lịch sử hội thoại, chuyển ngôn ngữ,
  chuyển theme, thu gọn/mở rộng — chiều rộng có animation, khi thu gọn chỉ còn icon
- Chat panel **cố định qua mọi stage** (yêu cầu trung tâm của bản export) và **không bao giờ
  bị unmount**, chỉ được transform
- Stage bên phải render một trong bốn trạng thái, suy ra từ `ChatState` đang có
- Focus mode thu gọn chat và map ra ngoài màn hình rồi mở rộng stage — bằng CSS transform
  trên container dùng chung, **không bao giờ bằng unmount**
- Toggle theme đặt `data-theme` trên `<body>`, lưu vào `localStorage`
- Giữ nguyên hành vi cũ: bootstrap session, gửi tin, reset, chuyển ngôn ngữ

**Phi chức năng**
- State chat phải sống sót qua mọi chuyển stage và focus — không remount, không mất dữ liệu
- Responsive: dưới `lg` sidebar phủ lên thay vì đẩy; dưới `md` stage xếp xuống dưới chat
- Mọi motion tôn trọng `prefers-reduced-motion`

## Kiến trúc

### Suy ra stage — không thêm state mới

Bốn trạng thái stage được **suy ra** từ `ChatState` app đã có. Không đổi backend, không
thêm store:

```ts
// lib/derive-stage.ts
export type StageView = 'intake' | 'generating' | 'hotels' | 'workspace'

export function deriveStageView(state: ChatState): StageView {
  if (state.pending && state.tripPlan == null && state.hotelOptions.length === 0)
    return 'generating'
  if (state.hotelOptions.length > 0) return 'hotels'
  if (state.tripPlan != null) return 'workspace'
  return 'intake'
}
```

Thứ tự ưu tiên quan trọng và phải có test: khi đã có `tripPlan`, người dùng vẫn có thể quay
lại chọn khách sạn, nên `hotels` phải được kiểm tra **trước** `workspace`. `generating` chỉ
kích hoạt khi đang pending **và** chưa có gì để render, nên một lượt chat giữa chừng không
làm trắng workspace.

Focus mode mới thật sự là state UI mới, do một hook nhỏ sở hữu:

```ts
// hooks/use-focus-mode.ts
type Focus = { kind: 'hotel'; id: string } | { kind: 'place'; id: string } | null
```

### Layout

```
┌─────────┬───────────────┬─────────────────────────────────┐
│ Sidebar │ Chat (cố định) │ Stage                          │
│  rail   │                │  intake | generating |         │
│ 76↔248px│   360-420px    │  hotels+map | workspace+map    │
└─────────┴───────────────┴─────────────────────────────────┘
     focus mode: chat →translateX(-100%), map →thu gọn,
                 stage mở rộng sang trái, panel chi tiết hiện bên phải
```

Chiều rộng animate bằng `--ease-glide` trong 0.42s (sidebar) / 0.62s (chat, stage). Bản
export làm điều này bằng transition `width`/`margin`/`transform` — hãy theo đúng cách đó,
đừng đưa thêm thư viện layout vào.

**Giữ `usePanelResize`.** Hook kéo-để-đổi-kích-thước hiện có vẫn áp dụng cho vách ngăn
chat/stage và là một tính năng thật; nó chỉ thao tác trên container mới. Lưu chiều rộng vào
đúng chỗ state component như hôm nay.

### Sidebar và lịch sử

Dựng đầy đủ rail. Danh sách hội thoại tiêu thụ `GET /chat/sessions` (Phase 4, đã mock ở
Phase 1) nhưng phải render sạch cả ba trạng thái:

- **đang tải** — skeleton rows
- **rỗng / endpoint chưa có (404)** — không render header và list; không báo lỗi, không dòng
  giả. Đây chính là thứ sẽ ship nếu Phase 4 bị cắt.
- **có dữ liệu** — dòng thật với title, ngày, pill trạng thái, thumbnail, nút xoá khi hover

Coi `404` từ `/chat/sessions` là "tính năng chưa có", **không phải** trạng thái lỗi.

### Danh sách component

Tạo mới, đặt trong thư mục `components/` phẳng theo quy ước hiện có, tên file kebab-case:

| File | Vai trò |
|---|---|
| `app-shell.tsx` | lưới ba vùng, transform cho focus mode |
| `sidebar-rail.tsx` | logo, chuyến-đi-mới, chỗ lịch sử, ngôn ngữ, theme, thu gọn |
| `conversation-list.tsx` | dòng lịch sử + ba trạng thái |
| `theme-toggle.tsx` | chuyển sáng/tối |
| `glass-panel.tsx` | primitive bề mặt dùng chung (`variant`: panel / card / chip) |
| `stage-router.tsx` | render trạng thái stage, chứa transition focus mode |

Tái dùng nguyên vẹn trong phase này: `use-chat-session`, `use-panel-resize`, `chat-client`,
`i18n`, `language-toggle`, `types`.

`language-toggle.tsx` được **restyle, không thay thế** — bản export đặt một segmented control
VI/EN trong sidebar, vẫn là component đó với class mới và vị trí mới.

## File liên quan

- Tạo: `frontend/src/components/app-shell.tsx`, `sidebar-rail.tsx`,
  `conversation-list.tsx`, `theme-toggle.tsx`, `glass-panel.tsx`, `stage-router.tsx`
- Tạo: `frontend/src/hooks/use-theme.ts`, `use-focus-mode.ts`
- Tạo: `frontend/src/lib/derive-stage.ts`
- Tạo: `frontend/src/api/session-client.ts` — gọi list/restore/delete
- Sửa: `frontend/src/App.tsx` — trở thành lớp composition mỏng trên `AppShell`
- Sửa: `frontend/src/components/language-toggle.tsx` — restyle + đổi vị trí
- Sửa: `frontend/src/i18n/locales/{en,vi}.json` — chuỗi cho shell
- Xoá: chưa xoá gì — markup header cũ chuyển vào `sidebar-rail`, còn
  `map-panel.tsx` / `itinerary-panel.tsx` giữ nguyên đến khi phase 9-10 thay thế

## Các bước thực hiện

1. `use-theme.ts` — đọc `localStorage`, mặc định sáng, ghi `data-theme` lên `<body>`, lưu
   khi đổi. Theo đúng quy ước khoá lưu trữ của module `i18n` hiện có.
2. `glass-panel.tsx` — wrapper mỏng trên các utility CSS ở Phase 1, để các phase sau không
   bao giờ phải tự viết lại công thức glass.
3. `derive-stage.ts` + kiểm tra dạng unit cho các quy tắc ưu tiên ở trên.
4. `use-focus-mode.ts` — mở/đóng/đổi. Đổi giữa hai khách sạn khi đang focus phải cập nhật
   đối tượng chi tiết mà **không** đóng focus mode (yêu cầu tường minh của design).
5. `app-shell.tsx` — ba vùng, transition width/transform, thu gọn focus mode. Chat và map
   được transform và `pointer-events: none`, **không bao giờ unmount**.
6. `sidebar-rail.tsx` — trạng thái thu gọn, toàn bộ controls. Chuyển nút reset "chuyến đi
   mới" (kèm hộp thoại xác nhận) từ header cũ sang đây.
7. `session-client.ts` + `conversation-list.tsx` với ba trạng thái; 404 ⇒ ẩn.
8. `stage-router.tsx` — render bốn trạng thái. Ở phase này, ba cái là placeholder;
   `workspace` render **`ItineraryPanel` + `MapPanel` hiện có** để app vẫn chạy đầy đủ
   giữa các phase.
9. Viết lại `App.tsx` chỉ còn composition.
10. Thêm khoá i18n cho shell vào cả hai catalog.
11. Kiểm chứng: kịch bản hội thoại mock vẫn chạy trọn; chat **không remount** qua các lần đổi
    stage (kiểm bằng render counter, hoặc gõ dở một tin nhắn rồi xác nhận nó còn nguyên);
    theme được lưu; bàn phím đi tới được mọi control trong sidebar.

## Tiêu chí hoàn thành

- [x] Shell render sidebar + chat cố định + stage; sidebar thu gọn mượt
- [x] Chat panel không bao giờ bị unmount qua bất kỳ chuyển stage hay focus nào
- [x] Cả bốn trạng thái stage suy ra đúng; quy tắc ưu tiên đúng (7 vitest case,
  bao gồm cả hai rủi ro ưu tiên nêu ở "Kiến trúc")
- [x] Focus mode thu gọn chat+map và mở rộng stage mà không unmount cái nào —
  cơ chế transform-only đã đúng (xác nhận qua code review); **chưa có UI nào
  gọi `openFocus` trong phase này** (đúng phạm vi — trigger là việc của
  Phase 8/9), nên chưa test được end-to-end bằng tay
- [x] Đổi đối tượng focus khi đang focus không làm đóng focus mode (đúng theo
  thiết kế hook, cùng giới hạn "chưa có trigger" ở trên)
- [x] Toggle theme chạy, được lưu, và cả hai theme đều đọc được; thêm inline
  script tránh flash theme sáng khi tải lại ở chế độ tối
- [x] Danh sách lịch sử xử lý được đang tải / rỗng / 404 / có dữ liệu mà không
  có dữ liệu giả; dòng lịch sử **chưa clickable** (mở lại hội thoại cần
  hydrate `use-chat-session.ts`, ngoài phạm vi phase này) nên render như
  hiển thị tĩnh, không phải nút chết
- [x] Luồng cũ nguyên vẹn: bootstrap, gửi tin, reset+xác nhận, chuyển ngôn ngữ,
  kéo đổi kích thước panel
- [x] Responsive ở `sm` / `md` / `lg` / `xl`, không có scroll ngang toàn trang
- [x] `npm run typecheck` và `npm run lint` pass; thêm `npm run test` (vitest)
- [ ] **Mở lại sau audit 06/08/2026:** `design-fidelity-checklist.md` §Phase 5 (nền gradient,
      sidebar, HistoryRow). Phase này đã đánh Done trước khi có cơ chế nghiệm thu thị giác, và
      audit tìm thấy `app-shell.tsx:90` phủ `bg-surface-background` đặc lên `--gradient-page` —
      giết toàn bộ hệ glass của app. Sửa nằm ở Phase 6 bước 11 mục 1; tick lại dòng này sau đó
  cho `derive-stage.ts`

Review vòng đầu (code-reviewer subagent) phát hiện 3 bug thật do thiếu
`display:flex` trên các wrapper mới (chat panel mất chiều cao, resizer cao
0px, sidebar thu gọn che nội dung dưới `lg`) — cả ba đã sửa và verify lại
bằng typecheck/lint/vitest/build. Chi tiết đầy đủ trong báo cáo cuối phase.

## Đánh giá rủi ro

**Remount chat là lỗi cần đề phòng nhất.** Toàn bộ mục đích của bản redesign là chat cố
định; nếu `stage-router` được đặt sao cho việc đổi stage khiến React reconcile lại cây con
chứa chat, thì nội dung đang gõ dở và vị trí cuộn sẽ mất. Giảm thiểu: chat nằm **ngang hàng**
với stage trong `app-shell`, không bao giờ nằm bên trong nó, và bước kiểm chứng phải test
tường minh việc nội dung gõ dở còn nguyên.

**Transform focus mode trên lớp glass bị blur có thể giật.** Chỉ animate `transform` và
`opacity` — tuyệt đối không animate `width`/`height` trong transition focus — và giữ số lớp
blur chồng nhau ở mức thấp.

**Viết lại `App.tsx` chạm vào gốc của app.** Hãy merge nó khi kịch bản hội thoại mock đã chạy
được, trước khi bắt đầu Phase 6; các phase sau đều giả định shell đã ổn định.
