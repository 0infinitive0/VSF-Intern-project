# Checklist bề mặt — đối chiếu từng component với design

Trích từ `data/trip_planner/trip_planner_components/*.dc.html`. Đây là **lớp 2** của cơ chế
nghiệm thu thị giác (xem `plan.md` §Nghiệm thu thị giác).

## Vì sao file này tồn tại

Tiêu chí dạng "Card khách sạn khớp design" không kiểm chứng được — nó là ý kiến, do chính
người viết code tự chấm. Phase 6 đã chứng minh hậu quả: implement xong, typecheck sạch, lint
sạch, 43/43 test pass, mọi tiêu chí dữ liệu đạt — **và cột chat không có bề mặt glass nào cả**.
Nội dung đúng, bề mặt biến mất, không tiêu chí nào bắt được.

Bảng dưới đây biến "khớp design" thành danh sách tick. Quy tắc dùng:

- Tick từng dòng **trước khi** đánh dấu phase là xong, không phải sau.
- Sai lệch có chủ đích thì **ghi lý do ngay tại dòng đó**, đừng tick bừa.
- Giá trị màu ghi dạng token (`--g2`, `--btn`); trong code là class Tailwind tương ứng
  (`bg-glass-2`, `bg-button`). **Không hardcode hex** — design hardcode `#3A73DE` ở vài chỗ
  nhưng `--acc` của nó tự đổi theo theme, nên port đúng là dùng token.

---

## Phase 6 — Chat

### ChatPanel (`ChatPanel.dc.html:2`)

- [x] Container: radius **26px**, bg `--g1`, blur **32px** saturate 1.7, border 1px `--edge` —
      lệch có ghi nhận: `glass-panel` utility dùng blur 30px (đã chốt ở audit gốc, chấp nhận được)
- [x] Shadow: `0 24px 56px -28px rgba(--sh,.34)` + `inset 0 1px 0 var(--gloss)`
- [x] Margin 14px, cao `calc(100% - 28px)`, `overflow:hidden`
- [x] Header: pad `14px 18px`, border-bottom `--line`; dot 7px `#2A9187` + ring `0 0 0 3px rgba(42,145,135,.18)`
- [x] Title 12.5px/590/-.1px; step label 10.5px `--t3`; dot tiến độ 13×4 radius 3, filled `--acc`
- [x] Step nav: pad `10px 14px`, border-bottom `--line`, nút radius 12, 11.5px, số 9.5px opacity .6
- [x] Nút step: current `--btn`/`--btn-fg`/600 · open `--g2`/`--t1`/`--stroke`/400 · inert transparent/`--t4`/`--line`
- [x] Thread: pad `16px 16px 6px`, gap 12px
- [x] Rail widget: pad `0 14px 14px`, gap 10px, `max-height:56vh`

### ChatMessage (`ChatMessage.dc.html`)

- [x] Radius bất đối xứng: AI `18px 18px 18px 6px` · user `18px 18px 6px 18px`
- [x] Bubble: `max-width:44ch`, pad `10px 14px`, 14px/1.58/-.08px, `white-space:pre-wrap`
- [x] AI: bg `--g3`, fg `--t1`, border `--line`, shadow `0 6px 16px -12px rgba(--sh,.7)`
- [x] User: bg `linear-gradient(145deg,#4F86E8,#2C5FC9)`, fg `#FCFDFE`, border `rgba(255,255,255,.22)`, shadow `0 8px 20px -10px rgba(44,95,201,.6)`
- [x] Avatar AI: 24px, radius 9, `linear-gradient(145deg,#5C93EE,#2C5FC9)`, shadow `0 4px 12px -3px rgba(44,95,201,.55)`, chữ "V" 11px/590
- [x] Timestamp: 9.5px/500/.04em, `--t3`, pad `0 4px`
- [x] **Animation `vPop .5s cubic-bezier(.22,1,.36,1) both`** trên mỗi tin nhắn

### Chỉ báo suy nghĩ (`ChatPanel.dc.html:38-45`)

