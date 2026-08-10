# Design audit — Phase 6 (FE Chat panel)

Đối chiếu: `frontend/src/**` (uncommitted changes) ↔ `data/trip_planner/trip_planner_components/*`
(`ChatPanel.dc.html`, `ChatMessage.dc.html`, `DestinationPicker`, `PeoplePicker`, `DatePicker`,
`BudgetSlider`, `InterestPicker`, `styles/*.css`) và `data/design/V-OTA Planner.dc.html`
(nguồn tính toán style: dòng 2296-2332, 2505-2570, 2223-2245).

**Kết luận ngắn:** logic phase-06 làm đúng (progressive disclosure, step navigator, wire
protocol nguyên vẹn, i18n đủ, typecheck/lint/43 test pass). **Phần thị giác thì lệch** — và
lệch ở tầng nền, nên mọi thứ bên trên dù đúng số đo vẫn không ra được cảm giác của design.

---

## P0 — Nền glass không tồn tại

### F1. Cột chat không có bề mặt glass — `chat-panel.tsx:73`

Design `ChatPanel.dc.html:2`:

```
border-radius:26px; background:var(--g1);
backdrop-filter:blur(32px) saturate(1.7);
border:1px solid var(--edge);
box-shadow:0 24px 56px -28px rgba(var(--sh),.34), inset 0 1px 0 var(--gloss);
margin:14px 0 14px 14px; height:calc(100% - 28px); overflow:hidden
```

Hiện tại: `<section className="flex flex-col shrink-0 min-h-0 h-full">` — không background,
không border, không radius, không shadow, không margin. Utility `glass-panel` đã tồn tại từ
Phase 1 (`styles.css:230-238`) nhưng chỉ `sidebar-rail.tsx` dùng.

Hệ quả: header divider và step-navigator divider đang vẽ trên nền đặc, chat dính sát mép màn
hình, không có panel nổi như design.

Sửa: `glass-panel rounded-[26px] overflow-hidden` + margin cấp từ `app-shell.tsx` container
(`m-3.5 h-[calc(100%-28px)]`). Blur của utility là 30px so với 32px của design — chấp nhận
được, không cần thêm variant.

### F2. Shell phủ màu đặc lên page gradient — `app-shell.tsx:90`

`styles.css:169` set `body { background: var(--gradient-page) }` đúng như design
(`dc.html:45,79`). Nhưng root shell vẽ đè `bg-surface-background` = `#ffffff` (dark:
`#1e2126`).

Hệ quả: **mọi bề mặt glass trong app đang blur trên nền phẳng một màu.** Đây là nguyên nhân
trực quan số một khiến UI "không giống design" — glassmorphism không có gì để khúc xạ.

Sửa: bỏ `bg-surface-background` khỏi root (để body gradient lộ ra).

> File thuộc phase-05 nhưng chặn tiêu chí "Chat khớp design" của phase-06 → sửa trong phase
> này, không đợi.

---

## P1 — Lệch token màu / công thức bề mặt

### F3. Hardcode `#3A73DE` phá dark mode

- `intake-destination-chips.tsx:39-40` (selected bg/border + hover)
- `suggestion-chips.tsx:31` (hover)

Design hardcode literal trong light, nhưng `--acc` của design **tự đổi theo theme**
(`theme.css:6` → `#6C9BF0`). Port trung thực là dùng token: `bg-primary` / `border-primary` /
`hover:bg-primary`. Hiện chip ở dark mode ra accent của light → sai contrast.

### F4. Composer pill sai công thức — `composer.tsx:47`

| | Design (`ChatPanel.dc.html:74`) | Hiện tại |
|---|---|---|
| background | `var(--g2)` (0.76) | `glass-chip` → `--g3` (0.92) |
| border | `1px var(--edge)` | có (qua glass-chip) |
| shadow | `0 8px 22px -14px rgba(var(--sh),.4)` | **không có** |
| padding | `5px 5px 5px 15px` | `pl-4 pr-1.5 py-1.5` (16/6/6) |

### F5. Suggestion chips dùng style của DestinationPicker — `suggestion-chips.tsx:31`

Design quickActions (`ChatPanel.dc.html:69`): `padding:7px 11px; font-size:11.5px;
color:var(--t2); background:var(--g2); border:1px solid var(--stroke)`, hover →
`background:var(--btn); color:var(--btn-fg); border-color:var(--t1)`.

Hiện tại: 12.5px, `--g3`, `text-on-surface`, hover accent xanh + translate-y — đó là công
thức của chip điểm đến, không phải quick action.

### F6. Nút confirm không đổi token theo trạng thái

Design dùng **màu** để báo trạng thái, impl dùng `disabled:opacity-50`:

- `intake-preference-chips.tsx:51` — design `interestBtnBg = picked.length ? var(--btn) :
  var(--fill2)` (`dc.html:2569`)
