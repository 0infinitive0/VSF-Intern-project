---
title: "Responses API — opt-in migration + reasoning summary"
description: "Bật OpenAI Responses API sau một cờ env (default vẫn Chat Completions), vá guard streaming đang nuốt delta im lặng, đo A/B trên lượt thật, rồi stream reasoning summary vào khối thinking bên cạnh dữ kiện graph."
status: in-progress
priority: P1
branch: "main"
effort: "~6d"
tags: [llm, openai, responses-api, streaming, sse, reasoning, eval, frontend]
created: 2026-08-19
updated: 2026-08-19
blockedBy: [260818-0924-deepdive-thinking-loader]
blocks: []
---

# Responses API — opt-in migration + reasoning summary

## Overview

Toàn bộ đường chạy hiện đi qua **Chat Completions**. `backend/src/services/llm.py`
không set `use_responses_api`, `output_version`, `reasoning`, hay `include` ở bất kỳ
nhánh nào (`llm.py:160,214,247`), nên `BaseChatOpenAI._use_responses_api()`
(`langchain_openai/chat_models/base.py:1761`) luôn rơi xuống nhánh Chat Completions.

Plan này làm ba việc, theo đúng thứ tự rủi ro tăng dần:

1. **Vá một lỗ hổng đang tồn tại** — `routes.py:711` guard `isinstance(content, str)`
   sẽ nuốt sạch delta, không exception, không log, ngay khi `content` thành list block.
   Lỗ này không cần ai đổi code để nổ: `_model_prefers_responses_api`
   (`base.py:605-616`) tự chuyển đường cho mọi model tên bắt đầu `gpt-5-pro`,
   `gpt-5.x-pro`, hoặc chứa `codex`. Đổi một biến env là đủ.
2. **Bật Responses API sau một cờ**, default bật, phạm vi giới hạn ở nhánh provider
   `openai` và họ model hỗ trợ. Rollback = đổi env, không deploy lại.
3. **Stream reasoning summary** vào khối thinking, chạy song song với dữ kiện graph
   mà `260818-0924-deepdive-thinking-loader` đang dựng.

## Bối cảnh phải đọc trước

**Spike đã đo thật:** `plans/reports/spike-260818-reasoning-summary.md` (2026-08-18).
Những con số dưới đây là đo, không phải giả định:

| Điều | Kết quả đo |
|---|---|
| Summary có ra chữ | Có, cả `gpt-5-mini` và `gpt-5.1` — nhưng chỉ khi model thực sự suy luận |
| Độ phủ | **Không dự đoán được.** Prompt lịch trình → 0 block; prompt xác suất → 59 block |
| Ngôn ngữ | **Luôn tiếng Anh.** System prompt tiếng Việt + chỉ dẫn ép tiếng Việt tường minh đều không đổi được |
| Latency | Không tăng. TTFT `gpt-5-mini` medium: 17.6s → 1.0s |
| `content` shape | **List block, không phải `str`.** Guard `routes.py` vỡ — đã xác nhận |
| Tool-calling | Còn sống. `bind_tools` qua Responses API gọi tool bình thường |
| `gpt-4o-mini` | **400 BadRequest** với cả `reasoning` lẫn `reasoning_effort` |
| Effort khuyến nghị | `medium`. `high` không thêm nội dung nhưng cắt mất text trả lời |

**Quyết định bị đảo ngược.** Ngày 2026-08-18 dự án chốt *không* dùng reasoning summary
(spike §6.1), và `260818-0924-deepdive-thinking-loader/plan.md:62` ghi "Không đụng
Responses API" như một non-goal. Ngày 2026-08-19 người dùng chọn ngược lại: bật summary
và render kèm dữ kiện graph. Lý do cũ vẫn đúng và không biến mất — **summary lúc có lúc
không, và bước gọi tool thì luôn rỗng** — nên kiến trúc ở đây phải coi reasoning là
*lớp phụ* chồng lên dữ kiện graph, không bao giờ là nguồn duy nhất lấp khối UI.
Phase 6 chịu trách nhiệm sửa lại hai file plan kia cho khớp.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Delta không bao giờ bị nuốt im lặng, bất kể model đi đường API nào | P1 |
| 2 | Bật/tắt Responses API bằng một biến env, không cần sửa code | P1 |
| 3 | Không provider nào ngoài OpenAI bị ảnh hưởng; `gpt-4o-mini` (judge của eval) không vỡ | P1 |
| 4 | Có số đo A/B thật (latency, token, cost, hop) trước khi bàn tới việc đổi default | P2 |
| 5 | Reasoning summary hiển thị trong khối thinking, phụ trợ cho dữ kiện graph | P2 |
| 6 | Hai plan chồng lấn được sửa cho nhất quán, không để hai nguồn sự thật | P2 |

## Non-Goals