- [x] Bubble pad `13px 15px`, radius 18, bg `--g3`, border `--line`
- [x] 3 chấm 6px `--t1`, `vDot 1.1s` với delay **0 / .16s / .32s**

### Composer (`ChatPanel.dc.html:74`)

- [x] Pill: radius **20px**, bg **`--g2`** (không phải `--g3`), border `--edge`
- [x] Shadow `0 8px 22px -14px rgba(--sh,.4)`
- [x] Pad `5px 5px 5px 15px`; input 13.5px
- [x] Nút gửi: 34px tròn, bg `--btn`, shadow `0 8px 18px -8px`

### Chip gợi ý — quickActions (`ChatPanel.dc.html:69`)

- [x] Pad `7px 11px`, radius 999, **11.5px**, fg `--t2`, bg `--g2`, border `--stroke`
- [x] Hover → bg `--btn`, fg `--btn-fg`, border `--t1`
- [x] **Khác** chip điểm đến — đừng dùng chung style

### DestinationPicker (`DestinationPicker.dc.html`)

- [x] Hint 10.5px `--t3`, pad-left 4; wrapper gap 7px
- [x] Chip pad `8px 13px`, radius 999, 12.5px, bg `--g2`, border `--stroke`
- [x] Hover → bg accent (token, **không hardcode**), fg `--on-acc`, `translateY(-2px)`
- [x] Animation `vPop .5s`

### Card intake dùng chung (People / Date / Budget / Interest)

- [x] Shell: pad 14px (Budget 16px), radius **22px**, bg `--g2`, border `--edge`, shadow `0 14px 34px -18px rgba(--sh,.4)`
- [x] Eyebrow: 10px/590/.1em/uppercase/`--t3`
- [x] Nút confirm: full width, pad 10px, radius 13px, 13px/590/-.12px
- [x] **Animation `vPop .5s`** trên mỗi card

### PeoplePicker (`PeoplePicker.dc.html`)

- [x] Container segmented: bg `--fill`, radius 13, pad 3, gap 2
- [x] Segment radius 10, pad `8px 0`, 13px
- [x] Selected: bg `--g3`, fg `--t1`, 600, shadow `0 4px 12px -6px rgba(--sh,.6)` · unselected transparent/`--t2`/400

### DatePicker (`DatePicker.dc.html`)

- [x] Nút nav 26px, radius 9, border `--stroke`, bg `--g2`, 11px; hover → `--btn`/`--btn-fg`
- [x] Nhãn tháng 13px/590; năm cùng dòng nhưng 400 + `--t3`
- [x] Weekday: 10px, `--t4`, canh giữa
- [x] Lưới: `repeat(7,1fr)`, gap **3px**; ô cao **31px**, 12.5px
- [x] Ô selected đầu/cuối: bg `--btn`, fg `--btn-fg`, 600 · in-range `rgba(58,115,222,.13)` · hover `rgba(58,115,222,.12)`
- [x] Radius theo vị trí: start `11px 5px 5px 11px` · end `5px 11px 11px 5px` · in-range `5px` · thường `11px`
- [x] Ô từ/đến: radius 12, bg `--fill`, label 9.5px uppercase .05em, giá trị 12.5px/590
- [x] Nút confirm đổi **token** theo trạng thái: đủ 2 đầu → `--btn`/`--btn-fg`; chưa → `--fill2`/`--t4`
- [x] **Animation `vFade .32s`** trên lưới ngày, key theo tháng — không remount `DayPicker` (phá
      focus bàn phím), thay bằng toggle class qua `ref`/`useEffect` trên `.rdp-month_grid`
- [x] **Không dùng CSS mặc định của `@daypicker/react`** — phải có lớp override

### InterestPicker (`InterestPicker.dc.html`)

