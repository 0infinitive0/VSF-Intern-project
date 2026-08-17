---
phase: 6
title: "Intake server-snapshot source of truth"
status: complete
priority: P1
effort: "1d"
dependencies: []
---

# Phase 6: Intake server-snapshot source of truth

## Overview

Chốt **server snapshot thắng local form** cho intake widget, và sửa bubble câu hỏi trùng
mà quyết định cũ (local-first) sinh ra. Đây là phase trả lời trực tiếp bug "chatbot gửi 2
tin nhắn".

## Bằng chứng lỗi

Bubble thứ hai **không phải backend gửi**. `message-list.tsx:104-108` render một bubble
tổng hợp không nằm trong `state.messages`:

```tsx
{intakeQuestion && (
  <MessageBubble
    message={{ id: '__intake_question__', role: 'ai', text: intakeQuestion, stage: 'intake' }}
  />
)}
```

Không có field `at` → không timestamp. Khớp ảnh chụp: bubble 1 có "21:21", bubble 2 không có.

### Truy vết với "tôi muốn đổi ngày đi"

1. Backend xóa slot `dates.start`/`dates.end`, `ask_slot` sinh câu hỏi ngày mới →
   `intake.missing = ['start_date', 'duration']` (`respond.py:306-315`). → **Bubble 1**.
2. `nextIntakeField(intake)` = `'dates'`.
3. `currentIntakeField(intake, form)` (`next-intake-field.ts:151-170`):
   - Field `'dates'`: `isFieldMissing` = **true**, nhưng `isFieldFilled(form,'dates')` cũng
     = **true** vì form local **vẫn giữ ngày cũ** — `use-intake-form.ts:69-70` merge kiểu
     `intake.start_date || prev.startDate`, **không bao giờ xóa**.
   - → nhánh `continue` (dòng 159) → **bỏ qua field mà backend vừa hỏi**.
   - → rơi xuống terminal `return 'preferences'` (dòng 169).
4. `locallyAdvancedField(intake, 'preferences')` → `'preferences' !== 'dates'` → gate mở →
   render `intakePreferencesQuestion`. → **Bubble 2**.

Cùng biến `activeIntakeField` điều khiển cả câu hỏi lẫn widget → rail hiện chips sở thích
thay vì date-picker, dù backend vừa hỏi ngày.

### Lỗi cấu trúc, không riêng câu này

Kể cả khi ngày *không* bị xóa, hai hàm không bao giờ khớp ở cuối luồng intake:

| | khi mọi field gated đã trả lời |
|---|---|
| `nextIntakeField` | `null` (dòng 73, `?? null`) |
| `currentIntakeField` | `'preferences'` (dòng 169, **không bao giờ trả null** khi `intake` tồn tại) |

`'preferences' === null` luôn false → bubble "Cuối cùng - bạn thích kiểu trải nghiệm nào?"
bám dai dẳng ở **mọi** turn có `lastStage === 'intake'` sau khi intake xong.

## Requirements

**Functional**
- Backend mở lại một field (slot về rỗng) → widget quay lại field đó, form local xóa giá
  trị cũ của **đúng field đó**.
- Không bao giờ hiện hai câu hỏi trong một turn.
- Terminal state (mọi field đã trả lời, đang chờ user bấm "Tìm khách sạn phù hợp") không
  render câu hỏi lặp lại mỗi turn.
- Giá trị user đang gõ dở **không** bị snapshot ghi đè giữa chừng.

**Non-functional**
- Không xóa message thật khỏi thread. `next-intake-field.ts:120-125` đã ghi lại một lần
  thử sai trước đây (`hideDuplicateIntakeReply`) làm câu hỏi thật biến mất — không lặp lại.
- Logic thuần, unit-test được, không cần render React (theo pattern hiện có).

## Architecture

### Quyết định: server snapshot thắng, có ngoại lệ cho edit đang dở

Ba thay đổi, mỗi cái đóng một lỗ khác nhau:

**(1) `use-intake-form.ts` — phân biệt "backend không có giá trị" với "backend không gửi"**

