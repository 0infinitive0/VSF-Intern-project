---
phase: 6
title: "Polish node"
status: reverted
priority: P3
effort: "1.5d"
dependencies: [1, 3]
---

# Phase 6: Polish node

> **Đã gỡ bỏ (2026-08-16).** Node ship ở `off`, eval đạt 100% number parity nhưng
> phát hiện 2 ca đổi nghĩa mà parity không thể bắt (xem cuối `plan.md`). Toàn bộ
> code, config `REPLY_POLISH_*`, prompt và eval đã bị xoá thay vì để lại sau flag —
> một đường rewrite đang tắt vẫn là lời mời bật lên. Phần dưới giữ nguyên làm hồ sơ
> thiết kế; kết luận đọc ở `ARCHITECTURE.md` §"Reply generation rule".

## Overview

Thêm một node LLM **rewrite-only** giữa `budget_check` và `respond`, diễn đạt lại reply
template cho tự nhiên hơn mà không được thêm bất kỳ fact nào. Kèm eval gate cơ học: mọi
con số trong reply sau polish phải khớp reply trước polish, lệch một số là fail.

> **Ghi nhận:** tôi đã khuyến nghị YAGNI cho phase này khi tư vấn — reply xác định hiện
> tại đã đúng và an toàn, và rủi ro là LLM bịa số tiền. Người dùng đã cân nhắc và quyết
> định làm. Plan thực thi đầy đủ với các rào chắn dưới đây, không thương lượng.

## Requirements

**Functional**

- Polish chỉ chạy trên đường `budget_check → respond` — đường mang reply template có số liệu.
- Prompt cấm thêm fact; node cấm output chứa số không có trong input.
- Bất kỳ thất bại nào (timeout, exception, eval fail) → trả nguyên bản, im lặng với người dùng.
- Ba chế độ qua env: `off` (mặc định), `shadow` (chạy, log, vẫn trả nguyên bản), `on`.

**Non-functional**

- Timeout ngắn; không được kéo dài p95 turn latency vượt ngưỡng đã thoả thuận.
- Eval gate 100% number-parity trên bộ mẫu trước khi bật `on` ở production.

## Architecture

### Vấn đề đặt node ở đâu

Reply được **lắp trong `respond`** (`respond.py:287-292`), không phải trong state. Một
node đứng trước `respond` không có sẵn reply để mà polish.

Không nhân bản logic chọn reply. Tách nó ra:

```python
# respond.py — trích xuất từ thân hàm respond hiện tại
def select_reply(state: TravelGraphState) -> str | None:
    """Reply của turn này theo thứ tự ưu tiên, hoặc None nếu không node nào
    phát ngôn. Tách khỏi `respond` để `polish` dùng chung nguồn sự thật —
    hai nơi tự chọn reply sẽ trôi khỏi nhau."""
    return (
        _compose(state.get("intake_answer"), state.get("next_question"))
        or _reply_from_task_results(state)
        or _reply_from_messages(state)
    )
```

`respond` trở thành:

```python
def respond(state):
    reply = state.get("polished_reply") or select_reply(state)
    if reply is None:
        logger.error(...)                      # canary từ Phase 1
        reply = _ACK_EN if ... else _ACK_VI
    ...
```

`polish` ghi `polished_reply` vào state. `respond` ưu tiên nó. Một nguồn sự thật cho
việc **chọn**, một nơi duy nhất **lắp** response.

### Chỉ wire trên một edge

`respond` hôm nay có 6 đường vào. Chỉ một đường được polish:

| Đường vào `respond` | Polish? | Lý do |
|---|---|---|
| `budget_check → respond` | **Có** | Đường mang reply template từ worker — đúng thứ cần diễn đạt lại |
| `scope_guard (blocked) → respond` | Không | Text từ chối an ninh phải giữ nguyên văn |
| `ask_slot (ask) → respond` | Không | Câu hỏi intake — địa phận Phase 16 của plan trước; polish có thể đổi nghĩa câu hỏi |
| `intake_qa → respond` | Không | Đã do LLM sinh |
| `qa_node → respond` | Không | Đã do LLM sinh |
| `supervisor (all done) → respond` | Không | Không có reply worker để polish |

