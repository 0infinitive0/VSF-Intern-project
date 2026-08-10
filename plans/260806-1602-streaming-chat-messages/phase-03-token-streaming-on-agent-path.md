---
title: "Phase 3: Token streaming on agent path"
status: done
phase: 3
priority: P1
effort: "1.5 ngày"
dependencies: [1]
---

# Phase 3: Token streaming nhánh agent

## Overview

Phát `delta` event chứa token LLM thật cho **duy nhất** nhánh `_run_chat_agent`
(`session.py:1085`) — đường chat tự do sau khi đã có danh sách khách sạn hoặc đã có lịch
trình. Ba nhánh còn lại không có prose LLM nào để stream (xem bảng 4 nhánh ở `plan.md`).

Phần khó của phase này **không phải** lấy token ra — LangGraph cho sẵn. Phần khó là ba cái
bẫy có thật trong vòng lặp hiện tại: text bị loại sau khi đã phát, tiền tố `SYSTEM ERROR:`
phải được sanitize *trước* khi ra ngoài, và vòng retry 2 lần.

## Requirements

- Functional:
  - `_run_chat_agent` phát `delta` cho prose cuối của agent, không phát cho token của tool
    call.
  - Nối các `delta` (sau `reset` gần nhất) == `final.reply`.
  - Không bao giờ để lọt JSON tool-call hoặc `SYSTEM ERROR:` ra ngoài dưới dạng `delta`.
- Non-functional:
  - `stream_mode` đổi không được làm hỏng phần đồng bộ `session.state` từ `last_event`.
  - Đường POST cũ đi qua cùng hàm này, không phát gì.

## Architecture

### Ba cái bẫy

**Bẫy 1 — text bị loại sau khi đã phát.** `session.py:1197` chỉ nhận
`final_ai_response` nếu `not _looks_like_textual_tool_call(...)`. Nghĩa là agent có thể
sinh trọn một khối JSON giả-tool-call, rồi code **vứt đi và thử lại**
(`session.py:1209`). Nếu đã stream thì người dùng vừa xem một đống JSON chạy qua màn hình.

**Bẫy 2 — `sanitize_system_error` chạy sau lượt.** `routes.py:179` sanitize
`result.text` *sau khi* `process_chat_turn` trả về. Với stream thì text đã ra ngoài rồi.

**Bẫy 3 — retry 2 vòng.** `for attempt in range(2)` (`session.py:1086`). Vòng 2 có thể
phát một câu trả lời hoàn toàn khác.

### Giải pháp: cổng 16 ký tự đầu

Không phát delta ngay từ token đầu. Gom vào buffer cho tới khi có **16 ký tự không-trắng
đầu tiên**, rồi quyết định một lần cho cả attempt:

```python
class _DeltaGate:
    """Giữ token lại tới khi đủ căn cứ quyết định có được stream attempt này không.

    Chặn hai thứ, cả hai đều đã có tiền lệ trong vòng lặp hiện tại:
      - JSON giả-tool-call, thứ `_looks_like_textual_tool_call` sẽ vứt ở cuối
        lượt (session.py:1197) — nhưng nó chỉ phán được khi đã có đủ text
      - tiền tố "SYSTEM ERROR:", thứ `sanitize_system_error` thay thế ở
        routes.py:179 — nhưng nó chỉ chạy sau khi lượt kết thúc

    16 ký tự đủ để phủ cả `{`/`[` mở đầu lẫn trọn chuỗi "SYSTEM ERROR:" (13 ký tự).
    """
    PROBE = 16

    def __init__(self) -> None:
        self._buf = ""
        self._decided: bool | None = None    # None=chưa quyết, True=cho stream

    def feed(self, chunk: str) -> str | None:
        """Trả về phần text được phép phát ra ngay, hoặc None nếu chưa/không stream."""
        if self._decided is False:
            return None
        self._buf += chunk
        if self._decided is None:
            stripped = self._buf.lstrip()
            if len(stripped) < self.PROBE:
                return None                   # chưa đủ căn cứ, giữ lại
            self._decided = not (
                stripped[0] in "{[" or stripped.startswith("SYSTEM ERROR:")
            )
            if self._decided is False:
                return None                   # attempt này im lặng, trả nguyên khối cuối lượt
            out, self._buf = self._buf, ""
            return out                        # xả buffer đã gom
        out, self._buf = self._buf, ""
        return out

    def flush(self) -> str | None:
        """Gọi khi stream của attempt kết thúc. Xả nốt phần còn kẹt trong buffer khi
        cả câu trả lời ngắn hơn PROBE ký tự ("Có." / "Yes.") — không có nó thì câu
        trả lời rất ngắn không bao giờ được phát ra dưới dạng delta, dù final.reply
        vẫn đúng."""
        if self._decided is False or not self._buf:
            return None
        stripped = self._buf.lstrip()
        if self._decided is None and (
            stripped[:1] in ("{", "[") or stripped.startswith("SYSTEM ERROR:")
        ):
            self._decided = False
            return None
        out, self._buf = self._buf, ""
        self._decided = True
        return out
```

Vòng lặp tạo **một instance cho mỗi attempt** (`gate = _DeltaGate()` ở đầu mỗi vòng
`for attempt in range(2)`) và gọi `gate.feed(...)` / `gate.flush()` — không gọi như
classmethod.

Khi `_decided is False`, attempt đó **không stream gì cả** và text về nguyên khối trong
`final` — đúng hành vi hôm nay. Không có gì xấu lọt ra màn hình.

Nếu agent sinh prose sạch ở attempt 1 rồi vòng lặp vẫn loại nó vì lý do khác, phát
`reset` để client xoá buffer. Đây là lưới an toàn, không phải đường chính.

### Lấy token ra khỏi LangGraph

`session.py:1121` đang là `stream_mode="values"`. Đổi sang list:

```python
events = session.agent.stream(
    {**session.state, "messages": [("user", agent_input)]},
    config=config_with_limit,
    stream_mode=["values", "messages"],
)
```

Với list `stream_mode`, mỗi item trở thành tuple `(mode, payload)` thay vì payload trần.
Vòng lặp hiện tại phải tách hai nhánh:

```python
for mode, payload in events:
    if mode == "values":
        ...toàn bộ logic hiện có, không đổi một dòng...
    elif mode == "messages":
        msg, meta = payload
        # Chỉ stream prose của node agent. Bỏ token của tool call:
        # AIMessageChunk mang tool_calls/tool_call_chunks là agent đang gọi tool,
        # không phải trả lời người dùng.
        if getattr(msg, "tool_call_chunks", None) or getattr(msg, "tool_calls", None):
            continue
        if meta.get("langgraph_node") != "agent":
            continue
        text = gate.feed(msg.content)
        if text:
            emit_delta(text)
```

**Phải xác minh bằng thực nghiệm, không tin tài liệu:** hình dạng chính xác của tuple
`(mode, payload)` và tên `meta["langgraph_node"]` phụ thuộc phiên bản LangGraph đang cài.
Bước 1 của phase là in ra và ghi lại hình dạng thật — codebase này đã có tiền lệ đúng cách
làm đó (`state.py` docstring: *"verified empirically, not from docs alone"*).

Nhánh `mode == "values"` phải giữ nguyên **toàn bộ** logic hiện có: `last_event`, đồng bộ
`session.state`, dựng lại `TripIntakeState` từ `pending_hotel_selection`, tín hiệu
anti-loop. Đây là phần dễ làm hỏng nhất của phase.

### `generating`

Phát `phase` key `generating` **một lần**, ngay trước delta đầu tiên được cổng cho qua.
Không phát nếu attempt bị cổng chặn.

## Related Code Files

- Modify: `backend/src/agents/session.py` — `_run_chat_agent`: `stream_mode`, tách nhánh, cổng delta
- Modify: `backend/src/api/streaming.py` — `emit_delta`, `emit_reset`
- Create: `backend/src/agents/delta_gate.py` — `_DeltaGate` (tách riêng để test được độc lập)
- Create: `backend/tests/test_agents/test_delta_gate.py`
- Modify: `backend/tests/test_api/test_chat_stream.py` — assertion nối delta == reply

## Implementation Steps

1. **Xác minh thực nghiệm trước:** viết một script tạm in ra hình dạng thật của
   `stream_mode=["values","messages"]` trên phiên bản LangGraph đang cài — tuple shape,
   khoá của `meta`, có `tool_call_chunks` hay không. Ghi kết quả vào docstring của
   `_run_chat_agent`. **Xoá script sau khi xong.**
2. Tạo `delta_gate.py` + test đơn vị: prose sạch, JSON mở đầu `{`, mở đầu `[`,
   `SYSTEM ERROR:`, chuỗi ngắn hơn 16 ký tự rồi kết thúc, chuỗi toàn khoảng trắng đầu.
3. Đổi `stream_mode` thành list; tách vòng lặp hai nhánh. Chạy
   `backend/tests/test_agents/` + `test_chat_turn_characterization.py` — phải xanh trước
   khi thêm bất kỳ delta nào.
4. Nối `_DeltaGate` + `emit_delta` vào nhánh `messages`.
5. Phát `generating` trước delta đầu tiên.
6. Phát `reset` khi `final_ai_response` bị loại mà cổng đã cho stream.
7. Thêm assertion "nối delta == final.reply" vào test stream.

## Success Criteria

- [x] Hình dạng thật của `stream_mode` list được xác minh bằng chạy thật và ghi vào docstring
      — script chạy với `_FakeStreamingModel` (không cần Ollama), kết quả ghi vào docstring
      `_run_chat_agent`, script đã xoá sau khi ghi lại
- [x] Lượt hỏi đáp tự do stream token thấy được; frame delta đầu tới trước `final` —
      `test_parity_agent_chat_branch` (qua endpoint thật) + mock server `:stream` hook
- [x] Nối delta == `final.reply` trên mọi lượt có stream — `test_delta_gate.py` (đơn vị) +
      `test_parity_agent_chat_branch` (qua HTTP thật)
- [x] Attempt sinh JSON tool-call: **không có delta nào**, `final.reply` vẫn đúng như hôm nay
      — `TestGateMutesToolCallJson` trong `test_delta_gate.py`. Phát hiện và sửa một lỗi
      thật trong quá trình xác minh: `_flush()` chỉ chặn lại ở lần gọi ra quyết định, lần
      `close()` gọi lại vẫn xả buffer bị mute — đã sửa, giờ chặn ở **mọi** lần gọi
- [x] Attempt sinh `SYSTEM ERROR:`: không có delta, `final.reply` là chuỗi đã sanitize —
      `test_system_error_prefix_never_emits_a_delta`
- [x] Lượt intake / hotel / finalize: **không có delta nào** — 3/4 nhánh của
      `test_stream_post_parity.py` khẳng định `deltas == []`
- [x] `test_chat_turn_characterization.py` và `test_agents/` xanh, không sửa test — xanh so
      với baseline `main` (đã đối chiếu qua `git stash`); 2 fake-agent stub trong
      `test_chat_turn_characterization.py` được cập nhật để khớp hình dạng
      `(mode, payload)` thật của `stream_mode` list — không đổi assertion nào
- [x] `session.state` sau lượt stream giống hệt sau lượt POST cùng input — đường đồng bộ
      `session.state` từ nhánh `values` không đổi giữa hai chế độ (`stream` chỉ tác động
      nhánh `messages`); xác nhận gián tiếp qua `final` khớp byte-for-byte giữa hai
      endpoint trên cả 4 nhánh (các field `intake`/`hotel_options`/`trip_plan` đều dựng từ
      `session.state`)

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Đổi `stream_mode` làm hỏng đồng bộ `session.state` từ `last_event` | Bước 3 tách nhánh và chạy test **trước khi** thêm delta. Tiêu chí "state sau stream == sau POST" gác lần cuối |
| Hình dạng tuple khác tài liệu | Bước 1 xác minh bằng chạy thật, đúng tiền lệ của repo |
| Cổng 16 ký tự cắt mất câu trả lời hợp lệ rất ngắn ("Có.") | `flush()` xả nốt buffer ở cuối mỗi attempt kể cả khi chưa đủ 16 ký tự, và vẫn áp cùng bộ lọc `{`/`[`/`SYSTEM ERROR:`. Có test riêng cho ca này |
| Token của node tool lọt ra | Lọc **hai** lớp: `tool_call_chunks`/`tool_calls`, và `meta["langgraph_node"] != "agent"` |
| Vòng retry phát hai lượt delta chồng nhau | `_DeltaGate` khởi tạo lại mỗi attempt; `reset` báo client xoá buffer khi attempt trước bị loại |
