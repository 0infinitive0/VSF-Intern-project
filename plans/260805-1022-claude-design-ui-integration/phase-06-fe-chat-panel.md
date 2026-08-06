---
phase: 6
title: "[FE] Chat panel cố định"
status: done
priority: P1
effort: "2-2.5 ngày"
dependencies: [5]
track: frontend
---

# Phase 6: [FE] Chat panel cố định

## Tổng quan

Restyle cột chat theo design và sắp xếp lại các ô nhập intake thành progressive disclosure.
Contract dữ liệu của chat **không đổi chút nào** — đây thuần tuý là phần trình bày cộng với
trải nghiệm nhập liệu, chạy trên đúng reducer `useChatSession` và đúng wire protocol
`composeIntakeMessage` hiện có.

## Yêu cầu

**Chức năng**
- Header chat: chấm trạng thái, tên chuyến đi, nhãn bước, dãy chấm tiến độ
- Step navigator: ba bước, cho biết đang ở đâu; bước đã hoàn thành thì bấm được
- Bong bóng tin nhắn theo design: avatar AI, bo góc bất đối xứng, timestamp, rộng tối đa 44ch
- Trạng thái suy nghĩ: animation ba chấm (thay cho spinner đếm giây thô trong luồng)
- Progressive disclosure: chip điểm đến, segmented số người, lịch chọn khoảng ngày, chip mức
  ngân sách, chip sở thích — mỗi cái chỉ hiện khi AI đang hỏi đúng field đó
- Composer: pill glass, nút gửi tròn
- Mọi chuỗi đều được dịch; định dạng ngày/số theo locale

**Phi chức năng**
- Giá trị wire gửi lên backend **giống hệt từng byte** so với hôm nay
- Thời gian đã trôi vẫn được hiển thị (nó trung thực và hữu ích) — chỉ đổi chỗ, không xoá
- Toàn bộ khối nhập liệu đi được bằng bàn phím và có nhãn cho screen reader

## Kiến trúc

### Cái gì tuyệt đối không được đổi

`composeIntakeMessage` (`lib/compose-intake-message.ts`) chuyển lựa chọn trên form thành các
cụm tiếng Việt chuẩn mà cơ chế match regex/closed-set của backend mong đợi
(`trip_intake.py:30-64`, `hotel_selection.py:509-531`). Plan i18n đã cố ý tách *nhãn hiển
thị* khỏi *giá trị wire* chính vì lý do này.

> **Quy tắc của phase này: restyle và sắp xếp lại các ô nhập; tuyệt đối không đụng vào các
> chuỗi mà `composeIntakeMessage` phát ra.**

Tương tự với chọn khách sạn: bấm chọn vẫn gửi `String(hotel.index)` như một tin nhắn thường.
Không có verb mới.

### Progressive disclosure

Hiện `IntakeParametersForm` render mọi field cùng lúc (386 dòng). Design chỉ hiện **một card
tại một thời điểm**, theo đúng field mà AI đang hỏi. Cơ chế điều khiển đã có sẵn trong
payload: `intake.missing[]`.

```ts
// lib/next-intake-field.ts
const ORDER = ['destination', 'people', 'dates', 'budget', 'preferences'] as const
export function nextIntakeField(intake: IntakeStatus | null) {
  if (!intake) return null
  return ORDER.find(f => intake.missing.includes(f)) ?? null
}
```

Phải xác minh bộ giá trị thật của `intake.missing` với `IntakeStatus.from_state` trước khi
dựa vào các khoá này — nếu tên khác thì ánh xạ ngay tại đây, một chỗ duy nhất, chứ đừng rải
điều kiện khắp nơi.

Tách form khổng lồ thành năm component tập trung. Đây đúng là phần modularization mà quy
tắc dự án yêu cầu, và mỗi cái tương ứng một card thật trong design:

| Component | Thay cho | Nguồn giá trị wire |
|---|---|---|
| `intake-destination-chips.tsx` | phần điểm đến | `intake.available_destinations` |
| `intake-people-stepper.tsx` | phần số người | segmented 1-5+ |
| `intake-date-range.tsx` | `date-field.tsx` | lịch chọn khoảng |
| `intake-budget-tiers.tsx` | phần ngân sách | `intake.budget_options` — **giá trị VI chuẩn** |
| `intake-preference-chips.tsx` | phần sở thích | nhãn sở thích closed-set |

`intake-parameters-form.tsx` trở thành orchestrator mỏng: chọn field hiện tại, render card
đó, submit qua `composeIntakeMessage` **không đổi**.

**Ngân sách giữ dạng chip theo mức** (quyết định đã chốt). Slider 500k–50M của design đã
được ghi vào bảng "Phần chưa làm" của plan, mục 9.

### Lịch chọn khoảng ngày

`@daypicker/react` và `date-fns` đã là dependency sẵn. Design muốn điều hướng theo **tháng
và năm**, chọn khoảng, tóm tắt từ/đến, và animation khi chuyển tháng — tất cả đều được hỗ
trợ. Hãy restyle chứ đừng thay thế, và giữ `formatTripDateRange` để hiển thị.

Định dạng theo locale đúng `Internationalization.md`: `15/08/2026` (vi) so với
`Aug 15, 2026` (en) — điều khiển từ `i18n.language` qua locale của `date-fns`.

### Step navigator và tiến độ

Ba bước: *Thu thập thông tin → Chọn khách sạn → Lịch trình*, suy ra từ đúng
`deriveStageView` mà shell đang dùng — một nguồn sự thật duy nhất, không thể lệch nhau.

Điều hướng lùi được làm trung thực: bước đã hoàn thành thì bấm được và **gửi một tin nhắn
ngôn ngữ tự nhiên** (ví dụ chuỗi đã dịch "Tôi muốn đổi khách sạn"), vì đó là điều backend
thực sự hỗ trợ. Không có verb rollback, và cũng không giả vờ có. Bước chưa tới thì trơ.

### Ba chấm suy nghĩ so với đồng hồ đếm

Design hiện ba chấm động. `ElapsedSpinner` hiện số giây thật — trung thực và đáng giữ. Hãy
ship ba chấm làm chỉ báo trong luồng, và đưa số giây đã trôi thành caption nhỏ bên dưới khi
thời gian chờ vượt vài giây. Không có gì bị bịa và không mất thứ gì hữu ích.

## File liên quan

- Sửa: `frontend/src/components/chat-panel.tsx` — header, tiến độ, step navigator
- Sửa: `frontend/src/components/message-list.tsx` — layout, timestamp, điều kiện hiển thị
- Sửa: `frontend/src/components/message-bubble.tsx` — bong bóng theo design
- Sửa: `frontend/src/components/composer.tsx` — pill glass
- Sửa: `frontend/src/components/suggestion-chips.tsx` — chip glass
- Sửa: `frontend/src/components/elapsed-spinner.tsx` — ba chấm + caption số giây
- Sửa: `frontend/src/components/intake-parameters-form.tsx` — thành orchestrator
- Tạo: năm component `intake-*.tsx` ở trên
- Tạo: `frontend/src/components/step-navigator.tsx`
- Tạo: `frontend/src/lib/next-intake-field.ts`, `frontend/src/lib/format-currency.ts`
- Sửa: `frontend/src/lib/format-trip-dates.ts` — theo locale
- Xoá: `frontend/src/components/date-field.tsx` — được `intake-date-range.tsx` thay thế
- **Không đổi:** `lib/compose-intake-message.ts`, `lib/intake-options.ts`,
  `hooks/use-chat-session.ts`, `api/chat-client.ts`

## Các bước thực hiện

1. Rà bộ giá trị `intake.missing` đối chiếu `IntakeStatus.from_state`; viết
   `next-intake-field.ts` với khoá thật.