Thay đổi topology trong `graph.py`, đúng một dòng:

```python
builder.add_edge("budget_check", "polish")
builder.add_edge("polish", "respond")
```

Thêm `"polish"` vào `NODE_NAMES` (test topology `test_graph_v2_skeleton.py` assert
không có node mồ côi).

### Eval gate — number parity

Rào chắn chính. Chạy **trong node**, không phải chỉ trong test:

```python
_NUMBER_RE = re.compile(r"\d[\d.,]*")

def _numeric_tokens(text: str) -> collections.Counter:
    """Multiset các token số, đã chuẩn hoá dấu phân cách nghìn.
    Multiset chứ không phải set: '2 khách sạn, 2 sao' mất một '2' vẫn là lỗi."""
    return collections.Counter(
        token.rstrip(".,").replace(".", "").replace(",", "")
        for token in _NUMBER_RE.findall(text)
    )

def _numbers_preserved(before: str, after: str) -> bool:
    return _numeric_tokens(before) == _numeric_tokens(after)
```

Không chỉ "không thêm số" mà **bằng nhau tuyệt đối** — bỏ sót một con số cũng là làm sai
lệch thông tin (mất giá phòng thì reply thành vô dụng).

Prompt phải nói rõ để model không tự ý đổi format: cấm đổi `2.500.000` thành
`2,5 triệu`. Chuẩn hoá dấu phân cách trong `_numeric_tokens` chỉ để chống khác biệt vô hại
`2.500.000` vs `2500000`, không phải để cho phép đổi đơn vị.

### Prompt

```
Bạn nhận một câu trả lời đã hoàn chỉnh của trợ lý du lịch. Nhiệm vụ duy nhất:
viết lại cho tự nhiên và dễ đọc hơn.

TUYỆT ĐỐI KHÔNG ĐƯỢC:
- Thêm bất kỳ con số nào không có trong bản gốc
- Bỏ bất kỳ con số nào có trong bản gốc
- Đổi cách viết số (giữ nguyên 2.500.000, không đổi thành "2,5 triệu")
- Thêm tên địa điểm, khách sạn, món ăn, hoạt động không có trong bản gốc
- Thêm nhận định, đánh giá, lời khuyên không có trong bản gốc
- Đổi cấu trúc dòng/ngày nếu bản gốc có định dạng theo ngày

CHỈ ĐƯỢC: đổi cách diễn đạt, nối câu, bỏ lặp từ, làm giọng văn thân thiện hơn.

Bản gốc:
{reply}

Trả về DUY NHẤT bản viết lại, không giải thích.
```

### Ba chế độ

`REPLY_POLISH_MODE`, theo đúng khuôn `JAILBREAK_GUARD_MODE` — khai bằng
`Literal[...] = Field(...)` ở `config.py:100`, đọc bằng `getattr(get_settings(), ...)` ở
`scope_guard.py:48`. Cùng khuôn với `contract_enforcement_mode` mà Phase 1 thêm:

| Mode | Hành vi | Dùng khi |
|---|---|---|
| `off` (mặc định) | Node return `{}` ngay | Production cho tới khi eval gate đạt |
| `shadow` | Chạy LLM, chạy eval, **log** kết quả, vẫn trả nguyên bản | Thu số liệu thật an toàn |
| `on` | Chạy, trả bản polish nếu qua eval; nguyên bản nếu không | Sau khi shadow chứng minh 100% parity |

`shadow` là thứ khiến phase này an toàn: thu được dữ liệu eval trên traffic thật mà người
dùng không chịu rủi ro nào.

### Thứ tự thất bại

```
mode == off                         → return {}
select_reply(state) is None         → return {}   (không có gì để polish; canary Phase 1 lo)
LLM timeout / exception             → log warning, return {}
output rỗng                         → return {}
_numbers_preserved == False         → log ERROR kèm cả hai bản, return {}
mode == shadow                      → log info, return {}
                                    → return {"polished_reply": polished}
```

