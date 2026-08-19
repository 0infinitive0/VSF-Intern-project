---
phase: 4
title: "ThinkingBlock UI trong chat"
status: pending
priority: P1
effort: "1.5d"
dependencies: [3]
---

# Phase 4: ThinkingBlock UI trong chat

## Overview

Component thay `ElapsedSpinner` ở `message-list.tsx:95`. Đây là phần người dùng thật sự
nhìn thấy — mọi phase trước tồn tại để phục vụ nó.

## Requirements

**Functional**
- Đang chạy: header + chevron (mở sẵn), nhóm xong hiện ✓, nhóm hiện tại hiện spinner + các
  dòng dữ kiện bên dưới.
- Xong: tự thu gọn còn 1 dòng header; click mở lại được. Lựa chọn thủ công của người dùng
  thắng hành vi tự động.
- Trước khi phase đầu tiên về: fallback `ElapsedSpinner` (giữ nguyên component, không xoá).
- Nhóm không có dòng nào: chỉ tiêu đề + ✓/spinner, **không** vùng text rỗng lửng lơ.
- **Làn reasoning** (thêm 2026-08-19, plan `260819-0931` Phase 5): dưới các dòng dữ kiện,
  thụt vào, độ tương phản thấp hơn, có nhãn i18n nói rõ đây là suy luận của mô hình. Chỉ
  mount khi có nội dung — không dựng khung rỗng chờ sẵn, vì rỗng là trường hợp thường.
  Nội dung là tiếng Anh và giữ nguyên tiếng Anh. Nó **không** thay thế dòng dữ kiện thiếu.
- `streamingText` về (câu trả lời bắt đầu chạy): khối thinking thu gọn, `MessageBubble`
  streaming hiện như hiện tại. Hai thứ không đè nhau.
- **Vùng cuộn riêng**: nội dung giới hạn chiều cao, tự cuộn trong khối, không đẩy dài
  khung chat.
- **Bám đáy**: dòng mới về thì tự cuộn xuống để luôn thấy dòng mới nhất.
- **Dừng bám khi người dùng đọc**: người dùng cuộn ngược lên → ngừng tự cuộn; cuộn về đáy
  → bám đáy trở lại.
- **Gradient mờ ở đáy** khi còn nội dung bên dưới, để lộ ra rằng vùng này cuộn được.

**Non-functional**
- Dòng mới xuất hiện có chuyển động nhẹ, tôn trọng `prefers-reduced-motion`.
- `aria-live="polite"` cho danh sách bước. Các dòng dữ kiện là text ngắn, thêm dần — đặt
  `aria-live` ở vùng bao là đủ, **không** đặt riêng từng dòng (screen reader sẽ đọc chồng).
- Nút thu gọn/mở là `<button>` thật, có `aria-expanded`, bàn phím dùng được.
- Dùng token sẵn có (`bg-glass-3`, `border-line`, `text-on-surface`, `text-primary`,
  `text-success`) như `elapsed-spinner.tsx` / `turn-phases.tsx`. Không màu cứng mới.
- Khối cao lên khi thêm dòng **không** được đẩy khung chat giật — kiểm với lượt nhiều nhóm.

## Architecture

Tái dùng ngôn ngữ thị giác của `turn-phases.tsx` (✓ và spinner đã đúng phong cách hệ thống)
nhưng **không** import nó: `TurnPhases` nhận `TurnPhase[]` thô và sống ở panel phải; đây
nhận `ThinkingGroup[]` đã gom nhóm, có thêm dòng dữ kiện và trạng thái thu gọn. Khác dữ liệu
vào, khác trạng thái, khác nơi sống. Gộp bằng props điều kiện sẽ tạo một component hai mặt —
tệ hơn là chép 20 dòng markup.

`message-list.tsx` sau khi sửa:

```tsx
{pending && streamingText && (/* … MessageBubble streaming, giữ nguyên … */)}

{pending && !streamingText && (
  <div className="flex justify-start">
    {thinking.length > 0 ? <ThinkingBlock groups={thinking} /> : <ElapsedSpinner />}
  </div>
)}
```

### Vùng cuộn có bám đáy

**Không có tiền lệ trong repo để tái dùng.** `message-list.tsx:53-67` chỉ *throttle* rồi
`scrollIntoView` **vô điều kiện** — nó không phát hiện người dùng đang cuộn lên, và hôm nay
sẽ giật người dùng về đáy giữa lúc họ đọc. Phần bám đáy dưới đây phải dựng mới, không copy
từ đó.

Điểm may: effect cuộn của `message-list` có deps `[messages, pending, streamingText,
intakeQuestion]` — **`thinking` không nằm trong đó**, nên dòng mới trong khối không kích
hoạt cuộn ngoài. Hai vùng cuộn độc lập. *Nếu sau này ai thêm `thinking` vào deps đó, hai
bên sẽ giành nhau* — ghi chú cảnh báo ngay tại effect ấy.

```tsx
const scrollRef = useRef<HTMLDivElement>(null)
const stick = useRef(true)          // bám đáy cho tới khi người dùng cuộn đi
const BOTTOM_EPS = 24               // px — coi là "đang ở đáy"

const onScroll = () => {
  const el = scrollRef.current
  if (!el) return
  stick.current = el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_EPS
}

useEffect(() => {
  const el = scrollRef.current
  if (!el || !stick.current) return
  el.scrollTo({ top: el.scrollHeight, behavior: reducedMotion ? 'auto' : 'smooth' })
}, [groups])
```

`stick` là `useRef` chứ không phải `useState` — nó được đọc/ghi trong handler cuộn chạy ở
tần suất cao và **không** được kéo theo re-render; biến nó thành state sẽ render lại mỗi
lần cuộn.

**Gradient mờ**: overlay tuyệt đối ở đáy vùng cuộn,
`linear-gradient(transparent, <token nền của khối>)`. Phải dùng **token**, không phải màu
cứng — gradient đổ về trắng sẽ thành một vệt sáng giữa nền tối ở dark theme. Đây là lỗi
kinh điển của kỹ thuật này. Ẩn overlay khi đã cuộn tới đáy (dùng chính `stick`), để không
làm mờ dòng cuối khi không còn gì bên dưới.

**Khi mở lại khối đã xong**: cuộn về **đầu** và đặt `stick = false`. Đây là bản ghi đã hoàn
tất, người dùng mở ra để đọc từ đầu, không có gì mới sắp tới để mà bám đáy.

Ảnh mẫu còn có nút tròn ↓ ở giữa vùng mờ. **Không nằm trong phạm vi phase này** — gradient
đã đủ báo hiệu cuộn được; thêm nút là quyết định riêng, làm sau nếu muốn.

## Related Code Files

- Create: `frontend/src/components/thinking-block.tsx` + `.test.tsx`
- Modify: `frontend/src/components/message-list.tsx` (~95)
- Read only: `frontend/src/components/turn-phases.tsx`, `elapsed-spinner.tsx`

## Implementation Steps

1. Dựng `thinking-block.tsx`: header + danh sách nhóm + dòng dữ kiện, dùng token có sẵn.
2. Thêm trạng thái thu gọn: mở khi `pending`, tự đóng khi mọi nhóm `done`, người dùng bấm
   được cả hai chiều và lựa chọn đó thắng.
3. Thêm vùng cuộn: `max-height` + `overflow-y: auto`, ref + `onScroll` + effect bám đáy
   theo mẫu ở Architecture. Chốt `max-height` bằng cách đo một lượt nhiều nhóm thật, đừng
   đoán một con số.
4. Thêm overlay gradient dùng token nền của khối; ẩn khi `stick` đang true.
5. Xử lý mở lại sau khi xong: cuộn về đầu, `stick = false`.
6. Thêm ghi chú cảnh báo tại effect cuộn của `message-list.tsx:55`: không thêm `thinking`
   vào deps, kèm lý do.