```ts
// TRƯỚC — không phân biệt được null với undefined
startDate: intake.start_date || prev.startDate,

// SAU — backend nói rõ null nghĩa là slot rỗng → xóa local
startDate: intake.start_date ?? (editingField === 'dates' ? prev.startDate : ''),
```

Ngoại lệ `editingField`: user đang bấm "Sửa" trên field đó thì giữ giá trị đang gõ, nếu
không mỗi snapshot sẽ xoá chữ dưới tay họ.

**(2) `currentIntakeField` — field backend đang thiếu luôn thắng**

```ts
// TRƯỚC (dòng 156-161)
for (const field of INTAKE_FIELD_ORDER) {
  if (isFieldMissing(intake, field)) {
    if (!isFieldFilled(form, field)) return field
    continue                                    // ← bỏ qua field backend vừa mở lại
  }
}

// SAU
for (const field of INTAKE_FIELD_ORDER) {
  if (isFieldMissing(intake, field)) return field    // server thắng, không xét form
}
```

Sau thay đổi (1), form không còn giữ giá trị cũ của field đã bị xóa, nên `continue` mất
lý do tồn tại. Bỏ nó làm progressive disclosure vẫn chạy (field chưa tới lượt thì không
`missing`).

**(3) `currentIntakeField` — trả `null` ở terminal state**

```ts
// SAU — thêm tham số phân biệt "đang thu thập" với "đã xong, chờ submit"
if (isFieldFilled(form, 'preferences')) return null   // đã chọn ít nhất một chip
return 'preferences'
```

`locallyAdvancedField(intake, null)` trả `null` (dòng 131) → không render câu hỏi.

Widget **vẫn hiển thị** — `showIntakeForm` (`chat-panel.tsx:118`) độc lập với
`activeIntakeField`. Chỉ câu hỏi lặp biến mất. Đây là điểm phải cẩn thận: card
preferences không được biến mất khi user chọn chip đầu tiên (`next-intake-field.ts:145-149`
ghi rõ nút "Tìm khách sạn" là đường duy nhất chạy `submitAll`).

### Bảng trạng thái sau khi sửa

| Tình huống | `nextIntakeField` | `currentIntakeField` | Câu hỏi FE |
|---|---|---|---|
| Backend hỏi destination | `destination` | `destination` | không (khớp) |
| User điền people local, backend chưa biết | `people` | `dates` | có — đúng, backend chưa hỏi dates |
| Backend mở lại dates | `dates` | `dates` | **không** (khớp — đã sửa) |
| Xong hết, chưa chọn chip | `null` | `preferences` | có — một lần |
| Xong hết, đã chọn chip | `null` | `null` | **không** (đã sửa) |

## Related Code Files

- Modify: `frontend/src/lib/next-intake-field.ts` — `currentIntakeField` bỏ `continue`, thêm terminal `null`
- Modify: `frontend/src/hooks/use-intake-form.ts` — merge dùng `??` + ngoại lệ `editingField`
- Modify: `frontend/src/components/chat-panel.tsx` — truyền `editingIntakeField` vào nếu chữ ký đổi
- Modify: `frontend/src/lib/next-intake-field.test.ts` — thêm case bảng trạng thái ở trên
- Modify: `frontend/src/lib/compose-intake-message.test.ts` — verify form rỗng ngày không sinh câu vô nghĩa
- Check: `frontend/src/lib/intake-checklist-rows.ts` — checklist đọc cùng nguồn, xác nhận không lệch

## Implementation Steps

1. **Test đỏ trước.** Trong `next-intake-field.test.ts`, thêm 5 case của bảng trạng thái.
   Case "backend mở lại dates" và "xong hết, đã chọn chip" phải fail hiện tại.
2. Sửa `use-intake-form.ts` merge logic ((1) ở trên). Chạy test —
   `compose-intake-message` có thể vỡ nếu form ngày rỗng: `composeIntakeMessage` bỏ qua
   câu trip-fact khi `durationDays <= 0` (`compose-intake-message.ts`), nên xác nhận nó
   degrade sạch chứ không sinh câu cụt.