Mọi đường thất bại đều `return {}` → `respond` dùng `select_reply` như cũ. Người dùng
không bao giờ thấy sự khác biệt khi hỏng.

## Related Code Files

- Create: `backend/src/agents/graph/nodes/polish.py`
- Create: `backend/tests/test_polish_node.py`
- Create: `eval/polish_number_parity.py` — script chạy eval trên bộ mẫu reply
- Modify: `backend/src/agents/graph/nodes/respond.py` — tách `select_reply`, ưu tiên `polished_reply`
- Modify: `backend/src/agents/graph/state.py` — thêm `polished_reply: str | None`
- Modify: `backend/src/agents/graph/nodes/load_context.py` — reset `polished_reply` mỗi turn
- Modify: `backend/src/agents/graph/graph.py` — thêm node + 2 edge, thêm vào `NODE_NAMES`
- Modify: `backend/src/agents/graph/prompts.py` — `build_polish_prompt`
- Modify: `backend/src/config.py` — `reply_polish_mode`
- Modify: `backend/tests/test_respond.py` — test `polished_reply` được ưu tiên
- Modify: `ARCHITECTURE.md` — bổ sung polish vào "Reply generation rule" (Phase 3)

## Implementation Steps

1. **Tách `select_reply` khỏi `respond`** — refactor thuần, không đổi hành vi. Chạy
   `test_respond.py`, phải xanh ngay. Không gộp với bước sau.

2. **Thêm `polished_reply` vào `TravelGraphState`** + reset trong `load_context` (nó là
   turn-scoped, giống `intake_answer`).

3. **Viết `_numeric_tokens`/`_numbers_preserved` + test trước node.** Đây là phần dễ sai
   nhất, test kỹ:
   - `"2.500.000đ"` vs `"2500000 đồng"` → preserved
   - `"3 khách sạn"` vs `"3 khách sạn tuyệt vời"` → preserved
   - `"3 khách sạn"` vs `"nhiều khách sạn"` → **fail**
   - `"2 sao, 2 phòng"` vs `"2 sao, 3 phòng"` → **fail**
   - `"2 sao, 2 phòng"` vs `"2 sao"` → **fail** (multiset, mất một token)
   - `"08:00-10:00"` giữ nguyên → preserved
   - `"2.500.000"` vs `"2,5 triệu"` → **fail** (đổi đơn vị)

4. **Thêm `reply_polish_mode` vào config**, mặc định `"off"`.

5. **Viết `polish.py`** theo thứ tự thất bại ở trên. Dùng `get_fast_llm(temperature=0.3)`.
   Đặt timeout tường minh — không dựa vào default của provider.

6. **Viết `build_polish_prompt`** trong `prompts.py`, giữ cùng chỗ với các prompt khác.

7. **Wire graph**: `budget_check → polish → respond`, thêm `"polish"` vào `NODE_NAMES`.
   Chạy `test_graph_v2_skeleton.py` — nó có **ba** assert chạm node mới:
   - dòng 52-53: `unreachable = set(NODE_NAMES) - visited` → node phải reachable từ START
   - dòng 56-57: `extra = set(graph_repr.nodes) - set(NODE_NAMES)` → **bắt buộc** thêm
     `"polish"` vào `NODE_NAMES`, không thì test đỏ
   - dòng 81: `other_node_names` suy ra từ `NODE_NAMES` cho test "node nào được phép
     `interrupt()`" — `polish` rơi vào nhóm **không** interrupt, đúng thiết kế (nó chỉ
     gọi LLM rồi trả về, không bao giờ pause)

8. **Test node với LLM mock**: mọi đường thất ​bại trả `{}`; đường thành công trả
   `polished_reply`; mode `shadow` trả `{}` dù LLM thành công và eval pass.

9. **Test `respond` ưu tiên `polished_reply`** khi có, `select_reply` khi không.