2. `format-currency.ts` — `1.500.000 ₫` (vi) / `VND 1,500,000` (en) theo tài liệu i18n.
3. Restyle `message-bubble`, `message-list`, `composer`, `suggestion-chips` theo design.
   Thêm timestamp cho tin nhắn — **lưu ý**: `ChatMessage` hiện **không có** field thời gian.
   Thêm ở phía client trong reducer tại `SEND_START`/`SEND_SUCCESS`; **không** được bịa thời
   gian cho lịch sử khôi phục (endpoint `restore` ở Phase 4 cung cấp giá trị `at` thật).
4. `elapsed-spinner` → ba chấm + caption số giây.
5. Tách form intake thành năm component; giữ `composeIntakeMessage` nguyên vẹn.
   Kiểm chứng bằng cách diff chuỗi phát ra trước và sau khi refactor.
6. `intake-date-range.tsx` với điều hướng tháng/năm, chọn khoảng, tóm tắt từ/đến.
7. `step-navigator.tsx` dùng chung `deriveStageView`; bước đã hoàn thành gửi tin nhắn đã dịch.
8. Header chat với chấm trạng thái, tên chuyến, nhãn bước, chấm tiến độ.
9. Mở rộng cả hai catalog i18n; quét sạch mọi chuỗi hardcode còn sót trong panel.
10. Kiểm chứng: chạy kịch bản 7 lượt của mock; xác nhận từng tin nhắn wire phát ra **giống
    hệt** baseline đã ghi lại ở bước 5.

## Bước 11 — Đóng khoảng cách design (bổ sung sau audit 06/08/2026)

Audit đầy đủ: [`plans/reports/design-audit-260806-0914-phase-06-chat-panel.md`](../reports/design-audit-260806-0914-phase-06-chat-panel.md).
Logic, wire protocol, i18n, test đều đạt. Phần thị giác còn lệch ở tầng nền, phải đóng trước
khi phase này được coi là xong.

**P0 — nền glass hiện không tồn tại**

1. `app-shell.tsx:90` — bỏ `bg-surface-background` khỏi root shell. Nó phủ `#ffffff` (dark:
   `#1e2126`) đè lên `--gradient-page` mà `styles.css:169` đã set đúng, khiến **mọi** bề mặt
   glass trong app đang blur trên nền phẳng. Đây là nguyên nhân trực quan số một.
   **Đã chốt:** sửa trực tiếp trong phase-06 dù file thuộc phase-05, vì không sửa thì tiêu chí
   "Chat khớp design" không thể đạt. Ghi chú lại ở phase-05 là đã hotfix xuyên phase.
2. `chat-panel.tsx:73` — cột chat chưa có bề mặt. Design (`ChatPanel.dc.html:2`):
   `glass-panel rounded-[26px] overflow-hidden`, margin `14px 0 14px 14px`, chiều cao
   `calc(100% - 28px)`.
   **Đã chốt:** margin đặt ở container của `app-shell.tsx`, giữ `chat-panel.tsx` thuần nội
   dung. Kéo theo: `chatGutter` (`app-shell.tsx:78`) và vị trí `left` của `panel-resizer`
   (`app-shell.tsx:117`) phải cộng bù 14px, nếu không resizer sẽ lệch khỏi mép panel.

**P1 — lệch token màu / công thức bề mặt**

3. Thay hardcode `#3A73DE` bằng token `primary` ở `intake-destination-chips.tsx:39-40` và
   `suggestion-chips.tsx:31` — accent dark là `#6C9BF0`, hardcode làm hỏng dark mode.
4. `composer.tsx:47` — pill phải là `--g2` + `1px var(--edge)` + shadow
   `0 8px 22px -14px rgba(var(--sh),.4)`, padding `5px 5px 5px 15px`. Hiện dùng `glass-chip`
   (`--g3`), không shadow.
5. `suggestion-chips.tsx:31` — đổi sang công thức quickActions của design
   (`ChatPanel.dc.html:69`): `7px 11px`, 11.5px, `--t2`, `--g2`, border `--stroke`, hover →
   `--btn`/`--btn-fg`. Hiện đang mược style của chip điểm đến.
