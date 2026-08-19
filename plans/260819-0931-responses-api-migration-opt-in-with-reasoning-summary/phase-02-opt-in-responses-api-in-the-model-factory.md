---
phase: 2
title: "Opt-in Responses API trong model factory"
status: completed
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Opt-in Responses API trong model factory

## Overview

Thêm `LLM_USE_RESPONSES_API` (default `true`) vào nhánh provider `openai` của
`get_llm`. Khi tắt, hành vi phải giống hệt hôm nay. Khi bật, chỉ họ model hỗ trợ mới
đổi đường; mọi provider khác và `gpt-4o-mini` không bị chạm.

## Requirements

**Functional**
- `LLM_USE_RESPONSES_API=false` → `ChatOpenAI` được dựng y như hôm nay.
- `=true` + model thuộc họ `gpt-5/o1/o3/o4` → `use_responses_api=True`.
- `=true` + model **ngoài** họ đó (ví dụ `gpt-4o-mini`) → **không** bật, ghi log ở mức
  `INFO` nói rõ vì sao bỏ qua.
- Cờ chỉ đọc trong nhánh `openai`. Nhánh OpenRouter (`llm.py:196`) và Cloudflare
  (`llm.py:222`) không đọc nó dù cùng dựng lớp `ChatOpenAI`.
- `stream_usage` **không** bị đụng tới. Xem "Cái giá đã không phải trả" bên dưới.

**Non-functional**
- Không thêm nhánh `if` thứ hai song song với nhánh `openai` hiện có — sửa tại chỗ.
- Cờ đọc theo đúng thứ tự ưu tiên đang có trong file: tham số hàm → `os.environ` →
  `settings`. Không phá vỡ quy ước đó cho riêng cờ này.
- `_openai_model_supports_temperature` (`llm.py:24`) là vị từ họ model duy nhất trong
  file. Dùng lại nó thay vì viết vị từ thứ hai — hai danh sách họ model sẽ lệch nhau.

## Architecture

### Vị từ họ model

`_openai_model_supports_temperature` trả `False` đúng cho họ `gpt-5/o1/o3/o4` — cũng
chính là họ hỗ trợ `reasoning`. Đảo dấu nó cho ý nghĩa cần dùng, nhưng đọc `not
_openai_model_supports_temperature(m)` ở call site là ngược nghĩa và khó đọc. Thêm một
alias mỏng, cùng nguồn sự thật:

```python
def _openai_model_is_reasoning_family(model: str) -> bool:
    """Model thuộc họ reasoning của OpenAI (gpt-5/o1/o3/o4).

    Cùng một ranh giới với `_openai_model_supports_temperature`, phát biểu theo chiều
    dương. Một danh sách họ model, hai cách gọi — không phải hai danh sách.
    """
    return not _openai_model_supports_temperature(model)
```

### Nhánh `openai` sau khi sửa

```python
kwargs: dict[str, Any] = {"model": ..., "api_key": openai_key}
is_reasoning = _openai_model_is_reasoning_family(str(kwargs["model"]))

if is_reasoning:
    kwargs["reasoning_effort"] = target_reasoning_effort
else:
    kwargs["temperature"] = target_temp

if target_use_responses_api and is_reasoning:
    kwargs["use_responses_api"] = True
elif target_use_responses_api:
    logger.info(
        "LLM_USE_RESPONSES_API bật nhưng model %s ngoài họ reasoning — giữ Chat Completions.",
        kwargs["model"],
    )
```

### Cái giá đã không phải trả

> **Sửa 2026-08-19 sau phép đo.** Bản đầu của phase này bắt buộc `stream_usage=False`
> khi bật Responses API, vì đọc source thấy `_construct_responses_api_payload`
> (`base.py:4293`) pop `stop`/`max_tokens`/`tool_choice`/`response_format`/`verbosity`
> nhưng **không** pop `stream_options`. Suy luận đó đúng về code và sai về hậu quả.
>
> Đo thật (`plans/reports/probe-260819-responses-api-payload-and-usage.md`):
> request chạy bình thường với `stream_usage=True`, và `usage_metadata` tới
> `usage_recorder` đầy đủ ở **cả bốn** cấu hình đo, gồm cả `stream_usage=False`.
> `model` cũng đọc được đúng dated snapshot id.
>
> Nên `stream_usage` được để nguyên. Nó đang bị tắt để chữa một căn bệnh không tồn
> tại, trong khi cái giá của việc tắt — mất token usage của mọi call streaming, đúng
> thứ `test_llm_provider.py:161` khoá và eval plan `260818-1650` cần — là thật.
>
> Cổng chặn cứng của bước 2 cũ vì thế không kích hoạt, và phase này nhỏ hơn dự kiến.

