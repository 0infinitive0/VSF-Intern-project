---
phase: 1
title: "Vá guard streaming"
status: completed
priority: P1
effort: "3h"
dependencies: []
---

# Phase 1: Vá guard streaming

## Overview

`routes.py:711` chỉ phát delta khi `content` là `str`. Khi `content` thành list block,
guard trả `False`, `emit_delta` không bao giờ được gọi, và người dùng nhìn màn hình
trắng — không exception, không log, không test nào fail. Phase này đóng lỗ đó, độc lập
với mọi quyết định về Responses API.

## Requirements

**Functional**
- Vòng drain `messages` phát được text từ cả hai hình dạng: `content: str` (Chat
  Completions) và `content: list[block]` (Responses API).
- Block không phải text (`reasoning`, `tool_call`, …) bị bỏ qua ở phase này — Phase 4
  mới xử lý `reasoning`.
- Chunk rỗng vẫn no-op như hôm nay (`emit_delta` đã guard `if not text`).

**Non-functional**
- Không đổi hợp đồng SSE. `docs/chat_api_contract.md` §Streaming giữ nguyên ở phase này.
- Không đổi hành vi khi chạy Chat Completions — đây là điều kiện để ship riêng.
- Đọc `.content_blocks` chứ không parse `.content` thô. Spike §Q4 đo được LangChain
  chuẩn hoá sẵn `{"type": "reasoning", "reasoning": "..."}`, và tự parse hình dạng
  OpenAI thô là gánh việc của thư viện.

## Architecture

Hôm nay (`routes.py:708-712`):

```python
if metadata.get("langgraph_node") in STREAMING_NODES:
    content = getattr(message_chunk, "content", "")
    if isinstance(content, str):
        emit_delta(content)
```

Sau khi vá — một helper thuần, đặt cạnh vòng drain:

```python
def _text_from(message_chunk) -> str:
    """Text người dùng đọc được trong một chunk, bất kể chunk đến từ API nào.

    Chat Completions đưa `content` là `str`. Responses API đưa list block, và
    LangChain chuẩn hoá nó qua `.content_blocks` — dùng cái đã chuẩn hoá thay vì
    parse hình dạng thô của nhà cung cấp.
    """
    content = getattr(message_chunk, "content", "")
    if isinstance(content, str):
        return content
    blocks = getattr(message_chunk, "content_blocks", None) or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
```

Vòng drain gọi `emit_delta(_text_from(message_chunk))`.

Vì sao không đọc `.content_blocks` cho cả hai đường: với Chat Completions,
`.content_blocks` cũng trả về `[{"type": "text", ...}]`, nhưng đi qua một lớp chuẩn
hoá cho mỗi chunk trong khi `str` đã có sẵn. Giữ nhánh `str` là đường nhanh, không
phải trùng lặp.

## Related Code Files

- Modify: `backend/src/api/routes.py` (vòng drain `messages`, ~708-712)
- Create: test trong `backend/tests/` (đặt cùng chỗ với test streaming hiện có — tìm
  file đang cover `_run_turn_via_graph` / vòng drain trước khi tạo file mới)

## Implementation Steps

1. Tìm test file đang cover vòng drain streaming. Nếu có, thêm vào đó; chỉ tạo file mới
   khi thật sự chưa có chỗ nào.
2. Viết test **trước**: một `AIMessageChunk` giả với `content` là list block
   `[{"type": "text", "text": "xin chào"}]` và `content_blocks` tương ứng → khẳng định
   `emit_delta` nhận `"xin chào"`. Test này phải **fail** trên code hiện tại.
3. Thêm test đối chứng: `content` là `str` → hành vi không đổi.
4. Thêm test cho block không phải text: chunk chỉ chứa `{"type": "reasoning", ...}` →
   `emit_delta` không được gọi (chuỗi rỗng, `emit_delta` tự no-op).
5. Viết `_text_from` và nối vào vòng drain.
6. Chạy test streaming + test graph node. Nếu có test e2e chạm SSE, chạy luôn.

## Success Criteria

- [x] Test list-block fail trước khi sửa, pass sau khi sửa
- [x] Test `str` không đổi kết quả
- [x] Chunk toàn block reasoning không phát delta rỗng
- [x] Không có file nào khác ngoài `routes.py` + test bị sửa
- [x] Ship được độc lập, không cần Phase 2

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| `.content_blocks` không tồn tại trên phiên bản langchain đang cài | Thấp | `getattr(..., None) or []`. Spike đã xác nhận API này có trên bản đang dùng (`langchain-openai 1.4.2`) |
| Ghép text từ nhiều block làm mất khoảng trắng | Thấp | Block text của LangChain giữ nguyên whitespace của model; test bằng chuỗi có dấu cách hai đầu |
| Đụng vùng code Phase 2 của deepdive plan cũng sửa | Trung bình | Deepdive Phase 2 sửa nhánh `updates`, phase này sửa nhánh `messages` — khác nhánh trong cùng vòng lặp. Ghi rõ khi ship để tránh merge conflict câm |
