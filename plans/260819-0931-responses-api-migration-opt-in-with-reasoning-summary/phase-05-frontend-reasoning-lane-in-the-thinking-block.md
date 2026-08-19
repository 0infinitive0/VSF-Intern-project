---
phase: 5
title: "Làn reasoning ở frontend"
status: pending
priority: P2
effort: "1d"
dependencies: [4]
---

# Phase 5: Làn reasoning ở frontend

## Overview

Nhận event `reasoning`, gom vào state, render trong khối thinking như một làn phụ dưới
các dòng dữ kiện. Dữ kiện graph vẫn là thứ lấp khối; reasoning chỉ chồng thêm khi có.

> **Bị chặn bởi `260818-0924-deepdive-thinking-loader` Phase 4.** Khối thinking UI
> (`ThinkingBlock`) chưa tồn tại — deepdive plan đang `pending`. Phase này không khởi
> động được cho tới khi component đó có mặt.

## Requirements

**Functional**
- `stream-client.ts` thêm handler `onReasoning?: (text: string) => void`, nhánh `case
  'reasoning'` trong `switch` sẵn có (`stream-client.ts:163-166`).
- `use-chat-session.ts` thêm action `STREAM_REASONING`, nối text vào state của **nhóm
  thinking đang chạy** — không phải một buffer toàn cục. Reasoning thuộc về bước nào
  thì hiện dưới bước đó.
- Reasoning xoá sạch ở mọi chỗ `phases`/`thinking` đang bị xoá
  (deepdive `phase-03` liệt kê `use-chat-session.ts:44,98,130,148,206,212`).
- Khối thinking hiển thị đầy đủ khi **không** có reasoning — đây là trường hợp thường,
  không phải biên.

**Non-functional**
- **Reasoning không thay thế dòng dữ kiện.** Deepdive `phase-03` đặt luật "thiếu dữ kiện
  thì không hiện dòng, không có câu chống chế". Reasoning không được dùng để lấp chỗ
  trống đó — làm vậy là quay lại đúng câu chống chế mà luật kia cấm, chỉ khác là bằng
  tiếng Anh.
- Đánh dấu thị giác phân biệt rõ chữ của model với chữ của sản phẩm: kiểu chữ khác, độ
  tương phản thấp hơn, và nhãn i18n nói rõ đây là suy luận của model. Nhãn là chữ của
  sản phẩm nên phải qua i18n; nội dung bên trong thì không.
- Không dịch, không i18n nội dung reasoning. Nó là tiếng Anh và ở nguyên tiếng Anh.
- Text dài phải cuộn trong khung riêng, không đẩy nội dung chat.
- `prefers-reduced-motion`: không animate text chạy.

## Architecture

```ts
// use-chat-session.ts — state
interface ThinkingGroup {
  key: ThinkingGroupKey
  labelKey: string
  lines: string[]        // dữ kiện graph, deepdive Phase 3 sở hữu
  reasoning: string      // chữ model, phase này sở hữu; '' là bình thường
  done: boolean
}
```

Hai field cạnh nhau, hai nguồn khác nhau, không cái nào fallback sang cái kia. Một nhóm
có thể có `lines` mà không có `reasoning` (thường gặp — bước gọi tool), hoặc cả hai, hoặc
chỉ `reasoning` (hiếm, và khi đó UI vẫn phải đọc được).

Render trong `ThinkingBlock`: `lines` trước, `reasoning` sau, thụt vào, có nhãn.

## Related Code Files

- Modify: `frontend/src/api/stream-client.ts` (handler + `case 'reasoning'`)
- Modify: `frontend/src/hooks/use-chat-session.ts` (action, reducer, reset paths)
- Modify: component `ThinkingBlock` (do deepdive Phase 4 tạo — đường dẫn chốt sau)
- Modify: file i18n (nhãn "suy luận của mô hình")
- Modify: `frontend/src/api/stream-client.test.ts`,
  `frontend/src/hooks/use-chat-session.test.ts`

## Implementation Steps

1. Xác nhận deepdive Phase 4 đã xong và `ThinkingBlock` tồn tại. Nếu chưa — dừng, báo.
2. `stream-client.ts`: thêm `onReasoning` vào interface handlers, thêm `case
   'reasoning'` gọi nó. Test: frame `reasoning` gọi đúng handler; frame lạ vẫn bị bỏ qua.
3. `use-chat-session.ts`: action + reducer nối vào nhóm đang chạy. Test: reasoning tới
   trước khi có nhóm nào active → bỏ qua, không crash.
4. Thêm reasoning vào mọi đường reset. Test: gửi lượt mới xoá sạch reasoning cũ.
5. Render trong `ThinkingBlock` với nhãn i18n + kiểu thị giác phân biệt.
6. Test render: nhóm không có reasoning vẫn hiện đủ dòng dữ kiện.
7. Kiểm tra thủ công một lượt thật với cờ bật, xem cả trường hợp có và không có summary.

## Success Criteria

- [ ] Frame `reasoning` tới đúng nhóm thinking đang chạy
- [ ] Khối thinking đầy đủ khi reasoning rỗng, có test
- [ ] Reasoning không bao giờ được dùng để lấp dòng dữ kiện thiếu
- [ ] Nhãn qua i18n, nội dung không
- [ ] Reset xoá sạch, có test
- [ ] Text dài cuộn trong khung riêng
- [ ] Không animate khi `prefers-reduced-motion`

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Deepdive Phase 4 chưa xong → phase này treo | **Cao** | Ghi `blockedBy` ở plan level. Bước 1 là cổng chặn tường minh |
| Reasoning tiếng Anh giữa UI tiếng Việt gây khó chịu | Trung bình | Nhãn i18n nói rõ nguồn; kiểu thị giác tách bạch. Không dịch — spike §Q2 đã loại phương án đó |
| Summary lúc có lúc không làm UI nhấp nháy | Trung bình | Làn reasoning chỉ mount khi có nội dung; không dựng khung rỗng chờ sẵn |
| Xung đột merge với deepdive Phase 3/4 trên cùng file | Cao | Cùng file, khác field. Ship sau deepdive, không song song. Phase 6 hoà giải plan trước |