- `intake-date-range.tsx:139` — design `datesBtnBg = dStart&&dEnd ? var(--btn) : var(--fill2)`,
  `fg = var(--btn-fg) : var(--t4)` (`dc.html:2560`)

### F7. Chip sở thích chưa chọn — `intake-preference-chips.tsx:41`

Design (`dc.html:2326-2329`): bg `rgba(255,255,255,.8)`, border `var(--fill2)`, fg `var(--t1)`.
Impl `bg-glass-3` + `hover:bg-glass-3` — hover là no-op.

---

## P2 — Motion và calendar

### F8. Toàn bộ motion token đang chết

`grep vPop|vRise|vIn|vFade src/components/*.tsx` → **0 kết quả**. Keyframes đã port vào
`styles.css:278-340` từ Phase 1 nhưng không ai dùng.

Design gắn:
- `animation:vPop .5s cubic-bezier(.22,1,.36,1) both` lên **ChatMessage** và **cả 5 picker card**
- `animation:vFade .32s ease both` lên lưới ngày của DatePicker, keyed theo tháng
  (`calKey`) — chính là "animation khi chuyển tháng" mà plan yêu cầu

### F9. Calendar dùng CSS mặc định của thư viện — `intake-date-range.tsx:8`

`import '@daypicker/react/style.css'` nguyên bản, và **không có một selector `.rdp*` nào trong
toàn bộ `src/`**. Lịch đang hiển thị theo default của `@daypicker/react`: font, kích thước ô,
màu selected, màu range, hover — không cái nào là design.

Design (`DatePicker.dc.html:16-25`, `dc.html:2237-2243`):

| | Giá trị |
|---|---|
| lưới | `grid-template-columns:repeat(7,1fr)`, gap 3px |
| ô ngày | height 31px, font 12.5px |
| weekday | 10px, `var(--t4)`, canh giữa |
| selected (đầu/cuối) | bg `var(--btn)`, fg `var(--btn-fg)`, weight 600 |
| in-range | bg `rgba(58,115,222,.13)` |
| hover | `rgba(58,115,222,.12)` |
| radius | start `11px 5px 5px 11px` · end `5px 11px 11px 5px` · in-range `5px` · thường `11px` |

Đây là khoảng cách thị giác lớn thứ hai sau F1/F2.

---

## Đã bám sát design — không cần đụng

- **Header** — dot 7px + ring shadow, title 12.5px/590, stepLabel 10.5px `--t3`, 5 progress
  dots 13×4 radius 3, filled dùng `bg-primary` (đúng `var(--acc)` theme-aware). Khớp.
- **StepNavigator** — bg/fg/border/weight/cursor khớp đúng bảng `steps3` (`dc.html:2507-2518`),
  kể cả trạng thái `open` vs `current` vs inert. Điều hướng lùi gửi tin nhắn ngôn ngữ tự nhiên
  đúng như plan chốt, không có rollback giả.
- **MessageBubble** — radius bất đối xứng 18/6, max 44ch, gradient user
  `linear-gradient(145deg,#4F86E8,#2C5FC9)`, border `rgba(255,255,255,.22)`, shadow, timestamp
  9.5px/`--t3`. Khớp từng giá trị.
- **ElapsedSpinner** — 3 chấm `vDot` delay 0/.16/.32, bubble `--g3` + `--line`, padding 13/15,
  radius 18. Khớp; caption số giây giữ lại đúng như plan yêu cầu.
- **IntakePeopleStepper** — segmented `--fill` container, selected `--g3` + shadow
  `0 4px 12px -6px`, weight 600/400. Khớp `dc.html:2313-2319`.
- **Wire protocol** — `compose-intake-message.ts`, `intake-options.ts`, `chat-client.ts` diff
  sạch tuyệt đối. `use-chat-session.ts` chỉ thêm field `at` (3 dòng) — đúng phạm vi plan cho
  phép ở bước 3.
- **Chất lượng** — `tsc --noEmit` sạch, `oxlint` sạch, 43/43 test pass, 28 khoá i18n phase-06
  có đủ ở cả `vi.json` và `en.json`.

---

## Sai lệch trạng thái plan

`plan.md:157` vẫn ghi Phase 6 = `Pending` và frontmatter `phase-06` là `status: pending`, trong
khi code đã implement gần xong. Cập nhật thành `in-progress` cho tới khi F1-F9 đóng.

## Câu hỏi chưa giải quyết

1. F2 sửa ở `app-shell.tsx` (file của phase-05, đã đánh dấu Done) — chấp nhận sửa xuyên phase,
   hay tách thành hotfix riêng cho phase-05?
2. Margin 14px của chat panel: đặt ở `app-shell.tsx` container hay ở chính `chat-panel.tsx`?
   Đặt ở shell thì `panel-resizer` và `chatGutter` (`app-shell.tsx:78`) phải cộng bù 14px.