- **Không** dùng server-side state (`previous_response_id`, `store=true`). LangGraph
  checkpointer đang là nguồn sự thật của transcript; thêm state phía OpenAI tạo nguồn
  thứ hai, và `QA_CONTEXT_TOKEN_BUDGET` trimming sẽ mâu thuẫn với response chain phía
  server. Phase 3 chỉ *đo* xem có đáng mở plan riêng hay không.
- **Không** đổi default sang Responses API trong plan này. Vì cả việc flip default lẫn
  server-side state đều là non-goal, phép đo chi phí/hop phục vụ chúng đã được hoãn sang
  [Phase 3b](./phase-03b-deferred-cost-and-hop-ab.md).
- **Không** đụng OpenRouter, Cloudflare, Ollama, Google, Anthropic.
- **Không** dịch reasoning summary sang tiếng Việt. Spike §Q2 đã chứng minh prompt
  không kiểm soát được ngôn ngữ; thêm lớp dịch là leo thang phạm vi.
- **Không** dựng khối thinking UI — đó là việc của `260818-0924-deepdive-thinking-loader`.

## Kiến trúc quyết định

### Cờ điều khiển

```
LLM_USE_RESPONSES_API=false     # default; giữ nguyên hành vi hôm nay
LLM_REASONING_SUMMARY=off       # off | auto ; chỉ có tác dụng khi cờ trên bật
```

Hai cờ tách rời có chủ ý: chuyển đường API và phát summary là hai rủi ro khác nhau.
Cái đầu có thể vỡ streaming; cái sau chỉ thêm nội dung. Gộp thành một cờ thì không
rollback riêng được.

### Guard theo họ model, không theo provider

Nhánh `openai` trong `llm.py` phục vụ **cả** judge của eval
(`eval/harness/judge.py:19` hardcode `get_llm(provider="openai", model="gpt-4o-mini")`).
Spike §4.1 đo được `gpt-4o-mini` trả 400 cho cả `reasoning` và `reasoning_effort`.
Nên cờ phải đi kèm một guard họ model, dùng lại đúng vị từ đang có:
`_openai_model_supports_temperature` (`llm.py:24`) đã phân biệt chính xác họ
`gpt-5/o1/o3/o4` với phần còn lại. Bật Responses API cho model nằm ngoài họ đó là
sai, kể cả khi env bảo bật.

### `stream_options` — hazard chưa ai đo

`llm.py` với base URL mặc định của OpenAI → langchain tự set `stream_usage=True`
(`base.py:1246`), và test `backend/tests/test_llm_provider.py:161` đang khoá hành vi đó.
Khi stream, `_stream` nhét `stream_options` vào kwargs (`base.py:1642`). Nhưng
`_construct_responses_api_payload` (`base.py:4293`) pop `stop`, `max_tokens`,
`tool_choice`, `response_format`, `verbosity` — **không pop `stream_options`**.
Payload Responses API sẽ mang theo một key API đó không có.

Đây là suy luận từ đọc source, **chưa chạy thật**. Phase 2 bước 1 phải đo trước khi
viết fix, và fix phải nằm ở `llm.py` (set `stream_usage=False` khi bật Responses API),
không phải patch vào langchain.

### Reasoning là lớp phụ, không phải nguồn chính

`deepdive` Phase 3 lập nguyên tắc: **FE giữ quyền sở hữu text hiển thị**, BE gửi khoá
đục + số liệu, không bao giờ gửi câu chữ (`phase-03:26-27`). Reasoning summary vi phạm
nguyên tắc đó — nó là văn xuôi tiếng Anh do model sinh ra.

Giải pháp là làm ngoại lệ đó **tường minh và có kiểu riêng**, không âm thầm nhét vào
`delta`: một event SSE mới tên `reasoning`, tách hẳn khỏi `delta` và `phase`. FE render
nó trong một làn riêng bên trong khối thinking, dưới các dòng dữ kiện, với dấu hiệu thị
giác cho biết đây là chữ của model chứ không phải chữ của sản phẩm. Dữ kiện graph vẫn
là thứ lấp khối UI; reasoning chỉ chồng thêm khi có.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Vá guard streaming](./phase-01-start.md) | **Done** |
| 2 | [Opt-in Responses API trong model factory](./phase-02-opt-in-responses-api-in-the-model-factory.md) | **Done** |
| 2.5 | [Helper đọc text dùng chung](./phase-02b-shared-response-text-helper.md) | **Done** |
| 3 | [Smoke test qua graph thật](./phase-03-measure-the-a-b-on-real-turns.md) | **Done** |
| 3b | [A/B chi phí và số hop](./phase-03b-deferred-cost-and-hop-ab.md) | **Hoãn** |
| 4 | [Reasoning summary qua dây](./phase-04-reasoning-summary-over-the-wire.md) | Pending |
| 5 | [Làn reasoning ở frontend](./phase-05-frontend-reasoning-lane-in-the-thinking-block.md) | Pending |
| 6 | [Quyết định rollout + hoà giải cross-plan](./phase-06-rollout-decision-and-cross-plan-reconciliation.md) | Pending |

