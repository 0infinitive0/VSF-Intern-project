---
phase: 6
title: "[FE] Chat panel cố định"
status: pending
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

## Tiêu chí hoàn thành

- [ ] Chat khớp design: header, tiến độ, bong bóng, timestamp, ba chấm, composer
- [ ] Mỗi lần chỉ hiện một card intake, điều khiển bằng `intake.missing` thật
- [ ] Tin nhắn wire phát ra giống hệt từng byte so với baseline trước refactor
- [ ] Date picker hỗ trợ điều hướng tháng + năm và chọn khoảng
- [ ] Ngân sách dùng chip theo mức với giá trị wire tiếng Việt chuẩn
- [ ] Step navigator phản ánh stage thật; bước lùi gửi tin nhắn thật; không có rollback giả
- [ ] Vẫn nhìn thấy thời gian đã trôi; có ba chấm suy nghĩ
- [ ] Tiền tệ và ngày định dạng theo locale
- [ ] Không còn chuỗi UI hardcode; cả hai catalog đầy đủ
- [ ] Đi được bằng bàn phím và screen reader xuyên suốt
- [ ] `npm run typecheck` và `npm run lint` pass

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
