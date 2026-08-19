# Chẩn đoán: `qa_node` không stream theo token

Ngày: 2026-08-19 · Phát hiện từ Phase 3 của plan `260819-0931-responses-api-migration-opt-in-with-reasoning-summary`
Đo bằng fake LLM, không tốn API.

## Triệu chứng

Smoke test Phase 3 đo được, ở **cả hai** transport:

| node | delta frames | ký tự |
|---|---|---|
| `intake_qa` | 41 | 154 |
| `qa_node` | **2** | ~650 |

Hai frame cho 650 ký tự không phải streaming. `qa_node` là node trả lời chính của sản
phẩm — hiệu ứng typewriter ở đó chưa bao giờ chạy.

## Nguyên nhân — đã chứng minh

Dump mọi chunk chế độ `messages` kèm metadata, không lọc:

```
=== intake_qa ===
  node='intake_qa'   AIMessageChunk   frames=17   chars=34    <-- token thật
  node='respond'     AIMessage        frames=1    chars=209

=== qa_node ===
  node='qa_node'     AIMessage        frames=1    chars=57    <-- cả câu, một lần
  node='respond'     AIMessage        frames=1    chars=57
```

Khác biệt nằm ở **kiểu**: `intake_qa` phát `AIMessageChunk` (token), `qa_node` phát
`AIMessage` (thông điệp hoàn chỉnh).

Lý do: `qa_node` **không phải node thường, nó là subgraph biên dịch sẵn**
(`graph.py:119`: `builder.add_node("qa_node", build_qa_subgraph(...))`).
`app.stream(stream_mode=["updates","messages"])` **không đi xuống subgraph lồng nhau**.
Thứ vòng drain nhìn thấy chỉ là thông điệp đầu ra của subgraph, phát một lần ở biên node.

Chạy lại đúng truy vấn đó với `subgraphs=True`:

```
=== qa_node ===
  ('qa_node:9e34a52c-...',)|agent   AIMessageChunk   frames=27   chars=57
  ()|respond                        AIMessage        frames=1    chars=57
```

**27 frame token vẫn luôn ở đó — chỉ là không ai nhìn thấy.** Node bên trong tên là
`agent`, không phải `qa_node`.

## Hình dạng của bản sửa

`subgraphs=True` trên `app.stream(...)`. Nhưng nó **không phải một dòng**:

1. **Tuple đổi hình dạng.** `for mode, chunk in app.stream(...)` thành
   `ValueError: too many values to unpack` — với `subgraphs=True`, generator trả
   `(namespace, mode, chunk)` ba phần tử. Đã gặp thật khi đo.
2. **Bộ lọc phải đổi trục.** `STREAMING_NODES` hiện so `metadata["langgraph_node"]` với
   `{"qa_node", "intake_qa"}`. Node bên trong subgraph tên `agent`, nên phép so đó
   không bao giờ khớp. Phải lọc theo **gốc namespace** (`qa_node:<uuid>` → `qa_node`),
   trong khi `intake_qa` vẫn ở namespace rỗng. Hai trục lọc trong cùng một vòng lặp.
3. **`respond` vẫn phát lại y nguyên câu trả lời** (frame cuối, 57 ký tự trùng khít).
   Bất biến "không gửi câu trả lời hai lần" phải giữ nguyên sau khi đổi trục lọc.

## Rủi ro chưa đo

**Tool-call có rò vào `delta` không?** Đây là câu hỏi quan trọng nhất và phép đo này
**không trả lời được** — fake LLM không gọi tool. Vòng ReAct của `qa_node` có tool
(`QA_TOOLS`); khi `subgraphs=True`, mọi chunk của node `agent` sẽ tới, gồm cả các hop
sinh tool call. Về lý thuyết tham số tool đi trong `tool_call_chunks` chứ không trong
`content`, nên `content` rỗng và `emit_delta` tự no-op — nhưng đó là suy luận, chưa đo.

Chính bất biến này là lý do `STREAMING_NODES` tồn tại: `test_stream_modes.py`
`TestWhatMustNeverStream` khoá việc JSON của `extract_patch` không được lộ ra. Bản sửa
phải mở rộng cùng lớp test đó sang tool call của ReAct trước khi tin.

## Sai lệch tài liệu

`docs/chat_api_contract.md` §Streaming mô tả `delta` là "real LLM tokens ... from the
graph nodes that write prose for the user (`STREAMING_NODES`: `qa_node`, `intake_qa`)".
Với `qa_node` điều đó **không đúng hôm nay**: nó là một thông điệp trọn gói, không phải
token. Sửa code thì tài liệu thành đúng; không sửa thì tài liệu cần đính chính.

## Vì sao lỗi này sống lâu

`test_stream_modes.py::TestDeltaFrames::test_a_qa_turn_streams_its_answer` chỉ khẳng
định `emitter.of("delta")` **không rỗng**. Một frame trọn gói thoả mãn điều đó. Không
test nào nói gì về **số lượng** frame, mà số lượng mới là toàn bộ khác biệt giữa
"typewriter" và "cả câu hiện ra một lúc".

## Phạm vi

Không thuộc plan Responses API — giống hệt nhau ở cả hai transport, có từ trước. Nhưng:

- **Chặn Phase 5** của plan đó: khối thinking dựng trên luồng delta này.
- Liên quan `260818-0924-deepdive-thinking-loader`, plan đang sở hữu UI streaming.

Nên là plan riêng, hoặc một phase của deepdive plan — không nhét vào plan Responses API.

## Câu hỏi mở

1. Tool-call của ReAct có rò vào `delta` khi bật `subgraphs=True` không? Phải đo bằng
   LLM thật hoặc fake có gọi tool.
2. ~~Có node subgraph nào khác cũng bị che luồng token không?~~ **Không.** `graph.py:102-121`
   — `qa_node` là node duy nhất được `add_node` bằng một graph biên dịch sẵn; 12 node còn
   lại đều là hàm thường (hoặc hàm bọc `enforce_contract`). Lỗi này chỉ có một chỗ.