7. Nối vào `message-list.tsx`, giữ `ElapsedSpinner` làm fallback.
8. Test: nhóm done → ✓; nhóm cuối → spinner; nhóm không dòng → không vùng text;
   `thinking` rỗng → `ElapsedSpinner`; `aria-expanded` đổi đúng; bàn phím mở/đóng được;
   người dùng đóng tay rồi nhóm mới về → vẫn đóng.
9. Test cuộn: ở đáy + dòng mới → cuộn theo; cuộn lên giữa chừng + dòng mới → **không** giật
   xuống; cuộn về đáy → bám lại; mở lại khối đã xong → ở đầu, không tự cuộn.
10. `npm run test` + `npm run typecheck`.
11. Kiểm theme sáng/tối bằng cách đọc token đã dùng (`use-theme.ts`), **đặc biệt là gradient**
    — không cần mở trình duyệt.

## Success Criteria

- [ ] `pending` + có nhóm → ThinkingBlock; `pending` + chưa có nhóm → `ElapsedSpinner`
- [ ] Nhóm xong ✓, nhóm hiện tại spinner
- [ ] Nhóm không có dòng nào → không render vùng text rỗng
- [ ] Xong thì tự thu gọn; click mở lại thấy nội dung
- [ ] Người dùng đóng tay → nhóm mới về không tự mở lại
- [ ] `aria-live` đặt ở vùng bao, không đặt từng dòng
- [ ] Nút có `aria-expanded`, bàn phím dùng được
- [ ] `prefers-reduced-motion` được tôn trọng, gồm cả hành vi cuộn (`auto` thay `smooth`)
- [ ] Đúng token màu ở cả hai theme, không màu cứng mới
- [ ] Khung chat không giật khi khối cao lên — khối tự cuộn trong `max-height`, không đẩy dài
- [ ] Đang ở đáy + dòng mới về → cuộn theo
- [ ] **Cuộn lên đọc + dòng mới về → không bị giật xuống**
- [ ] Cuộn về đáy → bám đáy trở lại
- [ ] Mở lại khối đã xong → ở đầu, không tự cuộn
- [ ] Gradient dùng token, không tạo vệt sáng ở dark theme; ẩn khi đã ở đáy
- [ ] `stick` là `useRef`, không gây re-render mỗi lần cuộn
- [ ] `message-list.tsx` có ghi chú cảnh báo về deps của effect cuộn
- [ ] `npm run test` + `typecheck` sạch

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| ThinkingBlock và MessageBubble streaming đè nhau | Hai nhánh loại trừ theo `streamingText`, giống cấu trúc hiện tại |
| Khối cao lên làm giật khung chat | `max-height` + cuộn trong khối; ghi thành tiêu chí nghiệm thu |
| **Cuộn ngoài của `message-list` giành với cuộn trong** | Hôm nay không giành vì `thinking` không nằm trong deps của effect ấy — nhưng đó là sự may mắn, không phải thiết kế. Bước 6 ghi chú cảnh báo tại chỗ để lần sửa sau không phá |
| Gradient đổ về màu cứng → vệt sáng ở dark theme | Dùng token; tiêu chí nghiệm thu kiểm riêng cả hai theme |
| `stick` làm state → re-render mỗi lần cuộn | Dùng `useRef`; ghi rõ lý do trong Architecture và tiêu chí nghiệm thu |
| Bám đáy tranh với việc người dùng đang đọc | Ngưỡng `BOTTOM_EPS`; ca test "cuộn lên + dòng mới về" |
| Screen reader đọc chồng khi thêm dòng | `aria-live` ở vùng bao, không ở từng dòng |
| Gộp nhầm với `TurnPhases` để "DRY" | Lý do không gộp đã ghi trong Architecture |
| Tự đóng đè lên ý muốn người dùng | Ca test "đóng tay rồi nhóm mới về" |