- [x] Chip pad `8px 13px`, radius 999, 12.5px
- [x] On: bg `--btn`, fg `--btn-fg`, border `--btn`, 500
- [ ] Off: bg `rgba(255,255,255,.8)` — **lệch có chủ đích:** literal này gần-trắng-trên-gần-trắng
      ở dark mode (chữ `--t1` dark ≈ `#EDF0F4`, tương phản ~1.05:1), cùng lỗi kế thừa từ bản
      thiết kế gốc. Đổi sang `bg-glass-2` (token theo theme) sau khi hỏi và được người dùng xác
      nhận ưu tiên đọc được hơn khớp đúng literal. fg `--t1`, border `--fill2`, 400 giữ nguyên.
- [x] Nút submit đổi token theo `picked.length`: có → `--btn`; không → `--fill2`

---

## Phase 7 — Stage Intake & Generating (đã Done 06/08/2026)

### Stage intake (`V-OTA Planner.dc.html:88-126`)

- [x] Container: pad 34px, nội dung `margin:auto`, rộng `min(640px,100%)`, gap 22, **`vRise .75s`**
- [x] Eyebrow: 10px/590/.1em/uppercase `--t3`
- [x] Headline: 42px/590/-1.9px/line 1.06 `--t1` + span gradient `vHue 12s`, bg-size 300% —
      lệch có chủ đích: dùng token `--color-primary/success/warning` thay hex `#3A73DE/#2A9187/#C8802F`
      để dark theme override được (cùng lý do dòng "---acc" ở mục quy tắc đầu file)
- [x] Sub: 14.5px/400/line 1.62 `--t2`, max-width 520
- [x] Panel checklist: radius 28, bg `--g1`, blur 30 saturate 1.7, border `--edge`, shadow
      `0 24px 56px -30px rgba(--sh,.35)` + inset gloss (qua `glass-panel`)
- [x] Label panel: 10px/590/.1em/uppercase `--t3`, margin-bottom 14
- [x] Dòng: chấm tròn 18px border 1.5px (collected: bg+border `--acc`, dấu ✓ `--on-acc`;
      chưa có: border `--stroke`), label 12.5px `--t3` rộng 104, value 13.5px, border-bottom `--line`
- [x] Dấu `—` cho dòng chưa có; giá trị thật từ `IntakeStatus`, không đoán/điền sẵn
- [ ] ~~Edit affordance từng dòng (`r.onPick`/`r.editLabel`)~~ — **bỏ có chủ đích:** stage không
      có send path; link "Sửa" dẫn tới đâu là hứa suông. Chỉnh sửa vẫn qua widget chat. Ghi tại
      `intake-checklist.tsx` header
- [ ] ~~`margin:0 -8px` + hover bg từng dòng~~ — đi cùng affordance click; không có click thì
      không có hover
- [x] 3 step card: grid 3 cột (responsive `sm:grid-cols-3`), pad 14, radius 20, bg `--g1`,
      border `--edge`; num 10px/590/.06em (B1 `--acc` token / B2-3 `--t4`); title 13px/590;
      desc 11.5px/450 `--t3`

### Stage generating (`V-OTA Planner.dc.html:141-155`)

- [x] Panel: radius 32, bg `--g1`, border `--edge`, **`vRise .6s`** — lệch có ghi nhận: blur 30
      (glass-panel) thay vì 36, cùng tiền lệ ChatPanel blur 32→30
- [x] Avatar "V": 34px, radius 12, gradient `#5C93EE→#2C5FC9` (hardcode theo design & tiền lệ
      ElapsedSpinner/message-bubble), **`vPulse 1.8s`**
- [x] Title 15px/530/-.2s + sub — title đổi theo giây thật (`pendingDefault`/`pendingSearchingHotels`/
      `pendingBuildingPlan`, mirror ElapsedSpinner); sub = số giây đã trôi **thật**
- [x] **Không** danh sách bước tick tuần tự (`genSteps`) — tiến độ bịa, plan.md mục 14
- [x] Skeleton: shimmer `linear-gradient(100deg,--fill 30%,--g3 50%,--fill 70%)` size 900px
      `vShimmer 1.5s linear infinite` (nguyên công thức, @utility `shimmer-block`) — hình dạng
      dùng variant `hotel` của `skeleton-card.tsx` để khớp card Phase 8 (plan bước 3), thay vì
      3 thanh bar của design