10. **Viết `eval/polish_number_parity.py`**: nạp một bộ reply mẫu (lấy từ output thật của
    `format_trip_response_from_json` + `budget_check` + `hotel_node`, tối thiểu 30 mẫu phủ
    trip 1/3/5/7 ngày, no-results, over-budget, amenity-drop), chạy polish, báo cáo tỉ lệ
    parity. Đặt cạnh harness eval sẵn có trong `eval/`.

11. **Chạy eval, ghi kết quả vào phase này.** Ngưỡng bật `on`: **100%** parity trên toàn bộ
    mẫu. Không phải 99%.

12. **Bật `shadow` ở staging**, chạy ít nhất một ngày traffic thật, đọc log parity.

13. **Quyết định**: 100% parity ở cả eval lẫn shadow → cho phép `on`. Không đạt → để `off`
    vĩnh viễn, ghi kết quả vào `ARCHITECTURE.md`, và báo lại rằng Phase 16 của plan trước
    nhiều khả năng nên huỷ.

14. **Cập nhật `ARCHITECTURE.md`** mục "Reply generation rule" (Phase 3): polish là ngoại
    lệ được kiểm soát — rewrite-only, có eval gate cơ học, mặc định tắt.

## Success Criteria

- [x] `select_reply` tách khỏi `respond`; `respond` là nơi duy nhất lắp response
- [x] `polish` chỉ nằm trên edge `budget_check → respond`, không đường nào khác
- [x] `polished_reply` là turn-scoped, reset trong `load_context`
- [x] Mọi đường thất bại trả `{}` → người dùng thấy nguyên bản
- [x] `_numbers_preserved` là multiset-equality, có test cho cả 7 case ở bước 3
- [x] `REPLY_POLISH_MODE` mặc định `off`; `shadow` không bao giờ đổi output người dùng
- [x] Eval ≥30 mẫu, báo cáo tỉ lệ parity, kết quả ghi vào phase
- [x] Chỉ bật `on` khi parity = 100% ở cả eval và shadow — **không bật**: parity đạt 100% nhưng đọc output phát hiện 2 ca đổi nghĩa (xem Execution Log)
- [x] `test_graph_v2_skeleton.py` xanh với node mới
- [x] `ARCHITECTURE.md` ghi polish như ngoại lệ có kiểm soát

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| **LLM bịa hoặc đổi số tiền** | **Cao** | Rào chắn chính của phase. Eval gate multiset-equality chạy trong node, không chỉ trong test. Mặc định `off`. `shadow` thu dữ liệu mà không rủi ro. Ngưỡng bật là 100%, không nới. |
| LLM giữ đúng số nhưng đổi ngữ nghĩa ("không tìm thấy" → "có ít lựa chọn") | **Cao** | Number parity **không** bắt được lỗi này. Bước 10 bộ mẫu phải phủ các case negative (no-results, over-budget, amenity-drop) và bước 12 shadow log cả hai bản để người đọc so sánh thủ công. Nếu thấy đảo nghĩa → để `off`. |
| Tăng latency mỗi turn có worker | Trung bình | Chỉ trên edge `budget_check`, không phải mọi turn. Timeout tường minh. Đo p95 trước/sau ở bước 12. |
| Reply nhiều ngày (5-7 ngày) bị LLM cắt bớt | Trung bình | Bộ mẫu bước 10 bắt buộc có trip 5 và 7 ngày. Số ngày là số → parity bắt được việc mất cả một ngày. |
| Tách `select_reply` làm vỡ thứ tự ưu tiên | Thấp | Bước 1 refactor thuần, test xanh trước khi làm gì tiếp. |
| Phase này tốn công rồi kết luận không dùng được | Trung bình | Đó là kết quả hợp lệ. Bước 13 nói rõ: `off` vĩnh viễn là một outcome được chấp nhận, và nó trả lời luôn cho Phase 16 của plan trước. Chi phí đã bounded ở 1.5d. |

