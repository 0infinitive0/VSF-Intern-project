---
phase: 2.5
title: "Helper đọc text dùng chung cho mọi call site"
status: completed
priority: P1
effort: "0.5d"
dependencies: [2]
---

# Phase 2.5: Helper đọc text dùng chung cho mọi call site

## Overview

Phase 2 ship một cờ mà **bật lên là hỏng**. 8 chỗ gọi LLM đọc `.content` như thể nó
luôn là `str`; khi cờ bật, `gpt-5.1` và `gpt-5-mini` đều chuyển sang Responses API và
trả list block. Cả 8 chỗ nằm trong `except Exception` rộng có fallback, nên không
exception nào nổi lên, không test nào đỏ, không người dùng nào thấy lỗi — bot chỉ
ngừng hiểu yêu cầu.

Phase này đóng khoảng cách đó bằng **một** helper, và xoá bốn cách giải nửa vời đang
tồn tại song song.

> **Vì sao phase này có mặt.** Nó không nằm trong plan gốc. Phát hiện ra khi người dùng
> hỏi "Phase 3 có rút số lượt chạy được không" ngày 2026-08-19 — câu hỏi đó buộc phải
> xem lại Phase 3 đang đo gì, và lộ ra rằng nó bỏ sót đúng câu hỏi chặn Phase 4.

## Requirements

**Functional**
- Một hàm `response_text(response) -> str` trong `src/services/llm.py`, xử lý:
  - `content` là `str` → trả nguyên (đường nhanh)
  - `content` là list block → ghép các block `type == "text"`
  - block khác (`reasoning`, tool call) → bỏ qua
  - `content` là `None`/thiếu → `""`
- Áp cho **cả 8** call site đang hỏng.
- `intake_qa._response_text` và `routes._streamed_text` gộp vào helper này.
- `amenity_catalog._parse_model_json` giữ nguyên chức năng parse JSON, nhưng nhận text
  đã được helper trích ra thay vì tự kiểm `isinstance(content, str)` rồi trả `{}`.

**Non-functional**
- **Một hàm, không phải hai.** Streaming chunk và response hoàn chỉnh cùng một bài
  toán: lấy chữ người dùng đọc được ra khỏi `content`. Tách đôi là mở đường cho hai
  bản lệch nhau — đúng thứ vừa xảy ra với bốn hàm hiện có.
- Không đổi hành vi khi `content` là `str`. Đây là điều kiện để merge an toàn khi cờ tắt.
- Helper nằm ở `services/` chứ không `domain/`: `test_domain_layer_purity.py` cấm
  `domain/` import langchain, và helper này đọc kiểu dữ liệu của langchain.

## Architecture

### Bốn cách giải nửa vời hiện tại

| Hàm | Xử lý list? | Khi gặp list |
|---|---|---|
| `intake_qa._response_text` | ✅ | ghép block `text` — đúng |
| `routes._streamed_text` (Phase 1) | ✅ | ghép block `text` — đúng |
| `extract_patch._strip_json_fence` | ❌ | `str(list)` → repr Python → JSON hỏng |
| `amenity_catalog._parse_model_json` | ❌ | trả `{}` im lặng |

Hai cái đúng, viết độc lập, gần giống nhau. Hai cái sai, sai theo hai kiểu khác nhau.
Đó là định nghĩa của việc thiếu một chỗ dùng chung.

### Helper

```python
def response_text(response: Any) -> str:
    """Chữ người dùng đọc được trong một response hoặc một streamed chunk.

    Chat Completions đưa `content` là `str`; Responses API đưa list block. Việc
    chạm vào hình dạng thứ hai KHÔNG cần ai bật cờ: langchain tự định tuyến theo
    TÊN model (`gpt-5-pro*`, mọi tên chứa `codex`).

    Block không phải text (reasoning, tool call) không phải câu trả lời và bị bỏ.
    """
```

Đọc qua `.content_blocks` (khung chuẩn hoá của langchain) chứ không parse hình dạng
thô của nhà cung cấp — đã xác nhận trên dây thật, xem
`plans/reports/probe-260819-responses-api-payload-and-usage.md` §2.

### Chế độ hỏng của từng call site, đã kiểm chứng

| Call site | Hỏng thế nào khi cờ bật |
|---|---|
| `extract_patch.py:569` | `JSONDecodeError` → retry hết lượt → **mọi tin nhắn thành `general_question`, patch rỗng** |
| `trip_edit_planner.py:476` | như trên → yêu cầu sửa lịch trình không được hiểu |
| `trip_planner.py:174` | → rơi về theme mặc định |
| `trip_planner.py:725` | → fallback |
| `suggestions.py:70` | `AttributeError`: list không có `.strip()` |
| `trip_intake.py:557` | `str(list)` → repr → JSON hỏng |
| `supabase_search.py:163` | như trên → filter rỗng, tìm kiếm mất lọc |
| `amenity_catalog.py:328` | trả `{}`, **không cả exception** |

