# Câu trả lời cho phần Phụ lục (Slide 13–42)

Tài liệu này gom toàn bộ câu hỏi/nội dung trong phần **Phụ lục kỹ thuật** của bài slide (`docs/slide/index.html`, slide 13→42) thành các cặp Hỏi–Đáp để tra cứu nhanh khi bảo vệ, không cần lật từng slide. Số slide được giữ nguyên để đối chiếu.

---

## Slide 14 — Toàn bộ luồng LangGraph có bao nhiêu node, cấu trúc thế nào?

**Đáp:** 14 node: `load_context → scope_guard → extract_patch → validate_patch → apply_patch → ask_slot → (intake_qa) → supervisor → {hotel_node, itinerary_node, booking_node, qa_node} → budget_check → respond → END`.

- Checkpointer mặc định là **MemorySaver** (dev/CLI luôn dùng cái này); production dùng **PostgresSaver**, khởi tạo lúc FastAPI start.
- `hotel_node`, `itinerary_node`, `booking_node` được bọc bởi `enforce_contract()` — diff state trước/sau, raise lỗi nếu node ghi ngoài khai báo hoặc kết thúc mà không có reply.

---

## Slide 15 — Node 01: `load_context()` làm gì?

**File:** `nodes/load_context.py:49-75`

**Đáp:** Node đầu tiên sau START, chạy ở **mọi** turn. Reset các field chỉ tồn tại trong turn hiện tại: `patch=[]`, `intent=""`, `applied_changes=[]`, `jailbreak_blocked=False`, `supervisor_iterations=0`. Cố tình **không** reset các field xuyên-turn (`missing_slots`, `trip_data`, `selected_hotel_id`, `pending_clarify_day`).

- Dùng `state.get(...)` thay vì `state[...]` vì thread mới chưa có checkpoint.
- Routes to: `scope_guard` (luôn luôn). LLM calls: không có.

---

## Slide 16 — Node 02: `scope_guard()` làm gì?

**File:** `nodes/scope_guard.py:47-67`

**Đáp:** Chạy `detect_jailbreak()` trên tin nhắn cuối của user, theo config `jailbreak_guard_mode` (`block`/`log`/`off`, mặc định **block**). Nếu phát hiện jailbreak độ tin cậy cao ở mode block → `jailbreak_blocked=True`, đi thẳng tới `respond`, bỏ qua toàn bộ patch pipeline.

- **Guardrail song sinh** (từ chối câu hỏi ngoài phạm vi) **chưa được xây**, dù tài liệu kế hoạch cũ ghi là đã xong — cần nói rõ điều này nếu bị hỏi.
- Đây là bộ lọc an toàn duy nhất chạy trước khi patch pipeline động vào state.
- Routes to: `respond` (nếu blocked) · `extract_patch` (bình thường). LLM calls: không có (heuristic/regex detector).

---

## Slide 17 — Node 03: `extract_patch()` làm gì?

**File:** `nodes/extract_patch.py:588-658`

**Đáp:** Bước "hiểu người dùng" duy nhất trong toàn graph — 1 lời gọi **reasoning LLM** (temperature=0.0) trả về `{intent, changes[], reason}` dạng JSON, retry 1 lần nếu parse lỗi, fallback về patch rỗng, **không bao giờ raise**.

- `intent` **không** tự chọn worker — chỉ `detect_impact()` + `WORKFLOW_TO_WORKER` mới định tuyến.
- Nhiều lớp grounding tất định phủ lên kết quả LLM: khớp destination/theme/companion với danh mục đóng.
- Regex parse ngày tháng ghi đè LLM cho đúng định dạng date-picker của frontend.
- Resolve phạm vi ngày ("ngày 1"/"hôm cuối") thành field chính xác.
- Routes to: `validate_patch` (luôn luôn). LLM calls: 1 lần — `get_reasoning_llm`, temp 0.0.

---