Phase 1 độc lập hoàn toàn — ship riêng được, không phụ thuộc quyết định migrate.
**Phase 2.5 chặn Phase 4**: cờ của Phase 2 hiện là súng đã lên đạn — bật lên là 8 chỗ
gọi LLM hỏng im lặng, mà Phase 4/5 lại đòi bật nó.
Phase 5 bị chặn bởi `260818-0924-deepdive-thinking-loader` Phase 4 (khối thinking UI
phải tồn tại trước).

**Phase 2.5 và 3b không có trong plan gốc.** Chúng xuất hiện ngày 2026-08-19 khi người
dùng hỏi "Phase 3 có rút số lượt chạy được không" — câu hỏi đó buộc phải xem lại Phase 3
đang đo gì, và lộ ra hai điều: phần đo phục vụ quyết định đã hoãn, còn câu hỏi thật sự
chặn Phase 4 thì bị bỏ sót.

## File ownership

| Phase | Files |
|---|---|
| 1 | `backend/src/api/routes.py` (vòng drain `messages`), `backend/tests/` |
| 2 | `backend/src/services/llm.py`, `backend/src/config.py`, `backend/.env.example`, `backend/tests/test_llm_provider.py` |
| 2.5 | `backend/src/services/llm.py` (helper), + 9 module đọc `.content`: `extract_patch`, `intake_qa`, `routes`, `trip_planner`, `trip_edit_planner`, `trip_intake`, `suggestions`, `supabase_search`, `amenity_catalog` |
| 3 | `backend/scripts/smoke_responses_api.py`, `plans/reports/` |
| 4 | `backend/src/api/routes.py` (vòng drain), `backend/src/api/streaming.py`, `docs/chat_api_contract.md` |
| 5 | `frontend/src/api/stream-client.ts`, `frontend/src/hooks/use-chat-session.ts`, component khối thinking (do deepdive Phase 4 tạo) |
| 6 | `plans/260818-0924-deepdive-thinking-loader/*`, `plans/reports/spike-260818-reasoning-summary.md`, `docs/` |

Phase 1, 2.5 và 4 cùng chạm vòng drain của `routes.py`; Phase 2 và 2.5 cùng chạm
`llm.py`. Mỗi phase xây trực tiếp trên phase trước — không chạy song song nhóm này.

## Cross-plan

| Plan | Quan hệ | Lý do |
|---|---|---|
| `260818-0924-deepdive-thinking-loader` (pending) | plan này **blockedBy** | Phase 5 cần khối thinking UI từ deepdive Phase 4. Đồng thời deepdive `plan.md:62` khai "Không đụng Responses API" là non-goal — Phase 6 phải sửa. |
| `260818-1650-eval-latency-and-cost-instrumentation…` (in-progress) | chồng lấn, không chặn | Phase 4 của plan đó đọc `usage_metadata` đã chuẩn hoá (`usage_recorder.py:98`), field này tồn tại ở cả hai API. Nhưng `model_name` (`usage_recorder.py:93`) đọc từ `llm_output`/`response_metadata` — hình dạng Responses API khác, Phase 3 phải xác nhận. |

## Success Criteria

- [x] Delta vẫn tới client khi model đi đường Responses API (test, không phải suy luận)
- [x] `LLM_USE_RESPONSES_API=false` cho hành vi byte-identical với hôm nay
- [x] `gpt-4o-mini` không bao giờ nhận `reasoning*` param, kể cả khi cờ bật
- [x] OpenRouter / Cloudflare / Ollama không đổi hành vi — test khoá
- [x] Không call site nào còn giả định `.content` luôn là `str`
- [x] Smoke test qua graph thật: kết quả khớp nhau giữa cờ tắt và cờ bật
- [ ] Reasoning summary hiện trong khối thinking, và khối vẫn đầy đủ nội dung khi summary rỗng
- [ ] `docs/chat_api_contract.md` mô tả event `reasoning`
- [ ] Không còn mâu thuẫn giữa plan này, deepdive plan, và spike report

## Open questions

1. ~~`stream_options` có làm Responses API trả 400 không?~~ **Không** — đo 2026-08-19, `plans/reports/probe-260819-responses-api-payload-and-usage.md`.
2. ~~`usage_recorder._record` đọc được `model_name` từ Responses API không?~~ **Có** —
   đúng dated snapshot id, `usage_metadata` đầy đủ gồm `cache_read` và `reasoning`.
3. Rollout thật: bật cờ ở staging trước hay bật thẳng cho một tỉ lệ traffic? Chưa có
   hạ tầng feature-flag theo % trong repo — Phase 6 cần người dùng chốt.
4. **Mới 2026-08-19.** `qa_node` chỉ phát 2 frame delta cho ~650 ký tự — không stream
   theo token, khác hẳn `intake_qa` (41 frame / 154 ký tự). Không phải hồi quy của plan
   này (giống nhau ở cả hai transport), nhưng Phase 5 dựng khối thinking trên luồng delta
   đó. Cần điều tra riêng trước Phase 5.
