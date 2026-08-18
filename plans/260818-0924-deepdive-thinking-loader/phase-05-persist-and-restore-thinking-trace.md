---
phase: 5
title: "Persist + restore thinking trace"
status: pending
priority: P2
effort: "1d"
dependencies: [4]
---

# Phase 5: Persist + restore thinking trace

## Overview

Làm cho khối thinking sống sót qua reload. Phase duy nhất chạm schema database, và là phase
duy nhất có thao tác cần người dùng chạy tay.

## Vấn đề quy trình phải xử lý trước

Repo **không có** `supabase/migrations/`. Chỉ có `supabase/seed.sql` và
`backend/scripts/database_schema.sql` — hai bản mô tả schema, không phải migration runner.
Và `session_store.py:378` ghi rõ migration gần nhất
(`20260811_add_session_checkpoint_persistence.sql`) **không được track trong repo**, kèm
ghi chú rằng test liên quan đã fail độc lập vì lý do đó.

Không có đường tự động để thêm cột. Phase này viết file SQL, cập nhật cả hai bản mô tả
schema, và **giao cho người dùng chạy tay**. Không giả vờ là đã chạy.

## Requirements

**Functional**
- Cột mới `chat_messages.thinking_trace jsonb NULL`.
- `final` payload chở `thinking_trace` → `session_store` ghi vào cột.
- `RestoredMessagePayload` thêm `thinking_trace`.
- `/session/restore` trả trace theo từng message.
- FE hiện header thu gọn cho message cũ có trace; click mở xem lại.

**Non-functional**
- Message cũ (`thinking_trace` NULL): **không** hiện header, không lỗi. Đây là đa số dữ liệu
  hiện có — đường NULL là đường chính, không phải ca biên.
- Lưu **dữ kiện**, không lưu câu chữ đã dựng. Câu chữ thuộc về FE (`thinking-lines.ts`) và
  phụ thuộc ngôn ngữ đang chọn — lưu câu tiếng Việt rồi restore trong phiên tiếng Anh sẽ
  hiện sai ngôn ngữ. Lưu `[{group, phase_key, facts}]` để FE dựng lại đúng ngôn ngữ hiện tại.
- Không lưu ID nội bộ / tool arg thô / chuỗi lỗi — whitelist của Phase 2 đã chặn ở nguồn,
  phase này không được nới ra.
- `session_store.persist` hiện `delete` rồi `insert` lại toàn bộ `chat_messages`
  (`session_store.py:371-375`). Ghi trace theo đúng đường đó, không thêm đường ghi thứ hai.

## Architecture

```sql
ALTER TABLE public.chat_messages
  ADD COLUMN IF NOT EXISTS thinking_trace jsonb;
```

Hình dạng trace — **dữ kiện, không phải câu chữ**:

```json
[{"group": "gather", "phase_key": "hotel_search",
  "facts": {"destination": "Đà Nẵng", "radius_km": 5, "found": 24, "kept": 8}}]
```

Đây là điểm khác quan trọng so với hướng reasoning cũ (khi đó phải lưu text vì text là thứ
model sinh ra). Ở đây text là hàm thuần của dữ kiện, nên lưu dữ kiện vừa nhỏ hơn, vừa
đúng ngôn ngữ khi restore, vừa cho phép đổi câu chữ sau này mà lịch sử tự cập nhật theo.

`group` dùng `ThinkingGroupKey` của FE. Ánh xạ phase key → group tồn tại cả ở BE (đường
persist) lẫn FE (đường live) — **trùng lặp có chủ ý**, hai đường vào khác nhau. Ghi chú
chéo trong cả hai file, và một test khẳng định hai bên cùng tập khoá.

## Related Code Files

- Create: `supabase/migrations/20260818_add_chat_message_thinking_trace.sql`
- Modify: `supabase/seed.sql` (định nghĩa `chat_messages`, ~394)
- Modify: `backend/scripts/database_schema.sql` (~195)
- Modify: `backend/src/services/session_store.py` (~371-375 ghi, ~405-415 đọc)
- Modify: `backend/src/models/schemas.py` (`RestoredMessagePayload`, ~488)
- Modify: `backend/src/api/routes.py` (`restore_session` ~303-335, `_restored_transcript`)
- Modify: `frontend/src/types/index.ts` (`ChatMessage.thinkingTrace?`)
- Modify: `frontend/src/components/message-list.tsx` (render trace lịch sử)
- Modify: `backend/tests/test_restore_endpoint.py`, `test_graph_session_persistence.py`

## Implementation Steps

1. Viết file migration SQL. Tạo luôn thư mục `supabase/migrations/` — đây là file đầu tiên,
   và việc repo chưa có thư mục này chính là nợ kỹ thuật phase này bù một phần.
2. Cập nhật `seed.sql` + `database_schema.sql` cho khớp.
3. **Báo người dùng chạy migration tay và chờ xác nhận.** Không code tiếp trên giả định cột
   đã tồn tại.
4. `session_store`: ghi `thinking_trace` trong đường `delete`+`insert` sẵn có; đọc thêm cột
   trong `load()`. Thiếu cột (môi trường chưa migrate) → ghi không có trace, **không** làm
   hỏng cả lượt persist. Dùng cùng kiểu phòng thủ như `PGRST202` ở `session_store.py:360-366`.
5. `RestoredMessagePayload` + `_restored_transcript` chở trace ra.
6. FE: `ChatMessage.thinkingTrace?`; dựng lại câu bằng `thinking-lines.ts` (Phase 3) rồi
   render `ThinkingBlock` ở chế độ chỉ-đọc (mọi nhóm `done`, không spinner).
7. Test: có trace → restore đúng; NULL → không lỗi, không header; `[]` → xử lý như NULL;
   trace lưu bằng tiếng Việt rồi restore ở phiên tiếng Anh → **hiện tiếng Anh**.
8. `pytest backend/tests/test_restore_endpoint.py test_graph_session_persistence.py` + `npm run test`.
9. Kiểm tay đầu-cuối: gửi lượt → reload → mở lại khối thinking, đối chiếu nội dung.

## Success Criteria

- [ ] Migration SQL tồn tại; `seed.sql` và `database_schema.sql` khớp
- [ ] Người dùng đã xác nhận chạy migration — ghi lại, không tự nhận
- [ ] Gửi lượt → reload → khối thinking mở lại được, nội dung khớp
- [ ] Message cũ (NULL): không header, không lỗi ở console lẫn log server
- [ ] Trace rỗng `[]` xử lý như NULL
- [ ] Môi trường chưa migrate: persist vẫn chạy, chỉ mất trace
- [ ] **Đổi ngôn ngữ rồi restore → câu chữ theo ngôn ngữ mới** (bằng chứng lưu dữ kiện, không lưu text)
- [ ] `ThinkingBlock` chế độ lịch sử không hiện spinner
- [ ] Không ID nội bộ / tool arg thô trong trace — kiểm một mẫu thật
- [ ] Test backend + FE xanh

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| **Không có quy trình migration trong repo** | Bước 3 dừng chờ người dùng; không code tiếp trên giả định |
| Môi trường chưa có cột → insert lỗi, mất cả transcript | Bước 4 dùng tiền lệ phòng thủ sẵn có ở `session_store.py:360-366` |
| Ánh xạ phase→group lệch giữa BE và FE | Ghi chú chéo hai chiều + test khẳng định cùng tập khoá |
| Trace phình to | Lưu dữ kiện (vài field/nhóm), không lưu văn bản — nhỏ theo thiết kế |
| Dữ liệu nhạy cảm lọt vào trace | Whitelist Phase 2 chặn ở nguồn; phase này không nới |