## Slide 18 — Node 04: `validate_patch()` làm gì?

**File:** `nodes/validate_patch.py:132-154`

**Đáp:** Dry-run áp patch (`domain.travel_state.apply_patch`) mà **không commit**, rồi chạy `detect_impact()` để biết worker nào cần chạy sau này.

- `budget.target` đơn lẻ → suy ra dải min/max ±20% (sàn 100k VND).
- `budget.trip_total` chia đều theo số đêm → dải min/max tương tự.
- `interrupt()` do date-ambiguity ngày xưa nay đã là **dead code** — luôn resolve DD-MM tất định.
- Routes to: `apply_patch` (luôn luôn). LLM calls: không có.

---

## Slide 19 — Node 05: `apply_patch()` làm gì?

**File:** `nodes/apply_patch.py:35-74`

**Đáp:** Commit `proposed_travel_state → travel_state`. Dựng hàng đợi `pending_tasks` từ `impacted_workflows`, sắp theo `WORKER_ORDER` cố định: **hotel → itinerary → booking → qa**.

- Tự thêm `hotel_node` vào queue khi `selected_hotel_id` vừa được set — chọn khách sạn không tự sinh ra impacted_workflow.
- Ghi audit record best-effort vào `sessions.context_data["state_audit"]` — không bao giờ raise nếu lỗi.
- Routes to: `ask_slot` (luôn luôn). LLM calls: không có.

---

## Slide 20 — Node 06: `ask_slot()` làm gì?

**File:** `nodes/ask_slot.py:134-149`

**Đáp:** Slot-filling **tất định** — tìm slot bắt buộc còn thiếu tiếp theo theo thứ tự cố định (`destination → people → dates → budget`) và render câu hỏi Việt/Anh thật sự sẽ gửi cho user.

- Có nhánh "không bắt được ý" khi slot vừa hỏi lại vẫn chưa có giá trị hợp lệ.
- Thứ tự slot cố định trong `SlotSpec`, không đổi theo ngữ cảnh.
- Routes to: `respond` (hỏi) · `intake_qa` (câu hỏi giữa chừng) · `supervisor` (đủ slot). LLM calls: không có (render template).

---

## Slide 21 — Node 07: `intake_qa()` làm gì?

**File:** `nodes/intake_qa.py:66-92`

**Đáp:** Van thoát read-only cho 2 tình huống: (1) user hỏi thật giữa lúc đang bị hỏi slot — trả lời thay vì hỏi lại; (2) patch rỗng vì không nêu giá trị cụ thể — hỏi làm rõ thay vì âm thầm không làm gì.

- Không tool, không retry.
- Bất kỳ exception nào → trả về `{"intake_answer": None}`, không chặn turn.
- Routes to: `respond` · `supervisor`. LLM calls: 1 lần — `get_fast_llm`, temp 0.2, streaming.

---

## Slide 22 — Node 08: `supervisor()` làm gì?

**File:** `nodes/supervisor.py:185-336`

**Đáp:** Node điều phối thuần túy — `all_tasks_done` là predicate Python, **không gọi LLM**. 3 nhánh theo thứ tự: fast path (~90% turn, 0 LLM), LLM path (structured output), fallback (lỗi LLM → suy luận tất định).

- Fast path: lấy task đầu theo `WORKER_ORDER`, không gọi LLM.
- LLM path: `get_fast_llm(temp=0)` + structured output trên `SessionManifest` gọn (chỉ boolean/count, không dữ liệu thật).
- `MAX_SUPERVISOR_ITERATIONS=5`, `MAX_DAY_REBUILD_HOPS=100` tách riêng để itinerary >5 ngày không bị cắt.
- Route cứng `list_nearby` — fix bug: câu hỏi "gần khách sạn có gì" từng làm sinh lại cả itinerary.
- Routes to: `hotel_node` · `itinerary_node` · `booking_node` · `qa_node` · `respond`. LLM calls: 0-1 lần (`get_fast_llm`, temp 0) — chỉ ~10% turn.

