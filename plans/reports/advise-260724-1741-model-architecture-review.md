# Advise — Model & Architecture Review (V-OTA PoC)

> Nguồn: /ak-advise session 24/07/2026. Plan gốc: `plans/260723-1015-v-ota-poc-master-roadmap`.
> Bối cảnh xác nhận: team 3 người quen LangGraph, budget API ~vài chục USD, M2 ~17/8, M3 ~31/8.

## 1. Verdict

- Kiến trúc hiện tại (LangGraph + FastAPI + Postgres + Qdrant + validation node) **phù hợp, không đổi**.
- Vấn đề thật: (a) model chưa chốt, `src/services/llm.py` hardcode `ChatOpenAI` mâu thuẫn `design_proposal.md` (Gemini chính + OpenAI fallback); (b) Sprint 2 dồn toàn bộ sản phẩm vào ~2 tuần.
- **Không fine-tune/train LLM**: corpus 1.100 hotels quá nhỏ, BRD chỉ yêu cầu grounding, không đủ thời gian. Đã confirm với user: training chỉ là option → loại.

## 2. Chốt model theo thành phần

| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| Hội thoại + orchestration | **Gemini 2.5 Flash** (primary), GPT-4o-mini (fallback) | Tiếng Việt tốt, function calling, ~$10/PoC. Khớp failsafe design_proposal §A |
| Embedding RAG | **BGE-M3 self-host** (benchmark vs multilingual-E5 bằng probe set ~20 query song ngữ) | Cross-lingual VI↔EN, chi phí 0, không rate limit. Gemini embedding = phương án 2 |
| Ranking hotel | **Heuristic**: `α·vector_score + β·filter_match + γ·rating` | Cố ý không dùng ML — không có dữ liệu hành vi để train |
| Itinerary planner | **Heuristic Python** (cụm địa lý + budget + giờ mở cửa) + LLM viết narrative | OR-Tools = stretch goal Phase 7 |
| Evaluation | LLM-as-judge cho test scenarios Phase 6/8 (BO-04 ≥70%) | |
| Memory/session | Postgres (bảng `sessions`/`chat_messages` có sẵn) | Không Redis, không Neo4j |

## 3. Kiến trúc agent (chốt)

```
FastAPI /chat (SSE streaming)
  └─ LangGraph StateGraph (1 graph)
     ├─ detect_language (heuristic langid → LLM khi mơ hồ)
     ├─ intent + slot extraction (1 LLM call, structured output)
     ├─ router: search | refine | itinerary | handoff | chitchat
     ├─ tools:
     │   search_hotels(query, filters) → Qdrant top-K → Postgres filter+rank
     │   get_hotel_details(id)         → Postgres
     │   build_itinerary(slots)        → heuristic planner
     │   handoff(hotel_id)             → source_url + context payload
     ├─ generate (grounded, trả lời đúng ngôn ngữ detect)
     └─ validate (entity vs retrieved IDs; fail → re-retrieve, không re-generate)

State: messages, language, 5 slots, active_filters, candidates, selected_hotel → Postgres
```

Khớp 100% Phase 2–7 roadmap hiện tại. Chỉ cần ghi rõ trong plan: ranking = heuristic có công thức; planner heuristic = default, solver = stretch; thêm LLM-as-judge vào Phase 6/8.

## 4. Đánh giá lời khuyên bên ngoài (stack "sản phẩm thật")

| Đề xuất | Verdict | Lý do |
|---|---|---|
| LLM có sẵn + function calling, không train | ✅ | Trùng khuyến nghị |
| RAG embedding + vector DB | ✅ | = Phase 2 |
| Rule-based + retrieval trước | ✅ | = vertical slice |
| LightGBM/XGBoost ranker từ click/booking | ❌ | Không tồn tại dữ liệu hành vi; PoC kết thúc trước khi có user |
| OR-Tools solver | ⚠️ | Stretch goal, không default — BR-06 chỉ cần tối ưu mức PoC |
| Redis | ❌ | Postgres đã có bảng session; thêm service không giải quyết vấn đề nào |
| Neo4j | ❌ | 5 slot profiling = 1 JSON column |
| Booking execution / payment / hủy phòng | ❌ | BRD §4 để booking engine ngoài scope; BR-05 chỉ cần handoff kèm context |

→ Lộ trình 4 giai đoạn kia là roadmap **post-PoC**. Ghi vào Phase 8 như "Future work" (ranker học hành vi, booking execution) — trả lời câu "tiếp theo là gì" ở Demo Day, chặn scope creep bây giờ.

## 5. Itinerary có dùng AI không → Có, hybrid (Mức 2)

- **Mức 1 — LLM làm tất cả**: ❌. Bịa địa điểm (vi phạm BR-07), cộng sai budget, xếp lịch phi thực tế địa lý.
- **Mức 2 — Hybrid** ✅ khuyến nghị cho Phase 7:
  1. LLM extract preferences từ câu tự nhiên → slots có cấu trúc
  2. Retrieval lấy attraction/hotel THẬT từ Qdrant/Postgres
  3. Heuristic planner (Python): cụm địa lý (lat/lon từ OSM), phân ngày, số học budget thật
  4. LLM viết narrative VI/EN — chỉ được nhắc entity trong danh sách planner trả về
  5. Validation node check entity vs IDs (tái dùng node Phase 3)
- **Mức 3 — OR-Tools**: chỉ khi Mức 2 xong sớm; corpus nhỏ nên gain không đáng effort.
- Pre-check Phase 7: bảng `attractions` có đủ lat/lon, giá vé, giờ mở cửa? Thiếu trường nào thì bỏ ràng buộc đó, không bịa dữ liệu.

## 6. Work checklist

- [ ] Hỏi mentor: BR-10 còn bắt buộc? Handoff = deep-link hay stub page? KPI thresholds?
- [ ] Sửa `src/services/llm.py` → factory provider-agnostic (`init_chat_model`): Gemini primary, OpenAI fallback, canned-response failsafe
- [ ] Thêm `langchain-google-genai` + config keys
- [ ] Qdrant vào compose stack (Phase 2 step 1)
- [ ] Probe set ~20 query song ngữ; benchmark BGE-M3 vs multilingual-E5 vs gemini-embedding; ghi kết quả vào `plans/reports/`
- [ ] Chốt embedding model, index 1.103 hotels + attractions
- [ ] Vertical slice: 1 query VI end-to-end (detect → intent → search → generate → validate → stream) trước khi thêm intent
- [ ] Phân công 3 người: dialog core / search+handoff / UI song song
- [ ] Cập nhật plan: ranking heuristic công thức, planner heuristic default + solver stretch, LLM-as-judge Phase 6/8, Future-work section Phase 8

## 7. Success metrics

- Cross-language retrieval: VI query → EN-described hotel và ngược lại, ≥80% probe set đúng top-5
- Tổng chi phí API PoC ≤ $30 (track theo BRD §11)
- Validation node chặn hotel bịa trong test fixture (pytest pass)
- ≥70% test scenario tới booking handoff (BO-04, đo Phase 6)
- Kill switch: tắt Qdrant, chat vẫn trả kết quả qua SQL fallback
- Itinerary: tổng chi phí trong lịch ≤ budget user, mọi entity có ID trong DB

## Unresolved questions

1. BR-10 (bilingual) có bị descope miệng không — mentor xác nhận.
2. Booking handoff target: deep-link OTA (`hotels.source_url`) hay stub page.
3. KPI thresholds chốt tại kick-off — Phase 8 cần số cụ thể.
4. Bảng `attractions` có đủ trường cho planner (lat/lon, giá vé, giờ mở cửa)?