3. Sửa `currentIntakeField` ((2) và (3)).
4. Chạy `npm test && npm run typecheck`.
5. Kiểm thủ công đúng kịch bản ảnh chụp: chốt xong một chuyến → gõ "tôi muốn đổi ngày đi"
   → phải thấy **một** bubble và **date-picker**, không phải chips sở thích.
6. Kiểm hồi quy: điền toàn bộ intake qua widget từ đầu → mỗi bước một câu hỏi, không sót
   không lặp.

## Success Criteria

- [x] 5 test bảng trạng thái pass; 2 trong số đó fail trước khi sửa
- [~] "tôi muốn đổi ngày đi" → một bubble, **widget date-picker chưa đạt** — xem Sai lệch (B)
- [x] Chọn chip sở thích → card **không** biến mất, câu hỏi lặp **biến mất**
- [x] Luồng intake từ đầu vẫn hỏi đủ 5 bước, không lặp — test progressive disclosure giữ nguyên, pass
- [x] Đang gõ dở trong ô "Sửa" → snapshot mới không xoá chữ
- [x] `npm test` (218 pass) + `npm run typecheck` xanh

## Sai lệch so với bản plan (2026-08-16)

Ba thay đổi mà plan đề xuất: (1) giữ, (2) **bỏ**, (3) **đổi hình dạng**. Lý do có bằng chứng.

### (2) — KHÔNG bỏ `continue` trong `currentIntakeField`

Lập luận của plan: *"Sau thay đổi (1), form không còn giữ giá trị cũ của field đã bị xóa,
nên `continue` mất lý do tồn tại. Bỏ nó làm progressive disclosure vẫn chạy (field chưa
tới lượt thì không `missing`)."*

**Tiền đề "field chưa tới lượt thì không missing" là sai.**
`_intake_status_from_travel_state` (`respond.py:305-315`) phát **toàn bộ** key chưa có
giá trị trong một lần:

```python
missing = [name for name, value in (("destination", ...), ("people", ...),
           ("start_date", ...), ("duration", ...)) if value is None]
```

Không có phát dần theo lượt. Nên ngay từ turn đầu `missing` đã là cả bốn key. Nếu
`isFieldMissing(field)` → `return field` vô điều kiện, widget sẽ **đứng yên ở
`destination`** cho tới khi có một chat turn — mà progressive disclosure cố ý *không*
tạo chat turn nào giữa các bước (docstring `locallyAdvancedField` ghi rõ điều này).
Bỏ `continue` giết luồng widget.

`continue` được giữ nguyên + thêm comment giải thích vì sao nó load-bearing.

### (3) — Chặn câu hỏi ở `locallyAdvancedField`, không phải `currentIntakeField`

Plan đề xuất `currentIntakeField` trả `null` ở terminal state, với lý do
*"Widget vẫn hiển thị — `showIntakeForm` (`chat-panel.tsx:118`) độc lập với
`activeIntakeField`"*.

**Sai.** `showIntakeForm` chỉ quyết định có render `IntakeParametersForm` hay không.
Bên trong component đó, `intake-parameters-form.tsx:60` gọi lại chính
`currentIntakeField`, và `switch (activeField)` rơi vào `default: return null`
(dòng 146-147) khi activeField là `null` → **card biến mất**, mất luôn nút "Tìm khách
sạn phù hợp" — đường duy nhất chạy `submitAll`.

Test hiện có `"keeps preferences active once toggled — it is terminal, not a gate"`
mã hóa đúng quyết định này từ trước. Sửa theo plan sẽ phải xóa test đó.

Hai consumer cần hai câu trả lời khác nhau: widget cần `'preferences'`, câu hỏi cần
`null`. Nên chặn ở nơi chỉ phục vụ câu hỏi:

```ts
locallyAdvancedField(intake, activeField, form)   // + tham số form
  → if (isFieldFilled(form, activeField)) return null
```

### (1) — Giữ, nhưng so sánh **transition**, không so sánh một snapshot

`intake.start_date ?? (editingField === 'dates' ? prev.startDate : '')` như plan viết sẽ
xóa mọi giá trị local mà server chưa biết — tức phá luôn progressive disclosure (user gõ
destination trong widget, một chat turn bất kỳ xảy ra, giá trị bay mất).