**Rollback:** `REPLY_POLISH_MODE=off` — node return `{}` ngay, không LLM call, hành vi
y hệt trước phase. Không cần revert code.

## Execution Log — 2026-08-16

### Kết luận: code ship, `REPLY_POLISH_MODE` để `off`. Không khuyến nghị bật.

Number-parity gate **đạt 100%**. Lượt đọc thủ công **không đạt**. Theo đúng risk row
"LLM giữ đúng số nhưng đổi ngữ nghĩa" của chính phase này, kết quả là để `off`.

### Bước 11 — kết quả eval

`python3 eval/polish_number_parity.py`, 35 mẫu, `gpt-5-mini-2025-08-07`, ngày 2026-08-16.
Report: `eval/results/polish-number-parity-20260816T022221Z.json`.

| Chỉ số | Kết quả |
|---|---|
| Số mẫu | 35 (yêu cầu ≥30) |
| Phủ trip 1/3/5/7 ngày | có, ×2 mức giá/sao |
| Phủ no-results, over-budget, amenity-drop | có |
| **Number parity** | **35/35 = 100.00%** |
| Cấu trúc reply 7 ngày | giữ nguyên — 31 dòng vào, 31 dòng ra, đủ khối ngày |

Hàng rào số **hoạt động đúng như thiết kế**. Không mẫu nào bị thêm, bớt, hay đổi định
dạng số. Rủi ro "reply 5-7 ngày bị cắt bớt" không xảy ra.

### Bước 13 — hai ca đổi nghĩa mà parity không thấy

Đây là lý do phase này không được bật, và cả hai đều **qua** parity 100%:

**1. `hotel_amenity_drop_all` — đảo ngược ý nghĩa con số**

```
BEFORE: Yêu cầu 'hồ bơi' loại 7 khách sạn, 'gần biển' loại 5 khách sạn — không còn lựa chọn nào.
AFTER : Với yêu cầu 'hồ bơi' (7 khách sạn) và 'gần biển' (5 khách sạn), hiện không còn lựa chọn nào.
```

`loại 7 khách sạn` = filter **loại bỏ** 7 khách sạn. Bản viết lại `'hồ bơi' (7 khách sạn)`
đọc tự nhiên thành **có** 7 khách sạn hồ bơi — nghĩa ngược lại — rồi kết bằng "không còn
lựa chọn nào", thành câu tự mâu thuẫn. Con số giữ nguyên tuyệt đối.

**2. `budget_replan_failed` — thêm một fact không có trong bản gốc**

```
BEFORE: Sau khi tìm khách sạn rẻ hơn, tổng chi phí vẫn là 13,500,000 VND (...)
AFTER : Dù đã tìm được khách sạn rẻ hơn, tổng chi phí vẫn là 13,500,000 VND (...)
```

Bản gốc nói *đã chạy* bước tìm khách sạn rẻ hơn. Bản viết lại khẳng định *đã tìm được* —
`budget_check` có message riêng cho việc đó ("Không tìm được khách sạn rẻ hơn: {error}"),
nên đây là fact mới do model thêm vào, đúng thứ prompt cấm.

**Ghi nhận thêm (nhẹ hơn, không phải lý do chặn):** `budget_over` bị đổi `VƯỢT` → `vượt`,
mất nhấn mạnh viết hoa cố ý của template. Ngược lại, `Hotel:` → `Khách sạn:` là một cải
thiện thật — nhãn tiếng Anh lọt vào output tiếng Việt của `format_trip_response_from_json`,
đáng sửa ở template chứ không cần LLM.

### Vì sao không chạy shadow

Bước 12 (shadow ≥1 ngày trên staging) **không chạy**, và không phải vì thiếu hạ tầng:
shadow tồn tại để phát hiện đúng loại lỗi vừa tìm thấy ở eval. Nó đã lộ ra rồi, ở bước rẻ
hơn. Chạy shadow lúc này chỉ để thu thêm ví dụ cho một kết luận đã có.

### Trạng thái code