## Related Code Files

- Modify: `backend/src/services/llm.py` (nhánh `openai` ~141-163, thêm vị từ ~24-29)
- Modify: `backend/src/config.py` (thêm setting + docstring nêu rõ default và lý do)
- Modify: `backend/.env.example` (khối "Chat LLM Configuration")
- Modify: `backend/tests/test_llm_provider.py`

## Implementation Steps

1. ~~Đo trước, sửa sau.~~ **Xong 2026-08-19** —
   `plans/reports/probe-260819-responses-api-payload-and-usage.md`. Không có 400,
   usage đầy đủ, `model` đọc được. Phép đo đó cũng xác nhận `_streamed_text` của
   Phase 1 khôi phục đúng text trên dây thật.
2. ~~Cổng chặn: dừng nếu usage không tới.~~ **Không kích hoạt** — usage tới ở cả bốn
   cấu hình đo.
3. Thêm `_openai_model_is_reasoning_family`, refactor nhánh `openai` dùng nó cho cả
   `temperature`/`reasoning_effort` (đang gọi `_openai_model_supports_temperature`
   trực tiếp).
4. Thêm `llm_use_responses_api: bool = False` vào `config.py` với docstring nêu: default
   tắt, phạm vi chỉ họ reasoning, và rollback bằng env.
5. Nối cờ vào nhánh `openai` theo sơ đồ trên.
6. Tests:
   - default tắt → không có `use_responses_api` trong instance
   - bật + `gpt-5-mini` → `use_responses_api is True`, `stream_usage` không bị đụng
   - bật + `gpt-4o-mini` → `use_responses_api` không được set (bảo vệ judge của eval)
   - bật + provider `openrouter` → không đổi (mở rộng test parametrize sẵn có ở
     `test_llm_provider.py:177`)
   - bật + provider `cloudflare` → không đổi
   - `test_openai_instance_reports_streamed_token_usage` (`:161`) vẫn pass khi cờ tắt
7. Cập nhật `.env.example` với cả hai cờ (`LLM_REASONING_SUMMARY` khai ở đây, dùng ở
   Phase 4) và một dòng nói rõ default + cách rollback.

## Success Criteria

- [x] Bước 1 có báo cáo đo, không phải suy luận từ source
- [x] Cờ tắt → mọi test hiện có pass không sửa
- [x] `gpt-4o-mini` không bao giờ nhận `use_responses_api`, có test — và xác nhận live
- [x] OpenRouter + Cloudflare có test khoá là không đổi
- [x] `usage_metadata` vẫn tới `usage_recorder` khi cờ bật — đo 2026-08-19
- [x] `config.py` docstring giải thích *vì sao* default tắt, không chỉ *là* tắt

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| ~~`stream_options` làm 400~~ | **Loại bỏ** | Đo 2026-08-19: không lỗi. Giả định sai từ đọc source |
| ~~Mất token usage → eval plan quy giá sai~~ | **Loại bỏ** | Usage tới đủ ở mọi cấu hình đo. `stream_usage` không còn bị đụng |
| Judge của eval (`gpt-4o-mini`) nhận param bị từ chối → toàn bộ eval vỡ | Cao | Guard họ model + test riêng. Spike §4.1 đã đo 400 thật |
| `extract_patch` dùng structured output — Responses API đi nhánh khác (`base.py:2265`) | Trung bình | Phase 3 phải chạy một lượt edit thật, không chỉ Q&A |
| Hai cờ làm ma trận cấu hình phình to | Thấp | Cờ thứ hai vô hiệu khi cờ thứ nhất tắt — 3 trạng thái hợp lệ, không phải 4 |