`null` trong một snapshot **không** phân biệt được "server chưa từng biết" với "server
vừa xóa". Chỉ có chuyển tiếp `non-null → null` mới nói lên điều đó. `mergeIntakeIntoForm`
giữ `previousIntake` làm mốc so sánh; `useIntakeForm` giữ mốc trong `useRef`.

Hệ quả tốt: sau khi (1) làm đúng, nhánh `if (!isFieldFilled(form, field)) return field`
sẵn có đã tự xử lý ca "backend mở lại dates" — không cần (2) nữa.

### (B) Backend **không** xóa slot khi user nói "đổi ngày" — việc còn lại, ngoài phạm vi phase

Rủi ro mà plan đã đánh dấu *"Giả định cần verify"* đã được verify: **giả định sai**.

| Bằng chứng | Kết luận |
|---|---|
| `_EXTRACT_PATCH_SYSTEM_PROMPT` (`prompts.py:50-95`) khai `operation: "set \| unset \| append \| remove"` trong schema nhưng **không có một dòng hướng dẫn nào** về khi nào emit `unset` | LLM không được dạy xóa slot |
| Prompt chỉ nói *"Emit a change only for a fact the user STATES about their own trip"* — "tôi muốn đổi ngày đi" **không nêu** ngày nào | Nhiều khả năng trả `changes: []` |
| Không có deterministic rewrite nào cho intent "đổi/xóa" (chỉ có `_rewrite_day_scope`, `_ground_changes`) | Không có lưới đỡ |
| `grep -rn "unset" tests/` → chỉ `test_travel_state.py:86` (tầng domain) | Không có test nào phủ extract_patch sinh `unset` |

Vậy đường đi thật của bug ảnh chụp **không phải** nhánh (1)/(2) mà plan mô tả, mà là (3):
mọi slot vẫn còn giá trị → `missing = []` → `nextIntakeField = null` → `currentIntakeField`
rơi xuống terminal `'preferences'` → `'preferences' !== null` → render bubble chips sở
thích. Khớp chính xác triệu chứng: bubble 1 có timestamp (backend), bubble 2 không có (FE),
và widget hiện chips thay vì date-picker.

**(3) đã sửa bubble trùng.** Nhưng **date-picker không thể đạt được từ FE**: FE không có
tín hiệu nào để biết user muốn đổi ngày — backend phải emit `unset` trên `dates.start`/
`dates.end` trước. Đó là việc của `extract_patch`, cần thay đổi prompt + eval, nên thuộc
một phase riêng (xem Open Questions ở `plan.md`).

`mergeIntakeIntoForm` vẫn được implement đầy đủ: nó đúng ngay khi backend bắt đầu emit
`unset` từ bất kỳ đường nào, và `unset` đã hoạt động ở tầng domain
(`apply_patch`, `travel_state.py:222`).

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Xóa local value làm `composeIntakeMessage` gửi câu thiếu field | Cao | Bước 2 verify degrade sạch. Đây là đánh đổi có ý thức: gửi câu thiếu field mà backend sẽ hỏi lại **đúng hơn** gửi ngày cũ mà user vừa nói muốn đổi |
| Snapshot ghi đè chữ user đang gõ | Cao | Ngoại lệ `editingField` ở (1). Test case riêng cho tình huống này |
| Card preferences biến mất khi chọn chip đầu tiên | Trung bình | `showIntakeForm` độc lập với `activeIntakeField`; test khẳng định card còn khi `currentIntakeField` trả `null` |
| `intake-checklist-rows.ts` đọc form theo giả định cũ | Trung bình | Đọc file trước khi sửa; nó UNION server + local nên xóa local có thể làm ô checklist tắt đèn. Nếu vậy, checklist phải đọc **server-only** cho field backend đang hỏi |
| Backend không thật sự xóa slot khi user nói "đổi ngày" | Trung bình | Giả định cần verify: chạy turn thật, in `intake.missing`. Nếu backend **không** xóa slot thì bug thuộc `extract_patch`, không phải FE — ghi vào Open Questions và mở phase riêng |