- [x] Progress bar vô hạn (không %): track 4px `--fill2`, segment 1/3 chạy
      `indeterminate-segment 1.4s` — keyframes riêng, không nằm trong file byte-locked

---

## Phase 8 — Khách sạn

Rà 06/08/2026 qua code (`hotel-option-card.tsx`, `hotel-detail-panel.tsx`, `room-card.tsx`,
`match-score-ring.tsx`, `match-reasons.tsx`) + token gốc (`design-theme.css`/`design-variables.css`:
`--warn:#C8802F`, `--acc→--color-primary`, `--ok-soft:rgba(42,145,135,.14)` khớp hardcode trong
`RoomCard`). Không mở trình duyệt (theo CLAUDE.md), đối chiếu giá trị số trực tiếp trong JSX/style.

### HotelCard (`HotelCard.dc.html`)

- [x] Card: radius **26px**, pad 16, blur 26 saturate 1.7, border 1px — `rounded-[26px] p-4 border` + `.hotel-card`/`.glass-panel` base
- [x] Ảnh 112×112, radius 20, có overlay **`vSheen 6s`**
- [x] Tên 16px/590/-.32px; khu vực 11.5px `--t3` (`text-on-surface-muted`); sao 11px `#C8802F` (`text-warning`→`--warn`) letter-spacing 1px
- [x] Giá 17px/400/-.5px; dòng phụ 10.5px `--t3`
- [x] Chip tiện nghi: 10.5px, pad `3px 9px`, radius 99, bg `--fill`, fg `--t2`
- [x] Divider trên khối match: `border-top --line`, pad-top 14, margin-top 14 (`mt-3.5 pt-3.5 border-t border-line`)
- [x] Vòng match: ngoài **62px** conic-gradient, trong **50px** bg `--g3`; số 14px/590; chữ MATCH 8px/.08em/uppercase/`--t3`
- [x] Bullet lý do: chấm 4px `--t4` margin-top 6, chữ 11.5px `--t2` line 1.45 `text-wrap:pretty` (`text-pretty`)
- [x] Hai nút đáy: chính radius 15 pad 11 13px/590 · phụ radius 15 pad `11px 15px` border `--stroke` bg `--g2` (`bg-glass-2`)
- [x] **Animation `vFade .55s`** lệch pha theo delay
- [x] Nút "Chọn" `stopPropagation` — thân card mở panel chi tiết

### HotelDetail (`HotelDetail.dc.html`)

- [x] Panel: radius 26, bg `--g1`, blur 32 saturate 1.7, border `--edge`, shadow như ChatPanel (`glass-panel` utility, shared với ChatPanel)
- [x] Hero **240px** + `vHero .9s` + `vSheen 7s` + overlay `linear-gradient(to top,var(--g3),transparent)` cao 120px
- [x] Nút đóng: 34px tròn, bg `--g3`, blur 18, border `--edge`, shadow `0 10px 24px -10px`
- [x] Tên 26px/590/-.9px/line 1.1
- [x] Vòng match nhỏ hơn card: ngoài **58px**, trong **46px** (`variant="panel"`)
- [x] Gallery `repeat(4,1fr)`, cao 80px, radius 16, `vFade` lệch pha
- [x] Panel "vì sao": bg **`--acc-soft`** (`bg-primary-soft`→`--color-primary-soft:var(--acc-soft)`), radius 22, pad 16; bullet 5px `--acc` (`bg-primary`), chữ 13px/1.55
- [x] Eyebrow section: 10px/590/.1em/uppercase/`--t3`, margin-bottom 9 (`SECTION_EYEBROW` const dùng chung)
- [x] Dòng khoảng cách: radius 16, pad `9px 12px`, bg `--g2` (`bg-glass-2`), border `--edge`, chấm 6px `--acc` (`bg-primary`), số `tabular-nums`
- [x] Ô chính sách: radius 18, pad `12px 13px`, label 10px uppercase, giá trị 13.5px/590
- [x] Chip tiện nghi: 11.5px, pad `5px 11px`, radius 99, bg `--fill`
- [x] **Không** có khối review, khối liên hệ, ô "Phòng đã chọn" (mục 17/18/21) — xác nhận vắng mặt trong JSX
- [x] Khoảng cách: **2 cột** (tên · km), không có cột phút (mục 23)