`extract_patch` nặng nhất: nó là cửa vào của mọi lượt.

### Cái KHÔNG hỏng

- `supervisor` dùng `with_structured_output` — **đo live 2026-08-19: chạy tốt** qua
  Responses API. Langchain tự xử lý phần parse. Không cần đụng.
- `intake_qa` và `routes` đã đúng sẵn, chỉ chuyển sang dùng helper chung.

## Related Code Files

- Modify: `backend/src/services/llm.py` (thêm `response_text`)
- Modify: `backend/src/agents/graph/nodes/extract_patch.py`
- Modify: `backend/src/agents/graph/nodes/intake_qa.py` (xoá `_response_text` cục bộ)
- Modify: `backend/src/api/routes.py` (xoá `_streamed_text` cục bộ)
- Modify: `backend/src/services/trip_planner.py` (2 chỗ)
- Modify: `backend/src/services/trip_edit_planner.py`
- Modify: `backend/src/services/trip_intake.py`
- Modify: `backend/src/services/suggestions.py`
- Modify: `backend/src/services/supabase_search.py`
- Modify: `backend/src/services/amenity_catalog.py`
- Modify: test tương ứng của từng module

## Implementation Steps

1. Viết `response_text` trong `services/llm.py` + unit test bao 4 hình dạng input
   (`str`, list text, list reasoning, `None`).
2. Chuyển `intake_qa._response_text` và `routes._streamed_text` sang helper. Test hiện
   có của cả hai phải pass **không sửa** — đó là bằng chứng helper tương đương.
3. Áp cho 8 call site còn lại, mỗi chỗ một commit logic riêng biệt trong đầu: đọc
   `response_text(response)` rồi mới parse.
4. Với mỗi call site, thêm một test khoá hành vi list-content. Không cần test đủ 8 nếu
   đường parse giống hệt nhau — nhưng `extract_patch`, `trip_intake`,
   `supabase_search`, `amenity_catalog` có 4 kiểu parse khác nhau, cần 4 test.
5. Chạy toàn bộ `backend/tests/`.
6. Chạy lại verify live với cờ bật: một lượt qua graph thật phải cho patch đúng, không
   rơi về `general_question`.

## Success Criteria

- [x] `response_text` có test cho cả 4 hình dạng input — 6 test
- [x] `intake_qa` và `routes` dùng helper, test cũ pass không sửa — 58 test
- [x] Cả 8 call site không còn đọc `.content` trực tiếp — grep xác nhận chỉ helper còn đọc
- [x] `extract_patch` trả patch đúng với list content — test đỏ khi hoàn nguyên, và verify live
- [x] Không còn hàm nào nửa vời xử lý riêng hình dạng này (xem ghi chú dưới)
- [x] Toàn bộ suite pass: 928 pass, đúng 7 fail có sẵn
- [x] Verify live: cờ bật cho patch giống hệt cờ tắt

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Sửa 10 file cùng lúc, khó review | Trung bình | Thay đổi mỗi chỗ là một dòng cùng dạng. Bước 2 chứng minh helper tương đương trước khi lan ra |
| `str(response.content)` ở vài chỗ đang cố ý ép kiểu cho input không phải message | Thấp | Đọc từng chỗ trước khi đổi; helper có `getattr` an toàn cho object lạ |
| Có call site thứ 9 chưa tìm ra | Trung bình | Sau khi sửa, grep lại `\.content` trên toàn `backend/src` như một bước kiểm |
| Đổi `amenity_catalog._parse_model_json` làm rơi guard `{}` | Thấp | Giữ nguyên `{}` khi JSON hỏng; chỉ đổi nguồn text đưa vào |

## Ghi chú sau khi làm

**Bằng chứng live cho cả hai chiều** (`extract_patch`, message `"cho tôi đi Đà Nẵng 4 ngày, 2 người"`):

| | cờ tắt | cờ bật |
|---|---|---|
| trước fix | `update_trip`, 2 thay đổi | **`general_question`, 0 thay đổi** |
| sau fix | `update_trip`, 2 thay đổi | `update_trip`, 2 thay đổi |

**Một mẩu code chết còn lại.** `amenity_catalog._parse_model_json` vẫn mở đầu bằng
`if not isinstance(content, str): return {}`. Giờ nó luôn nhận `str` từ `response_text`,
nên nhánh đó không bao giờ chạy. Để nguyên: nó vô hại, và xoá đi là churn trong một file
plan khác cũng đang chạm.

**3 lỗi lint `I001` do phase này tạo ra, đã sửa.** Import `response_text` thêm vào
`suggestions`, `trip_edit_planner`, `trip_intake` vi phạm cấu hình isort của repo (không
cho gộp import có alias). `ruff --select I001 --fix` tách thành dòng riêng. Delta lint
cuối cùng: 15 → 15.
