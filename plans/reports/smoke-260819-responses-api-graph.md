# Smoke: Responses API qua graph thật

Ngày: 2026-08-19 · Plan: `260819-0931-responses-api-migration-opt-in-with-reasoning-summary` Phase 3
Script: `backend/scripts/smoke_responses_api.py` · Models: `gpt-5.1-2025-11-13` + `gpt-5-mini-2025-08-07`

## Kết luận

**PASS.** 6 lượt (3 nhóm node × 2 cấu hình) qua LangGraph thật. Không exception, `intent`
và `patch` khớp nhau giữa hai transport, `usage_metadata` và `model` đầy đủ cho **mọi**
call ở cấu hình bật cờ.

## Kết quả

`LLM_USE_RESPONSES_API=false`

| lượt | err | intent | patch | deltas | reply | calls | usage | model |
|---|---|---|---|---|---|---|---|---|
| intake | - | `general_question` | 0 | 41 (154c) | 186c | 2 | 2/2 | 2/2 |
| qa | - | `general_question` | 0 | 2 (719c) | 630c | 3 | 3/3 | 3/3 |
| edit | - | `update_trip` | 2 | 0 | 109c | 3 | 3/3 | 3/3 |

`LLM_USE_RESPONSES_API=true`

| lượt | err | intent | patch | deltas | reply | calls | usage | model |
|---|---|---|---|---|---|---|---|---|
| intake | - | `general_question` | 0 | 30 (104c) | 136c | 2 | 2/2 | 2/2 |
| qa | - | `general_question` | 0 | 2 (596c) | 507c | 3 | 3/3 | 3/3 |
| edit | - | `update_trip` | 2 | 0 | 109c | 3 | 3/3 | 3/3 |

Bảy phép kiểm mỗi lượt — không exception, intent khớp, patch khớp, có reply, usage đủ,
model đủ, delta parity — đều đỗ cho cả ba lượt.

## Đọc ra được gì

**Kế toán chi phí không bị mù.** 8/8 call ở cấu hình bật cờ có `usage_metadata` và
`model`. Đây là điều kiện `eval/harness/cost.py` cần để quy giá, và nó giữ nguyên qua
transport mới. Xác nhận lại kết luận của probe Phase 2 ở mức graph.

**Phase 2.5 đã đóng đúng lỗ.** Lượt `edit` cho `intent='update_trip'` với 2 thay đổi ở
**cả hai** cấu hình. Trước Phase 2.5, cùng lượt đó ở cấu hình bật cờ cho
`general_question` với 0 thay đổi.

**Độ dài reply lệch nhau** (186c vs 136c, 630c vs 507c). Đây là nhiễu của model, không
phải dấu hiệu hỏng: cùng prompt gọi hai lần cũng lệch. Phép kiểm là "có reply", không
phải "reply giống hệt".

## Giới hạn của phép đo

- **Mỗi ô chạy một lần.** Đủ cho câu hỏi nhị phân "có vỡ không", không đủ cho bất kỳ kết
  luận nào về latency, chi phí, hay số hop. Đó là việc của Phase 3b, đang hoãn.
- **Không xác nhận được ReAct có gọi tool thật hay không.** Lượt `qa` cho 3 call LLM,
  nhưng script không phân biệt được đó là supervisor + qa + respond hay có tool xen vào.
  Spike 2026-08-18 §Q5 đã đo `bind_tools` qua Responses API riêng và kết luận còn sống;
  phép đo này không lặp lại điều đó.
- **Lượt `qa` chỉ phát 2 frame delta** cho ~600-700 ký tự, tức không stream theo token.
  Giống nhau ở cả hai cấu hình nên không phải hồi quy, nhưng là một điều đáng xem riêng:
  hiệu ứng typewriter ở `qa_node` có thể không hoạt động như thiết kế.
- Không chạm `trip_planner` (dựng lịch trình đầy đủ) và `hotel_node` — hai node nặng
  nhất. Chúng dùng cùng `response_text` sau Phase 2.5, nhưng chưa được chạy thật.
- Persistence tắt (`_persistence_enabled = False`), nên đường ghi DB không được chạm.

## Câu hỏi mở

1. Vì sao `qa_node` chỉ phát 2 frame delta thay vì stream từng token? Ngoài phạm vi plan
   này, nhưng ảnh hưởng trực tiếp tới khối thinking của Phase 5.