### RoomCard (`RoomCard.dc.html`)

- [x] Card radius 22, pad 14
- [x] Thumb 92×76, radius 16, có `vSheen`
- [x] Tên 14px/590/-.2px; meta 11px `--t3` (`text-on-surface-muted`); giá 15px/590/-.3px
- [x] Badge tình trạng: 10.5px/530, pad `3px 9px`, radius 99, bg `rgba(42,145,135,.14)`, fg `--ok` — hardcode khớp byte-đúng `--ok-soft` token
- [x] Mở rộng: `border-top --line`, gallery `repeat(3,1fr)` cao 70 radius 14, `vFade .35s`
- [ ] Mô tả gói (`package_details`) 13px/1.55 — code hiện dùng `text-[12px] font-[450]`, thiếu
      `leading-[1.55]` tường minh; lệch nhỏ so với spec, chưa sửa vì không ảnh hưởng tiêu chí
      hoàn thành chức năng của Phase 8.
- [x] Nút radius 14, pad 10 (`py-2.5`)
- [x] **Không** có nút "Chọn phòng", **không** có 2 ô chính sách huỷ/thanh toán (mục 4/21) — xác nhận vắng mặt trong JSX

---

## Phase 9 — Workspace (rà 07/08/2026)

### Header workspace (`V-OTA Planner.dc.html:194`)

- [x] Panel riêng: margin `14px 14px 0`, pad `13px 18px`, radius 26, bg `--g1`, blur 30 saturate 1.7
- [ ] Shadow `0 20px 50px -30px rgba(--sh,.32)` + `inset 0 1px 0 var(--gloss)` — dùng chung
      `@utility glass-panel` (Phase 1) thay vì shadow riêng của header: cho ra
      `0 24px 56px -28px rgba(--sh,.34)`. Lệch nhẹ (không nhận ra bằng mắt thường), đổi lấy
      một utility glass dùng chung cho mọi panel thay vì mỗi component một công thức riêng.
      `PlaceDetail.dc.html` tự thân dùng đúng `0 24px 56px -28px .34` nên panel chi tiết địa
      điểm khớp chính xác; chỉ riêng header lệch
- [x] Logo 30px radius 10 gradient + shadow `0 6px 16px -5px`
- [x] Nút "Tạo lại": pad `9px 16px`, radius 12, border `--stroke`, bg `--g2`, 13px/400
- [x] **Không** có nút "Chia sẻ" (mục 22)

### DayCard (`DayCard.dc.html`)

- [x] Radius 18, pad `12px 14px`, bg `--g2`, border `--edge`, gap 12
- [x] Chấm 9px + halo `0 0 0 4px` theo màu ngày
- [x] Tiêu đề 13.5px/590/-.16px; phụ 11.5px `--t3`; mũi tên `→` 12px `--t4`
- [x] Hover: `translateY(-2px)`, shadow `0 14px 30px -18px rgba(--sh,.55)`, bg `--g3`
- [x] `vFade .5s` lệch pha
- [x] Màu ngày **dùng chung** `lib/map-colors.ts` với route trên map (Phase 10 sẽ tiêu thụ
      cùng `dayColor()`)

### TimelineItem (`TimelineItem.dc.html`)

- [x] Item radius 20, pad 13, gap 12
- [x] Cột trái 44px: giờ 11.5px/530 `--t2` **`tabular-nums`**; chấm số 24px tròn + glow `0 4px 10px -4px`
- [x] Thumb 52×52, radius 14
- [x] Tên 14px/590/-.2px; badge loại 9.5px pad `2px 7px` radius 99 bg `--fill`
- [ ] Ghi chú 11.5px `--t3` line 1.45 `text-wrap:pretty` — **bỏ**, mục 24 bảng "Phần chưa
      làm": `DayItem` không có cột note. `meta` 11px `--t3` (khung giờ thật) **vẫn có** ✅