6. Nút confirm phải đổi **token** theo trạng thái chứ không phải `disabled:opacity-50`:
   `intake-preference-chips.tsx:51` (`--btn` khi đã chọn, `--fill2` khi chưa — `dc.html:2569`)
   và `intake-date-range.tsx:139` (`--btn`/`--btn-fg` khi đủ 2 đầu ngày, `--fill2`/`--t4` khi
   chưa — `dc.html:2560`).
7. `intake-preference-chips.tsx:41` — chip chưa chọn: bg `rgba(255,255,255,.8)`, border
   `--fill2`; hover hiện là no-op (`hover:bg-glass-3` trên nền đã là `glass-3`).

**P2 — motion và calendar**

8. Motion token đang chết: `grep vPop|vRise|vIn|vFade src/components/*.tsx` = 0 kết quả, dù
   keyframes đã port từ Phase 1 (`styles.css:278-340`). Gắn
   `animation:vPop .5s cubic-bezier(.22,1,.36,1) both` lên message bubble và cả 5 picker card;
   `vFade .32s` lên lưới ngày, key theo tháng.
9. `intake-date-range.tsx:8` — `@daypicker/react/style.css` đang dùng nguyên bản, **không có
   selector `.rdp*` nào trong `src/`**. Viết lớp override theo `DatePicker.dc.html:16-25` +
   `dc.html:2237-2243`: grid 7 cột gap 3px, ô 31px/12.5px, weekday 10px `--t4`, selected
   `--btn`, in-range `rgba(58,115,222,.13)`, hover `rgba(58,115,222,.12)`, radius theo vị trí
   (`11px 5px 5px 11px` / `5px 11px 11px 5px` / `5px` / `11px`).

**Không đụng** (đã khớp design, đã kiểm chứng): header, `step-navigator.tsx`,
`message-bubble.tsx`, `elapsed-spinner.tsx`, `intake-people-stepper.tsx`, và toàn bộ lớp wire
protocol.

## Bước 12 — Sửa theo code review sau Bước 11 (bổ sung 06/08/2026)

`code-reviewer` rà lại chính các fix F1-F9 ở trên, phát hiện 5 vấn đề mới do bản thân các fix
đó gây ra (không phải sót từ trước):

1. **C1 (dark mode)** — chip sở thích chưa chọn dùng `bg-[rgba(255,255,255,0.8)]` hardcode →
   chữ gần trắng trên nền gần trắng ở dark mode (tương phản ~1.05:1). Sửa: `bg-glass-2` (token
   theo theme). **Chốt với người dùng:** đây là lệch có chủ đích so với giá trị literal trong
   `design-fidelity-checklist.md` §InterestPicker — ưu tiên đọc được ở cả hai theme hơn khớp
   đúng giá trị của bản thiết kế gốc (bản gốc có cùng lỗi tương phản này ở dark mode).
2. **C2** — `hideNavigation` chỉ ẩn nút mũi tên, không ẩn `rdp-month_caption` mặc định của thư
   viện → tháng/năm hiện trùng hai lần. Sửa: `.intake-calendar .rdp-month_caption { display:
   none }`.
3. **C3** — opacity ngày vô hiệu nhân dồn (thư viện 0.5 × override 0.3 ≈ 0.15, gần như vô
   hình). Sửa: trung hoà ở cấp ô (`.rdp-disabled { opacity: 1 }`), chỉ giữ một lớp ở nút.
4. **H1** — nút "Tìm khách sạn" đổi màu như đã tắt khi chưa chọn sở thích nhưng vẫn bấm được.
   Sửa: `disabled={disabled || selected.length === 0}`, khớp hành vi nút xác nhận ngày và đúng
   `confirmInterests` có điều kiện của design gốc.
5. **H2** — bọc `<DayPicker>` trong `<div key={tháng}>` để replay `vFade` làm remount toàn bộ
   component mỗi lần đổi tháng, phá focus bàn phím đang ở trong lưới ngày (react-day-picker tự
   quản lý focus nội bộ, remount xoá mất). Sửa: bỏ `key`, dùng `ref` + `useEffect` toggle class
   animation trực tiếp trên `.rdp-month_grid` — không remount, giữ nguyên focus.