Toàn bộ node đã ship và có test (20 test trong `test_polish_node.py`, đủ 7 ca parity của
bước 3 cộng mọi đường thất bại). Với `REPLY_POLISH_MODE=off` — mặc định — node return `{}`
ngay, **không có LLM call nào**, hành vi y hệt trước phase. Không cần revert.

Muốn thử lại: sửa prompt để chặn hai lỗi trên (cấm diễn giải lại quan hệ "loại bỏ / phù
hợp"; cấm chuyển "sau khi làm X" thành "đã đạt được X"), chạy lại
`python3 eval/polish_number_parity.py`, và **đọc** output chứ không chỉ nhìn con số parity.

### Hệ quả cho plan trước

Phase 16 của `260812-0927-langgraph-orchestration-state-patch-and-interrupts`
("Conversational polish layer for context lines and re-asks") — theo bước 13 của phase
này, **nhiều khả năng nên huỷ**. Bằng chứng: cùng một model, trên text ngắn và đơn giản
hơn text của Phase 16, đã hai lần đổi nghĩa trong 35 mẫu. Câu hỏi re-ask của `ask_slot`
còn nhạy cảm hơn với việc đổi nghĩa. Quyết định cuối thuộc về người dùng.

## Bổ sung — 2026-08-16, sau khi người dùng bật `on` và không thấy gì xảy ra

### Bug: timeout 6s là con số đoán, và nó giết đúng thứ node này sinh ra để làm

Người dùng set `REPLY_POLISH_MODE=on`, reply không đổi. Log container:

```
WARNING src.agents.graph.nodes.polish: Reply polish timed out after 6.0s; sending the original
```

Node chạy đúng, LLM call đúng, nhưng `_POLISH_TIMEOUT_SECONDS = 6.0` — một con số tôi
đoán khi viết bước 5 — nhỏ hơn thực tế 3-4 lần. Đo thật với `gpt-5-mini`:

| Loại reply | Ký tự | Thời gian (3 lần chạy) |
|---|---|---|
| Reply worker ngắn | 72 | 4.9s / 4.9s / 5.4s |
| Dòng ngân sách | 112 | 8.0s / 4.7s / 6.2s |
| **Itinerary 3 ngày** | 432 | **15.3s / 17.6s / 21.9s** |
| **Itinerary 7 ngày** | 820 | **16.6s / 21.1s / 17.9s** |

Ngay cả reply ngắn nhất (~5s) đã sát ngưỡng 6s. Mọi itinerary — **đúng loại reply mà
phase này tồn tại để diễn đạt lại** — luôn timeout. Triệu chứng nhìn từ ngoài giống hệt
"bật `on` mà không có gì xảy ra", vì mọi đường thất bại đều trả `{}` một cách im lặng.

`gpt-5-mini` là reasoning model — chính codebase đã biết điều đó
(`_openai_model_supports_temperature` loại `gpt-5*`). Độ trễ là chi phí reasoning, không
phải mạng chậm, và không có knob `reasoning_effort` để giảm.

### Vì sao eval bước 11 không bắt được

`eval/polish_number_parity.py` gọi thẳng `_rewrite`, **đi vòng qua executor và timeout của
node**. Nên nó báo 100% parity trong khi production timeout 100%. Lỗ hổng thật của bộ eval:
nó đo đúng thứ nó được thiết kế để đo (parity) và mù hoàn toàn với thứ quyết định node có
chạy được hay không (latency).

Đã sửa: eval giờ đo và báo cáo median / p95 / max latency, kèm tên mẫu chậm nhất, và ghi
vào report JSON.

### Đã sửa

- `_DEFAULT_POLISH_TIMEOUT_SECONDS = 25.0` — **đo được**, không đoán, kèm bảng số liệu
  trong docstring để người sau không hạ xuống mà không biết mình đang bỏ đi cái gì.
- Thêm `REPLY_POLISH_TIMEOUT_SECONDS` vào config → chỉnh được không cần deploy.
- Log timeout kèm độ dài reply: một loạt timeout nghĩa là ngưỡng sai so với reply thật,
  không phải model hỏng.
- `test_off_is_the_default` trước đây assert qua `get_settings()`, tức là đọc `.env` của
  máy dev — nó đỏ ngay khi người dùng bật `on`. Sửa thành assert field default của
  `Settings`, độc lập môi trường.

Verify trong container sau khi rebuild: reply itinerary 3 ngày, **17.8s, polish thành công**.

### Lưu ý triển khai (không phải bug, nhưng đã làm mất thời gian)

Code được **bake vào image**, chỉ `logs/` và `data/` là bind mount. `docker compose restart`
**không** nạp code mới — container vẫn chạy `polish.py` cũ với 6s. Phải
`docker compose up -d --build backend`.

### Điều này KHÔNG đổi kết luận của phase

Ngược lại, nó thêm lý do thứ hai, độc lập với lỗi đổi nghĩa:

> Polish tốn **15-22s** cho đúng loại reply nó nhắm tới, và thời gian đó nằm **trên lượt
> của người dùng**. Non-functional requirement của chính phase này viết: *"Timeout ngắn;
> không được kéo dài p95 turn latency vượt ngưỡng đã thoả thuận."* Một lượt dựng lịch
> trình vốn đã chậm, cộng thêm 15-22s để diễn đạt lại một câu đã đúng là đánh đổi tệ.

Vậy có **hai** lý do độc lập để `REPLY_POLISH_MODE=off`:

1. **Đổi nghĩa** — 2/35 mẫu, parity không bắt được (bước 13 ở trên).
2. **Độ trễ** — 15-22s trên lượt người dùng, cho đúng loại reply cần polish nhất.

Nếu sau này muốn mở lại: dùng model không-reasoning cho riêng polish (latency là chi phí
reasoning), sửa prompt chặn 2 lỗi đổi nghĩa, rồi chạy lại eval và **đọc** output.

## Bổ sung 2 — 2026-08-16: model nhanh hơn, và reply ngắn hơn

Hai thay đổi, xuất phát từ hai câu hỏi của người dùng: *"có thể dùng model nhanh hơn
không"* và *"itinerary 3 ngày chỉ cần hiển thị trên UI, không cần show text"*.

### A. Reply của itinerary giờ là tóm tắt ngắn, không phải cả lịch trình

UI đã render lịch trình từ `trip_plan` — `trip-overview-tab.tsx` (hotel card, route theo
ngày, stat) và `day-timeline.tsx` (từng ngày, giờ, hoạt động). Dump lại toàn bộ dưới dạng
text trong chat bắt người dùng đọc **cùng một kế hoạch hai lần**.

`itinerary_node` đường all-days-done giờ gọi `format_trip_summary_reply` thay vì
`format_trip_response_from_json`:

```
Đã dựng xong lịch trình 3 ngày quanh Khách sạn Mường Thanh.
Chi tiết từng ngày ở bảng lịch trình bên cạnh.
```

Vẫn **specific** (tên khách sạn + số ngày), nên contract `emits_reply` của Phase 1 vẫn
làm đúng việc của nó — một worker im lặng không thể núp sau câu này. Vẫn deterministic,
đọc từ trip đã dựng, không LLM. Đây **không** phải quay lại `_ACK_VI`: `_ACK_VI` là câu
chung chung không mang thông tin nào và bắn cho mọi loại turn.

Test `test_respond.py` đổi theo: assert tên khách sạn + "2 ngày", và thêm một test mới
assert reply **không** chứa `08:00` / tên địa điểm / xuống dòng — tức không lặp lại thứ UI
đã hiển thị.

### B. Model cho polish: `gpt-4.1-mini`

Độ trễ là chi phí reasoning, không phải bản chất của việc viết lại câu. Đo trên itinerary
7 ngày (820 ký tự), 2 lần chạy mỗi model:

| Model | Thời gian | Parity | Kết luận |
|---|---|---|---|
| `gpt-5-mini` (fast model hiện tại) | 23.8s / 20.3s | ok | Reasoning overhead, không dùng được |
| `gpt-5-nano` | 23.4s / 17.1s | ok | Cũng reasoning, không nhanh hơn |
| `gpt-4o-mini` | 3.7s / 3.8s | **FAIL** | Nhanh nhất nhưng làm sai số — loại |
| **`gpt-4.1-mini`** | **4.8s / 4.4s** | **ok** | **Chọn** |

`gpt-4o-mini` là lời nhắc rằng **nhanh không phải tiêu chí**: nó nhanh nhất và trượt hàng
rào số ngay ở mẫu đầu tiên.

Thêm `reply_polish_model` vào config (rỗng = dùng `LLM_FAST_MODEL`), truyền vào
`get_fast_llm(model=...)`. Không ảnh hưởng ai không set nó.

### C. Chạy lại eval với `gpt-4.1-mini` (37 mẫu, corpus đã cập nhật)

Corpus đổi cho khớp production: 8 mẫu `summary_*` (reply thật hiện tại) + 2 mẫu
`worstcase_full_itinerary_*` giữ lại làm ca xấu nhất — text dày số nhất mà node có thể
nhận.

| | Lần 1 | Sau khi vá prompt |
|---|---|---|
| Parity | 34/37 = 91.89% | **36/37 = 97.30%** |
| Latency median | — | **0.9s** |
| Latency p95 | — | **4.2s** |
| Latency max | — | **6.3s** (worst-case 7 ngày) |

**Latency: giải quyết xong.** Median 0.9s so với 15-22s trước đó — nhanh hơn ~20 lần.

3 ca fail lần 1 đều cùng một loại: model viết số nhỏ thành chữ (`1 khách sạn` → `một
khách sạn`, `0 khách sạn` → `Không có khách sạn nào`). Nghĩa đúng, nhưng vi phạm luật.
Đã vá prompt (cấm viết số thành chữ, có ví dụ), 2/3 hết. Còn `zero_edge`: model vẫn nhất
quyết đổi `Có 0 khách sạn` → `Không có khách sạn nào` bất chấp lệnh cấm tường minh.

### D. Kết luận: vẫn `off`. Model nhanh hơn không sửa được thứ đang chặn.

**Hai lỗi đổi nghĩa lặp lại y hệt trên `gpt-4.1-mini`:**

```
hotel_amenity_drop_all
  BEFORE: Yêu cầu 'hồ bơi' loại 7 khách sạn, 'gần biển' loại 5 khách sạn — không còn lựa chọn nào.
  AFTER : Yêu cầu 'hồ bơi' có 7 khách sạn, 'gần biển' có 5 khách sạn — hiện không còn lựa chọn nào khác.
```
`loại 7` (bị loại bỏ) → `có 7` (có 7 cái). Đảo ngược, y như `gpt-5-mini` đã làm.

```
budget_replan_failed
  BEFORE: Sau khi tìm khách sạn rẻ hơn, tổng chi phí vẫn là 13,500,000 VND (...)
  AFTER : Dù đã tìm khách sạn có giá thấp hơn, tổng chi phí vẫn là 13,500,000 VND (...)
```
Vẫn khẳng định *đã tìm được*.

**Hai model khác hẳn nhau, cùng hai lỗi, cùng vị trí.** Đây là bằng chứng mạnh hơn nhiều
so với lần đo trước: vấn đề nằm ở **bản chất công việc**, không ở lựa chọn model. Đổi
model chỉ đổi giá và tốc độ, không đổi việc một model viết lại câu mang dữ liệu sẽ diễn
giải lại quan hệ trong câu đó.

Trạng thái cuối:
- Latency: **đã sửa** (0.9s median với `gpt-4.1-mini`)
- Parity: 97.30% — **chưa đạt** ngưỡng 100%
- Đổi nghĩa: **chưa sửa được**, và không sửa được bằng cách đổi model

`REPLY_POLISH_MODE=off`. Người dùng hiện đang để `on` trong `.env` của máy mình — đó là
lựa chọn của họ, đã báo rõ đánh đổi.