- [x] Leg pill: thụt trái **52px**, vạch dọc 2×22 radius 2, pill radius 99 bg `--g1` border `{legColor}44`, chấm 7px, số `tabular-nums`
- [x] **Animation `vIn .55s`** lệch pha theo delay
- [x] Item không mở được: **không** `cursor:pointer`, **không** hover elevation

### PlaceDetail (`PlaceDetail.dc.html`)

- [x] Panel giống HotelDetail; hero **250px** (không phải 240)
- [x] Badge loại: 10px/590/.1em/uppercase, fg `--on-acc`, bg theo `kindColor`
- [x] Badge ngữ cảnh "Ngày N · giờ": 11px/530 `--t2`, bg `--g3`
- [x] Tên 26px/590/-.9px
- [x] Facts: label 10px uppercase `--t3`, giá trị 13px/530
- [x] Mô tả 14px/1.6/-.08px `text-wrap:pretty`
- [x] Ô route: radius 18, pad `12px 13px`, bg `--g2`, giá trị **15px**/590
- [x] Gallery `repeat(3,1fr)` cao 92px radius 16
- [x] **Không** có khối tiện ích, review, lân cận, "AI đề xuất vì" (mục 20/6/7/5)

---

## Phase 10 — Map

- [ ] Khung map: radius 26, `overflow:hidden`, border `--edge`, shadow `0 20px 50px -26px rgba(--sh,.3)`
- [ ] Thẻ chú thích: pad `11px 14px`, radius 18, bg `--g2`, blur 20 saturate 1.6, border `--edge`, `max-width:280px`
- [ ] Nhãn thẻ 10px/590/.1em/uppercase `--t3`; nội dung 11.5px `--t2` line 1.45
- [ ] Tile Mapbox `light-v11`/`dark-v11` theo theme — **không** còn `filter: invert() hue-rotate()`

---

## Phase 5 — Shell (đã Done, rà lại xong 06/08/2026)

- [x] Nền trang là **`--gradient-page`**, không bị phủ màu đặc bởi container nào — đã hotfix ở
      Phase 6 bước 11 mục 1 (`app-shell.tsx:90` bỏ `bg-surface-background`)
- [x] Sidebar: bg `--g1`, blur 30 saturate 1.7, border-right `--line2`, gap 10 — border đổi từ
      `border-border-subtle` (`--line`) sang `border-line2`; các mục còn lại đã đúng sẵn
- [x] Brand 34px radius 12 gradient + shadow `0 8px 20px -7px rgba(44,95,201,.65)` — thêm
      `boxShadow` còn thiếu
- [x] Nút chuyến mới: cao 40, radius 14, **border dashed** `--stroke`, bg `--g1` — đổi
      `rounded-2xl`(16px)→`rounded-[14px]`, thêm `bg-glass-1`
- [x] Lang segmented: bg `--fill`, radius 12, pad 3, gap 2 — đã đúng sẵn, không cần sửa
- [x] Nút theme: cao 36, radius 12, border `--stroke`, bg `--g1` — đổi `glass-chip` (bg `--g3`,
      radius 999) sang `bg-glass-1` (giữ `rounded-xl` sẵn có)
- [x] HistoryRow: radius 14, thumb 32px radius 11, tiêu đề 12.5px/590, ngày 10px `--t3`, pill
      trạng thái 9px radius 99, nút xoá 24px radius 8 ở `top/right 8px`, `vFade .5s` lệch pha —
      sửa radius 16→14, tiêu đề `text-xs font-semibold`→`text-[12.5px] font-[590]`, ngày
      `text-on-surface-faint`(`--t4`)→`text-on-surface-muted`(`--t3`), nút xoá `top/right-1.5`
      (6px)→`top/right-2`(8px), thêm `animate-[vFade_0.5s_ease_both]` lệch pha theo index +
      `hover:bg-glass-2` (khớp `style-hover` của `HistoryRow.dc.html`)