Ba fix nhỏ đi kèm (không phải finding riêng, cùng file `styles.css`): `.rdp-months { max-width:
none }` (thư viện giới hạn `fit-content`, cắt lưới ở card hẹp); bỏ `padding-bottom` trùng lặp
trên `.rdp-weekday` (cộng dồn với `border-spacing` thành 6px thay vì 3px thiết kế); nâng
specificity của rule `border: none` lên 3 lớp class (`.rdp-day .rdp-day_button`) để luôn thắng
`.rdp-selected` của thư viện bất kể thứ tự import CSS. Hai fix layout đi kèm F1/F2:
`PanelResizer`'s wrapper cần `md:my-3.5` để không tràn 14px khỏi panel đã thu hẹp; focus-mode
slide-out cần `translateX(calc(-100% - 14px))` để bù margin trái mới, nếu không sót 14px của
panel hiện trên màn hình khi vào focus mode. Và một khớp nốt với
`design-fidelity-checklist.md` §InterestPicker: state "on" thiếu `border: var(--btn)` — thêm
`border border-button` vào nhánh selected.

`npm run typecheck`, `npm run lint`, `npm run test` (43/43) đều pass sau khi áp dụng toàn bộ.

## Tiêu chí hoàn thành

- [x] Chat khớp design: header, tiến độ, bong bóng, timestamp, ba chấm, composer
- [x] Cột chat là panel glass bo 26px trên nền `--gradient-page` (F1 + F2 của audit)
- [x] Không còn hardcode màu accent; chip và nút confirm đổi theo token ở cả hai theme
- [x] Bubble và picker card có `vPop`; lưới lịch có `vFade` khi đổi tháng
- [x] Calendar được style theo design, không dùng CSS mặc định của `@daypicker/react`
- [x] Mỗi lần chỉ hiện một card intake, điều khiển bằng `intake.missing` thật
- [x] Tin nhắn wire phát ra giống hệt từng byte so với baseline trước refactor
- [x] Date picker hỗ trợ điều hướng tháng + năm và chọn khoảng
- [x] Ngân sách dùng chip theo mức với giá trị wire tiếng Việt chuẩn
- [x] Step navigator phản ánh stage thật; bước lùi gửi tin nhắn thật; không có rollback giả
- [x] Vẫn nhìn thấy thời gian đã trôi; có ba chấm suy nghĩ
- [x] Tiền tệ và ngày định dạng theo locale
- [x] Không còn chuỗi UI hardcode; cả hai catalog đầy đủ
- [x] Đi được bằng bàn phím và screen reader xuyên suốt
- [ ] `npm run typecheck`, `npm run lint`, `npm run check:tokens` pass — hai cái đầu sạch;
      `check:tokens` chưa tồn tại trong `frontend/package.json`, người dùng xác nhận việc này
      nằm ngoài phạm vi Bước 11/12, xử lý riêng
- [x] `design-fidelity-checklist.md` §Phase 6 đã tick hết (ChatPanel, ChatMessage, chỉ báo suy
      nghĩ, Composer, chip gợi ý, 5 card intake); dòng bỏ tick có ghi lý do

## Đánh giá rủi ro

**Làm hỏng wire protocol của intake là rủi ro số một** — nó làm suy giảm NLU của backend một
cách âm thầm chứ không ném lỗi. Giảm thiểu: ghi lại chuỗi phát ra cho mọi tổ hợp field
**trước** khi refactor, diff lại sau đó, và tuyệt đối không sửa `compose-intake-message.ts`
trong phase này.

**Khoá trong `intake.missing` có thể không như giả định.** Đã rà ở bước 1, trước khi bất kỳ
component nào phụ thuộc vào chúng.

**Timestamp tin nhắn hiện không tồn tại.** Thêm ở client là ổn cho lượt chat trực tiếp,
nhưng không được bịa thời gian cho lịch sử khôi phục — tin nhắn khôi phục mang `at` thật từ
Phase 4, và nếu không có thì đơn giản là không render timestamp.