---

## Slide 23 — Node 09: `hotel_node()` làm gì?

**File:** `nodes/hotel_node.py:215-521`

**Đáp:** Áp `hotel_preferences` làm bộ lọc cứng cấp app qua `select_hotel_candidates()`. Khi user chọn khách sạn (`selected_hotel_id`), gọi `build_selected_hotel_trip` — dựng cả khách sạn **và** itinerary trong một lần.

- Khóa tuyệt đối: từ chối đụng vào `trip_data` nếu session đã có booking đã thanh toán.
- Có thể `interrupt()` một lần để hỏi tâm điểm tìm kiếm bán kính khi không tự resolve được.
- Chấm điểm/xếp hạng là Python thuần — xem [Slide 31](#slide-31--công-thức-chấm-điểm-khách-sạn-là-gì).
- Routes to: `budget_check` (hết task) · `supervisor` (còn task). LLM calls: 0 trực tiếp trong node này.

---

## Slide 24 — Node 10: `itinerary_node()` làm gì?

**File:** `nodes/itinerary_node.py:393-701`

**Đáp:** Trình **chỉnh sửa** itinerary, không phải trình dựng — mọi action cần `trip_data` đã tồn tại (chỉ `hotel_node` tạo ra nó). Đọc action từ `task_description` JSON: `rebuild_days`, `edit_item`, `lock_days`, `list_nearby`.

- `rebuild_days` lặp qua subgraph `rebuild_day` cho từng ngày, tự re-queue vào `pending_tasks`.
- `edit_item` dùng bộ 9-operation `trip_edit_planner` có sẵn.
- `list_nearby` chỉ đọc — không đụng `trip_data`.
- Routes to: `respond` · `budget_check` · `supervisor` (loop). LLM calls: 1 lần sinh day-theme — **chỉ khi Tier 1 Cache miss**.

---

## Slide 25 — Node 11: `booking_node()` làm gì? (xem thêm [Slide 38](#slide-38--vì-sao-giữ-booking_node-trong-graph-nếu-nó-luôn-từ-chối))

**File:** `nodes/booking_node.py:35-42`

**Đáp:** **Luôn từ chối** — `_IMPOSSIBLE=True` cứng, supervisor không bao giờ thật sự delegate vào đây. Tồn tại để turn có ý định đặt phòng nhận phản hồi trung thực thay vì rơi vào ack chung chung.

- Quan trọng, cần phân biệt rõ: đặt phòng & thanh toán VNPay **thật sự tồn tại và hoạt động** (`booking_service.py`, `payment_service.py`, `vnpay_service.py`) — nhưng đi qua REST route riêng (`api/routes.py`), **không** qua chat agent này. Chat agent không thể tự đặt phòng.
- Routes to: `budget_check` (ngay lập tức). LLM calls: không có.

---

## Slide 26 — Node 12: `qa_node()` làm gì?

**File:** `nodes/qa_node.py:186-195`

**Đáp:** Không phải hàm thường — là 1 subgraph `create_react_agent` (ReAct loop). Read-only theo **cấu trúc**: schema `QAState` chỉ mở rộng field đọc — `travel_state`/`pending_tasks`/`task_results` không thể chạm tới, không chỉ là quy ước.

- Tools: `get_hotel_options`, `get_trip_plan`, `query_hotel`, `query_hotel_rooms`, `search_places`.
- `pre_model_hook` cắt transcript về ngân sách **30.000 token** trước mỗi lời gọi LLM trong loop.
- Routes to: `respond` (luôn luôn, edge thường). LLM calls: N lần thay đổi — giới hạn bởi token budget, không giới hạn số lượt.

---

## Slide 27 — Node 13: `budget_check()` làm gì?

**File:** `nodes/budget_check.py:307-457`

**Đáp:** Python thuần, 0 LLM. Pass-through nếu `budget.trip_total` chưa set. Nếu vượt ngân sách: suy ra trần giá khách sạn/đêm từ phần còn lại sau khi trừ chi phí hoạt động, chạy **đúng 1 lần** re-plan.

- Re-plan: tìm lại khách sạn dưới trần giá (loại khách sạn hiện tại), rebuild chỉ những ngày chưa khóa.
- Không bao giờ lặp tối ưu vô hạn — đúng 1 pass.
- Không bao giờ âm thầm trả về plan vượt ngân sách mà không báo cho user.
- Routes to: `respond` (luôn luôn). LLM calls: không có.

---

## Slide 28 — Node 14: `respond()` làm gì?

**File:** `nodes/respond.py:284-381`

**Đáp:** Mọi nhánh của graph đều chảy qua đây trước END. Dựng câu trả lời theo thứ tự ưu tiên cố định, rồi gói toàn bộ `PlannerChatResponse` gửi về frontend.

Thứ tự ưu tiên câu trả lời:
1. Câu hỏi `intake_qa` + câu hỏi `ask_slot` (ghép lại).
2. `task_results[-1]["reply"]` gần nhất.
3. Tin nhắn AI chưa tiêu thụ trong `messages` (từ `qa_node`).
4. Ack chung "Đã cập nhật thông tin chuyến đi." — log ở mức **ERROR** như lưới an toàn phát hiện bug.

Routes to: `END`. LLM calls: không có.

---

## Slide 29 — Đang dùng model AI nào? So sánh ra sao?

**Đáp:** Cấu hình đang chạy thật (`backend/.env`, không phải ví dụ trong README):

| Vai trò | Model | Env var | Dùng ở |
|---|---|---|---|
| Reasoning LLM | **GPT-5.1** | `LLM_MODEL=gpt-5.1-2025-11-13` | `extract_patch`, sinh day-theme khi cache miss |
| Fast LLM | **GPT-4o-mini** | `LLM_FAST_MODEL=gpt-4o-mini` | `supervisor`, `intake_qa`, `qa_node` (ReAct) |
| Embeddings | **BGE-M3** | `EMBEDDING_MODEL=@cf/baai/bge-m3` | Qua Cloudflare Workers AI — 1024-d, RAG + Tier 1 Cache |

- **Bằng chứng tuning thật:** mặc định `reasoning_effort="low"` cho họ model reasoning (gpt-5.1 nằm trong họ này) sau khi đo được mức "medium" mặc định của OpenAI tốn **76 giây / 1536 token reasoning ẩn** — 89% tổng 119s — chỉ để trả lời 1 câu hỏi năng lực đơn giản trong `qa_node` (`config.py:30-39`).
- Factory hỗ trợ **6 provider**: Ollama (fallback tự động), OpenAI (đang dùng), Google Gemini, Anthropic, OpenRouter, Cloudflare (đang dùng cho embeddings). Đổi provider chỉ bằng biến môi trường, không đổi code. Ollama tự động là lưới an toàn khi provider chính lỗi.

---

## Slide 30 — Vì sao chọn BGE-M3 cho embedding?

**Đáp:** `EMBEDDING_MODEL=@cf/baai/bge-m3` qua Cloudflare Workers AI, 1024-d.

- **Đa ngôn ngữ Việt/Anh:** BGE-M3 huấn luyện đa ngôn ngữ (100+), phù hợp truy vấn du lịch song ngữ mà không cần dịch trước.
- **Khớp sẵn schema 1024-d:** `EMBEDDING_DIMENSION=1024` bị ép cứng trong code (`itinerary_reuse.py`) — ghi vector sai chiều sẽ raise lỗi ngay.
- **Không khóa 1 nhà cung cấp:** cùng model bge-m3 chạy được qua Ollama (local), Cloudflare Workers AI, hoặc OpenRouter — đổi hạ tầng mà không cần re-embed.

So sánh nhanh:

| Model | Đa ngôn ngữ VN | Chiều vector | Chi phí | Tự host được | Khớp schema hiện tại |
|---|---|---|---|---|---|
| **BGE-M3 (đang dùng)** | Mạnh | 1024 | Free tier / miễn phí | Có | ✓ Khớp sẵn |
| OpenAI text-embedding-3-small | Khá, thiên tiếng Anh | 1536 | Trả phí/token | Không | ✗ Cần re-embed |
| Google text-embedding-004 | Khá | 768 | Trả phí/token | Không | ✗ Cần re-embed |
| Cohere embed-multilingual-v3 | Mạnh | 1024 | Trả phí/token | Không | Dim khớp nhưng vector space khác → vẫn cần re-embed |

Lưu ý: đổi model embedding không chỉ là đổi API key — mọi vector đã lưu (hotel, attraction, lịch trình đã cache) phải re-embed lại vì vector space không tương thích giữa các model.

---

## Slide 31 — Công thức chấm điểm khách sạn là gì?

**File:** `services/hotel_selection.py`

**Đáp:** 3 giai đoạn:
1. **Lọc cứng** — giá (RPC), rating, amenities, review, số khách — không bao giờ là điểm cộng mềm.
2. **Semantic search** — bge-m3 embed → Supabase RPC `match_hotels_with_rooms`, ngưỡng 0.35.
3. **Chấm điểm mềm** — 2 công thức song song, độc lập nhau.

**`_composite_score`** (dùng để **SẮP XẾP**, ra `recommendation_score`):
- Similarity 0.55 · Rating 0.20 · Review score 0.15 · Price fit 0.10
- \+ `budget_bonus` (≤0.05, decay tuyến tính quanh giá mục tiêu) + `amenity_bonus` (0.03/tag khớp, cộng dồn tối đa 0.20)

⚠ **`match_score`** (hiển thị cho user) dùng công thức **KHÁC** hoàn toàn: `_realistic_match_score` = 0.4×star + 0.6×review, trộn thêm price/amenity fit — độc lập hoàn toàn với điểm sắp xếp ở trên, dễ gây nhầm khi debug thứ hạng.

---

## Slide 32 — Thuật toán lập lịch trình hoạt động thế nào? (xem thêm [Slide 39](#slide-39--sao-dùng-greedy-heuristic-thay-vì-csp--ilp-solver))

**File:** `services/trip_scheduler.py` (1458 dòng, hàm thuần Python) — **greedy theo khung giờ cố định**. KHÔNG phải constraint solver, KHÔNG phải TSP cổ điển.

**8 khung giờ cố định/ngày:** 07:00 Breakfast → ~08:15 Sáng → 11:00-12:30 Lunch → 13:00 Nghỉ KS (90p) → ~15:30 Chiều → ~17:45 Coffee → ~18:45 Dinner → ≤20:30 Tối (tùy chọn).

**Scoring — có điểm neo:**
- similarity 0.45 · dist→anchor 0.35 · dist→hotel 0.10 · rating 0.10
- − 0.55 × phạt đường vòng (detour/route_limit)

**Gom cụm bán kính:** 5km → 10km → 15km, nới dần chỉ khi bán kính chặt hơn ra 0 kết quả. Khoảng cách Haversine thẳng (không phải ETA routing thật) — thời gian di chuyển = distance/25km/h, làm tròn lên 5 phút, sàn 10 phút.

- **Meal/rest insertion:** bữa ăn bị hotel-covered → thay bằng item tại khách sạn. Đúng 1 block nghỉ 90 phút lúc 13:00/ngày.
- **Repair pass:** `validate_or_repair_day` — gỡ trùng nghỉ, ép ≤1 điểm thiên nhiên/ngày, đẩy hoạt động biển khỏi giữa trưa.

---

## Slide 33 — Tier 1 Cache hoạt động chi tiết thế nào?

**Đáp:**
- Ngưỡng: `ITINERARY_REUSE_TIER1_THRESHOLD` (`trip_planner.py:69`), mặc định **0.88**, override được qua env.
- Fingerprint: ghép text (destination, duration, adults/children, sở thích đã sort, planning_constraints canonical JSON) → embed bge-m3 (1024-d) → gửi qua Supabase RPC `match_itineraries`.
- **Lọc cứng TRƯỚC similarity:** destination_id · duration_days · hotel_id (bắt buộc) · planning_constraints — phải khớp **chính xác** mới xét đến % tương đồng.

**`classify_reuse_candidate()` — 7 bước kiểm tra bảo thủ theo thứ tự:** Destination khớp → Hotel khớp → Duration khớp → Constraints khớp → Status Finalized → Similarity ≥ 0.88 → Bundle hợp lệ (≥7 item/ngày).

- **HIT:** rebuild itinerary quanh khách sạn hiện tại, dùng lại `day_themes` cũ — không copy y nguyên.
- **MISS:** rơi xuống pipeline sinh theme bằng LLM (gpt-5.1) + scheduler bình thường.

---

## Slide 34 — Pipeline tìm kiếm ngữ nghĩa (RAG) hoạt động thế nào?

**Đáp:** Embedding lưu & query hoàn toàn trên Supabase pgvector — **không hybrid keyword/BM25, không reranker model**.

1. **Trích filter** (tùy chọn) — LLM đọc category/giá/rating từ câu hỏi tự do.
2. **Embed** — bge-m3 → vector 1024-d.
3. **pgvector RPC** — cosine similarity, ngưỡng 0.35 (hotel) / 0.40 (attraction).
4. **Lọc + degrade** — 0 kết quả sau lọc chặt → trả về kết quả chưa lọc, không bao giờ rỗng.
5. **Hydrate** — query lần 2 lấy đầy đủ field canonical theo ID đã match.

**Biến thể tiered** (dùng cho `trip_scheduler`): 3km/0.40 → 3km/0.25 → 8km/0.40 → 12km/0.25 — mở rộng dần từng tier, dừng ngay khi đủ số lượng ứng viên cần.

---

## Slide 35 — Session & state được quản lý thế nào?

**Đáp:**
- TTL SessionRegistry: **2h**. Cap session/process: **200**. Uvicorn worker: **1** (in-memory).

**Chuỗi khôi phục session (`SessionRegistry.get`):** 1. In-memory dict → 2. Supabase `sessions` row → 3. Hỏi thẳng checkpointer.

- **`TravelGraphState`:** state thật của LangGraph mỗi turn: `messages`, `travel_state`, patch fields, `pending_tasks`/`task_results`. `trip_data` cố tình để **NGOÀI** `travel_state` — round-trip dict sẽ âm thầm drop field lạ.
- **Checkpointer:** mặc định `memory`; production dùng `PostgresSaver`. CLI/script **luôn** dùng `MemorySaver` bất kể config.

---

## Slide 36 — Ước tính chi phí & token? (xem thêm [Slide 40](#slide-40--tier-1-cache-hit-rate-thật-chi-phí-llm--lịch-trình-là-bao-nhiêu))

**Sự thật trước tiên:** không có token counting hay cost tracking nào được đo đạc trong code hiện tại (đã tìm khắp `backend/`, `eval/`, `docs/`).

**Tần suất gọi LLM theo node/turn (đếm từ code):**
- `extract_patch`: 100% turn · reasoning
- itinerary theme: chỉ khi cache miss (~30%) · reasoning
- `intake_qa`: có điều kiện (~15%) · fast
- `supervisor`: ~10% turn · fast
- `qa_node`: N lần, trần 30.000 token · fast

**0 LLM call (Python thuần):** `load_context`, `scope_guard`, `validate_patch`, `apply_patch`, `ask_slot`, `hotel_node` (scoring), `booking_node`, `budget_check`, `respond`.

**Con số thật duy nhất trong code:** `qa_context_token_budget` = **30.000 token**/lời gọi (`config.py`).

**Chưa đo — ước tính định tính:** model thật đang chạy là gpt-5.1 (reasoning, đắt hơn/token) cho `extract_patch` & sinh theme; gpt-4o-mini (fast, rẻ hơn) cho `supervisor`/`intake_qa`/`qa_node`. Muốn số $ chính xác cần bật đo token thật, không suy đoán từ giá công khai.

---

## Slide 37 — Giá phòng đổi giữa lúc khách thanh toán thì sao?

**Đáp:**

**Đã có:**
- Đối soát số tiền VNPay thật — làm tròn giá phòng trung bình về VND nguyên, tránh lệch `vnp_Amount` (fix đã merge).
- Trạng thái **CANCELLED** rõ ràng khi VNPay timeout — khách không bao giờ "treo" không biết kết quả.

**Chưa có (trung thực):**
- Không tìm thấy re-check tồn phòng real-time ngay trước khi tạo booking (đã tìm `booking_service.py`).
- Chưa có khóa tồn kho (inventory lock) giữ chỗ trong lúc khách điền thanh toán.

**Kết luận:** đây là khoảng cách thật, không phải điểm yếu che giấu — đối soát số tiền & xử lý timeout đã production-ready; giữ chỗ real-time là hạng mục roadmap tiếp theo.

---

## Slide 38 — Vì sao giữ `booking_node` trong graph nếu nó luôn từ chối?

**Đáp:** Trích docstring thật của node (`booking_node.py`):

> "plan.md defers booking entirely: no auth model, no inventory source. But the supervisor needs a routable destination for a booking request, or such a turn would silently fall to respond with nothing said — the exact silent no-op this whole plan exists to eliminate."

**3 lý do giữ trong graph:**
1. Tránh **silent no-op** — turn "đặt phòng giúp mình" phải luôn nhận phản hồi trung thực, không rơi vào ack chung chung.
2. Đồng nhất framework: mọi worker đi qua cùng `pending_tasks` → `budget_check` → `respond`, không cần đường tắt riêng ở gateway.
3. Scaffolding sẵn cho Phase 6: khi có intent-classification thật, chỉ cần đổi `_IMPOSSIBLE["booking_node"]`, không phải viết lại routing.

**Vì sao không định tuyến ở API gateway?** Sẽ tách rời logic "đặt phòng" khỏi vòng đời turn thống nhất — nghĩa là 2 hệ thống lỗi/log riêng biệt cho cùng 1 ý định người dùng.

---

## Slide 39 — Sao dùng greedy heuristic thay vì CSP / ILP solver?

**Đáp:** (Lý do kỹ thuật suy ra từ hành vi hệ thống — không phải trích tài liệu thiết kế có sẵn)

- **Độ trễ hội thoại:** chat cần phản hồi trong vài giây. ILP với ràng buộc mềm (giờ mở cửa, sở thích, khoảng cách, ngân sách) có thể mất nhiều giây–phút để hội tụ tối ưu toàn cục.
- **Lịch trình luôn bị sửa lại:** khách chỉnh sửa liên tục (`edit_item`, `rebuild_days`) — tối ưu toàn cục 1 lần kém giá trị hơn khả năng sửa nhanh + repair pass cục bộ.
- **Ràng buộc thực tế khó mô hình hóa:** giờ mở cửa động, bữa ăn đã gồm trong khách sạn, tránh biển giữa trưa... là domain rule — biểu diễn trong ILP sẽ nổ số biến nhanh chóng.
- **Giải thích được cho khách:** mỗi lựa chọn log lý do cụ thể (`adjustments`) — nghiệm ILP dạng "hộp đen" khó trả lời "vì sao lịch trình lại như vậy".

---

## Slide 40 — Tier 1 Cache hit rate thật? Chi phí LLM/lịch trình là bao nhiêu?

**Trung thực:** chưa có dashboard % hit rate hay $ cost — nhưng dữ liệu thô đã tồn tại, chỉ thiếu lớp tổng hợp.

**Đã log mỗi lần:**
- `reuse_miss reason=no_qualified_candidate` — log mỗi lần cache miss.
- `reuse_rejected template=... reason=...` — log lý do từ chối từng template ứng viên.

**Cần thêm để có con số thật:**
- Tổng hợp log hit/miss thành metric % theo thời gian (chưa có dashboard).
- Bật token counting thật cho gpt-5.1/gpt-4o-mini theo từng lời gọi (chưa instrument).

**Kết luận:** đây là việc thêm 1 lớp aggregation, không phải xây lại từ đầu — hạ tầng log đã sẵn sàng để nối vào.

---

## Slide 41 — Luồng đặt phòng & thanh toán VNPay hoạt động thế nào?

**File:** `use-room-hold.ts` · `routes.py` · `vnpay_service.py`

1. **Chọn phòng & giữ chỗ** — RPC khoá theo `room_id + guest_ref`, TTL 15 phút.
2. **Đếm ngược** — đọc lại `expires_at` từ server mỗi giây.
3. **Nhập thông tin khách** — tên, email, số điện thoại.
4. **Tạo giao dịch VNPay** — ký URL HMAC-SHA512, rời hẳn SPA.
5. **2 kênh xác nhận song song** — chỉ 1 trong 2 đáng tin:
   - **IPN (server-to-server):** xác minh chữ ký + đối chiếu số tiền → `UPDATE ... WHERE status='PENDING'` (chính câu lệnh này LÀ cơ chế idempotent) → xác nhận booking → gửi email. Đây là **nguồn xác nhận duy nhất đáng tin**.
   - **Redirect (hiển thị):** query string có thể bị sửa, không được tin. SPA tải lại toàn bộ, poll `GET /payments/{id}` tối đa ~20s để hiện màn kết quả.

---

## Slide 42 — Giữ phòng (room hold): quyết định thiết kế & rủi ro là gì?

**File:** `use-room-hold.ts` — state toàn cục theo tab, không theo session.

- **Không có cron dọn dẹp:** hold hết hạn chỉ đơn giản ngừng được tính vào "phòng đang giữ" (`expires_at > now()` trong truy vấn còn phòng) — chỉ thật sự đổi `status→EXPIRED` khi có ai cố `confirm` nó.
- **`roomHold` là state TOÀN CỤC:** không theo từng đoạn chat — quyết định có chủ đích. Gốc rễ của nhiều bản vá sau này: đổi khách sạn, xoá session đang giữ, hiển thị nhầm hold của đoạn chat khác.
- **Chỉ giữ 1 khách sạn 1 lúc:** khoá advisory theo `guest_ref` (không chỉ `room_id`) chặn ở tầng DB — không phụ thuộc frontend kiểm tra đúng hay không.
- **`switchHold` luôn huỷ rồi tạo lại:** không có API "sửa" hold — đổi loại phòng hay đổi khách sạn đều release toàn bộ + reserve lại, TTL 15 phút mới tinh.

⚠ **Sự cố thật đã gặp:** thanh toán VNPay thật thành công nhưng app từng kẹt "đang chờ xác nhận" — do tính giá trung bình ra số lẻ `float`, lệch với số VND nguyên VNPay trả về trong IPN → `RspCode 04 "Invalid amount"`. Đã sửa bằng `Decimal` + làm tròn VND nguyên, dung sai <1 VND khi so khớp — đã xác nhận chạy đúng trên staging thật.

---

*Nguồn: trích xuất từ `docs/slide/index.html` (slide 13–42, phần "Phụ lục kỹ thuật" / "Phụ lục · Q&A" / "Phụ lục · Câu hỏi dự kiến"). Cập nhật file này nếu nội dung slide thay đổi.*
