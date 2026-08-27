# Eval Harness — Hướng dẫn kiểm thử

`eval/` chấm điểm chất lượng RAG của backend bằng RAGAS, 2 layer độc lập:
Layer 1 (retrieval) và Layer 2 (e2e conversation). Bối cảnh đầy đủ:
[`plans/260820-1106-eval-harness-graph-cutover-restore/plan.md`](../../plans/260820-1106-eval-harness-graph-cutover-restore/plan.md).

## 1. Embedding provider: vì sao Layer 1 dùng Ollama chứ không phải Cloudflare

`backend/.env` khai báo:

```
EMBEDDING_PROVIDER=cloudflare
EMBEDDING_MODEL=@cf/baai/bge-m3
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...
OLLAMA_URL=http://localhost:11434
```

Nhưng thực tế chạy, `get_embeddings()` (`backend/src/services/llm.py:447`) trả về
`OllamaEmbeddings`, không phải Cloudflare. Đã xác minh nguyên nhân (không phải bug code):

- Máy này có biến shell **`EMBEDDING_PROVIDER=ollama`** export sẵn ở tầng OS
  (`env | grep EMBEDDING_PROVIDER` → `ollama`).
- `pydantic-settings` (`backend/src/config.py`) mặc định ưu tiên **biến môi
  trường OS** hơn giá trị trong file `.env` — đây là hành vi chuẩn của
  pydantic-settings, không phải lỗi.
- Vậy `EMBEDDING_PROVIDER=ollama` ở shell đè lên `cloudflare` trong
  `backend/.env` mỗi lần chạy.

**Kết quả thực tế:** Layer 1 cần **Ollama chạy local** (`ollama serve`, model
`bge-m3` đã pull sẵn), không cần Cloudflare token/account ID hoạt động — dù
`.env` viết là `cloudflare`. Muốn Layer 1 THẬT SỰ dùng Cloudflare, phải:
```bash
unset EMBEDDING_PROVIDER   # xoá override ở shell, hoặc tìm file profile (~/.zshrc...) đang export nó
```
rồi mới chạy — không sửa gì trong code hay `.env`.

Kiểm tra nhanh embedding provider đang thực sự dùng:
```bash
cd backend && python3 -c "
from src.services.llm import get_embeddings
print(type(get_embeddings()).__name__)"   # OllamaEmbeddings hay OpenAIEmbeddings (cloudflare route)
```

## 2. Golden dataset — 2 file, 2 mục đích khác nhau

| File | Layer | Số record | Dùng để |
|---|---|---|---|
| `eval/datasets/golden-retrieval.jsonl` | 1 (retrieval) | 44 | Chấm search trả đúng chỗ chưa |
| `eval/datasets/golden-conversations.jsonl` | 2 (e2e) | 10 | Chấm cả cuộc hội thoại qua graph |

### 2.1 `golden-retrieval.jsonl` — schema mỗi record

```json
{
  "id": "hotel-nhatrang-4star-price-vi",
  "search": "hotels",              // "hotels" | "attractions"
  "language": "vi",                // "vi" | "en"
  "pair_id": "hotel-nhatrang-4star-price",  // ghép cặp vi/en cùng ý query
  "query": "khách sạn 4 sao view biển ở Nha Trang dưới 2 triệu",
  "filters": {"destination": "Nha Trang", "min_star_rating": 4, "max_price": 2000000},
  "expected_ids": ["ee40f07a-..."],      // BẮT BUỘC phải xuất hiện trong top-10
  "acceptable_ids": ["a12e4403-...", ...], // OK nếu có, không bắt buộc
  "rationale": "..."                      // tại sao expected/acceptable_ids được chọn (đã adjudicate thủ công 2026-08-10)
}
```

Phân bổ 44 record: **31 hotels / 13 attractions**, **28 vi / 16 en** (nhiều
cặp vi-en cùng ý để so sánh cross-language). Mỗi record test 1 trong các góc:
query mơ hồ không filter, filter giá/sao cụ thể, điểm đến ít dữ liệu (Huế),
điểm đến không hỗ trợ, v.v.

**Cách chấm (`eval/harness/retrieval_eval.py`):**
- Gọi thẳng `search_hotels_with_rooms` / `search_attractions` (hàm production thật, `use_llm_filter=True`).
- **Non-LLM (free, exact ID match):** `non_llm_precision`, `non_llm_recall` — so `retrieved_ids` với `expected_ids`/`acceptable_ids`.
- **LLM-judged (tốn phí, bật bằng `--llm-metrics`):** `llm_precision` (`LLMContextPrecisionWithReference`), `llm_context_relevance` (`ContextRelevance`) — LLM tự đánh giá độ liên quan ngữ nghĩa, không chỉ khớp ID.

### 2.2 `golden-conversations.jsonl` — 10 test case cụ thể

Mỗi record là 1 kịch bản hội thoại nhiều lượt (`turns: [...]`), `expected_stage`
là stage cuối cùng cuộc hội thoại phải đạt được. `__ACTION:select_first_hotel__`
là sentinel giả lập việc bấm chọn khách sạn trên UI (không phải text thật).

| # | id | Test gì | expected_stage |
|---|---|---|---|
| 1 | `conv-nhatrang-couple-3d` | Luồng chuẩn: intake → tìm khách sạn → chọn → dựng lịch trình, kết bằng 1 lượt hỏi về loại phòng (`answer_checks`) | `planned` |
| 2 | `conv-danang-family-3d` | Như #1, gia đình, điểm đến khác, cũng có lượt hỏi cuối (`answer_checks`) | `planned` |
| 3 | `conv-hcm-finalize-4d` | Chọn khách sạn xong rồi gõ "Chốt lịch trình" | `planned` |
| 4 | `conv-hue-finalize-2d` | Chuyến **1 ngày** — sản phẩm chặn vì cần tối thiểu 1 đêm; case kiểm thông báo chặn bằng tiếng Việt | `intake` |
| 5 | `conv-nhatrang-refine-budget` | Chỉnh lại ngân sách giữa chừng | `planned` |
| 6 | `conv-hcm-luxury-en` | Hội thoại tiếng Anh (loại khỏi run mặc định) | `planned` |
| 7 | `conv-nhatrang-attraction-mix` | Hỏi xen kẽ về điểm vui chơi giữa lúc chọn khách sạn | `planned` |
| 8 | `conv-unsupported-destination` | Hỏi "Phú Quốc" — không có trong dữ liệu. Agent phải từ chối và nêu 5 điểm đến có thật, nên dừng ở intake là **đúng** | `intake` |
| 9 | `conv-hcm-district-switch` | Yêu cầu chặt: 4 sao, Quận 1, ~1.8tr; nói "Sài Gòn" thay vì tên chuẩn | `planned` |
| 10 | `conv-hue-thin-corpus-probe` | Huế rất ít resort biệt lập — test agent không bịa khi corpus mỏng | `hotel_options` |

Run mặc định chỉ chạy **9 record tiếng Việt** (#6 bị lọc); `--include-en-mirrors` mới đủ 10.

**Trạng thái 2026-08-20: cả 9/9 đạt đúng `expected_stage`.** Trước đó 4 case fail, và
việc điều tra chúng tìm ra 3 bug sản phẩm thật (thời lượng nói ở lượt trước bị bỏ rơi,
`"N ngày"` hiểu không nhất quán giữa LLM và helper, `"Sài Gòn"` đôi khi không được trích
thành destination) cùng 2 bug harness. Chi tiết adjudication từng record:
[`eval/datasets/README.md`](../../eval/datasets/README.md).

**Cách chấm (`eval/harness/e2e_eval.py`):**
- Mỗi turn chạy qua `turn_runner.run_turn` (graph thật, Supabase thật, KHÔNG ghi vào session store thật — `persist=None`).
- Phân loại turn: `template` (hotel_node — tìm/chọn khách sạn, câu trả lời gần như cố định) / `mixed` (itinerary_node, budget_check, booking_node — vừa số liệu thật vừa văn bản sinh) / `generated` (agent tự hỏi lại, câu hỏi mở).
- `faithfulness`: **metric duy nhất còn dùng LLM judge**, và chỉ chấm ở turn mà quan hệ nó giả định là có thật — luật nằm ở `eval/harness/turn_metrics.py`, khoá bằng `backend/tests/test_eval_turn_metrics.py`:
  - `faithfulness` chỉ cho `hotel_node` và turn không worker (`qa_node`/`intake_qa`) khi có context. **Loại `booking_node`/`budget_check`**: reply của chúng trích số app **tính ra** (tổng tiền, giá trung bình/đêm, phần vượt ngân sách), không context nào chứa số đã tính — chấm ở đó là so hai thứ không liên quan rồi báo lệch thành hallucination. Turn đó cần một phép kiểm số học, không cần judge.
  - **Loại `itinerary_node`, thay bằng kiểm tất định.** Reply của nó là một lịch trình ("Ngày 1: Ăn sáng tại X, Tham quan Y…"), nên gần như mọi mệnh đề RAGAS tách ra đều khẳng định *ngày nào, bữa nào* — trong khi context là danh sách tên địa điểm không mang ngày lẫn bữa. Đo được trên `conv-hcm-finalize-4d`: faithfulness 0.0 trong khi **cả 7 địa điểm được xếp lịch đều có trong context đã truy vấn**. Thay vào đó `turn_metrics.ungrounded_itinerary_places` so khớp chính xác: địa điểm nào trong lịch trình mà không truy vấn nào của hội thoại trả về thì hội thoại **fail hẳn**, không phải bị trừ vài phần trăm. Nếu template lịch trình đổi khiến parser không đọc được, check báo `<unparsed itinerary reply>` thay vì im lặng cho qua.
  - Turn hotel-pick (`__ACTION:select_first_hotel__`) bị loại: input là sentinel, reply là câu xác nhận không có dữ kiện.
- **`response_relevancy` đã bị bỏ hẳn khỏi Layer 2 (2026-08-20, quyết định của chủ dự án).** Nó chấm `cosine(user_input, câu-hỏi-suy-ngược-từ-câu-trả-lời)`, nghĩa là **trả lời càng đầy đủ điểm càng thấp**: liệt kê thêm giá thì câu hỏi sinh ra giàu hơn câu user gõ, cosine tụt. Trần đo được 0.7877, cờ `noncommittal` ép về 0 thất thường (0.632 rồi 0.0 trên hai câu trả lời tương đương nhau), và đúng những lượt nó phủ nay đã có `answer_checks` phủ chính xác hơn mà không cần model nào. **Layer 2 giờ chỉ còn: `faithfulness` + latency + cost, cộng các assertion tất định bên dưới.**
- **Ba bảo đảm an toàn là assertion tất định, không phải điểm số.** Vi phạm thì hội thoại fail hẳn; không sinh ra con số nào trong report, vì một bảo đảm mà báo "0.94" thì đã hỏng rồi.

  | Bảo đảm | Cơ chế |
  |---|---|
  | Không bịa khách sạn (BR-07) | `ungrounded_hotel_ids` — ID trên thẻ ⊆ ID đã truy vấn trong hội thoại |
  | Không bịa địa điểm lịch trình | `ungrounded_itinerary_places` |
  | Trả lời đúng thứ được hỏi | `answer_checks` + `answer_coverage` |

  Lý do BR-07 không giao cho judge, đo được ngày 2026-08-20 trên `conv-hue-thin-corpus-probe`: cả **5 thẻ khớp từng ký tự** với context đã truy vấn, mà Faithfulness vẫn chấm **0.0** — một lời gọi judge hỏng kéo trung bình toàn suite từ ~0.87 xuống 0.78. So khớp ID không thể sai kiểu đó, theo cả hai chiều.
- **`answer_coverage` — thứ thay thế `response_relevancy` ở lượt hỏi-đáp.** Thay vì đi đường vòng qua embedding của câu hỏi suy ngược, nó hỏi thẳng: *người dùng hỏi loại phòng thì câu trả lời có nêu tên phòng có thật không*. Dataset khai **kiểm gì** (`answer_checks: [{"turn": 4, "kind": "lists_rooms_of_selected_hotel"}]`, validate lúc nạp nên `kind` gõ sai hay `turn` vượt phạm vi là lỗi ngay, không phải một check âm thầm không chạy); dữ liệu sản phẩm cung cấp **sự thật** lúc replay (`get_hotel_detail` — đúng hàm mà tool chat và `GET /hotels/{id}` dùng, nên kỳ vọng không thể lệch với thứ người dùng thấy). Không đóng băng danh sách phòng vào `.jsonl`: đổi tên một phòng là eval sẽ báo agent hỏng.
  - **Cổng chặn**: reply không nêu **một** phòng có thật nào → hội thoại fail (câu hỏi coi như không được trả lời).
  - **Số báo cáo**: `answer_coverage` = tỉ lệ phòng được nêu. Không đặt ngưỡng — bỏ qua phòng đã hết chỗ không phải là sai.
  - Khớp tên theo cả hai nửa của tên song ngữ ("Phòng Deluxe Giường Đôi Hướng Phố (Deluxe City View Double Room)"), nên trả lời bằng tiếng Việt vẫn tính là nêu đúng phòng.
- **Không đổi embedding judge sang OpenAI.** Từng định làm, đo xong thì ngược lại: với câu người dùng tiếng Việt, `text-embedding-3-small` chấm câu hỏi tiếng Anh RAGAS sinh ra chỉ **0.4826** so với **0.7283** của bge-m3 (bge-m3 huấn luyện xuyên ngữ, OpenAI thì không). Ghi lại ở `judge.build_judge_embeddings` — embedding giờ chỉ còn `smoke_check.py` dùng, vì Faithfulness thuần văn bản.
- Mỗi trung bình trong `breakdowns` đi kèm `n`: `{"template": {"mean": 0.9048, "n": 1}}`. Vì phần lớn turn bị loại có chủ đích, một trung bình rất dễ chỉ là **một** quan sát — đọc `mean` mà không có `n` là hiểu sai quy mô bằng chứng.
- **Cái được đem đi chấm là "chat text + danh sách thẻ khách sạn", không phải riêng câu chat.** Ở turn `hotel_node`, câu chat chỉ là caption ("Mình tìm được 5 khách sạn phù hợp") còn câu trả lời thật gửi cho người dùng là `hotel_options` (tên, hạng sao, giá/đêm, tổng giá). Chấm mỗi caption thì judge phải xác minh một con số đếm không hề có trong context → luôn ra 0.0 dù agent không bịa, mà sai giá trên thẻ — lỗi đáng bắt nhất — lại không ai nhìn thấy. Xem `context_format.hotel_options_as_answer`; transcript in ra nguyên văn chuỗi đã chấm.
- Vì thế context của Layer 2 render kèm sao/giá (`as_context(..., detail=True)`), dùng chung bộ format số với phía câu trả lời để judge không đọc "950,000 VND" vs "950.000đ" thành hai số khác nhau. Layer 1 vẫn dùng dạng gọn `[id] tên, thành phố` như cũ — mặc định `detail=False`, đổi mặc định là dịch điểm Layer 1 mà không ai sửa gì ở Layer 1. Contract này được khoá bằng `backend/tests/test_eval_context_format.py`.
- **Context đem chấm là tích luỹ theo hội thoại, không phải của riêng lượt đó.** `hotel_node` giữ `previous_options` nên danh sách thẻ trên màn hình cộng dồn qua các lượt, trong khi kết quả RPC của một lượt thì không. Chấm danh sách cộng dồn với context một lượt sẽ báo những khách sạn tìm được ở lượt trước là "không có căn cứ" — đo được 0.42 ở `conv-nhatrang-attraction-mix` lượt 3, nơi 5/10 thẻ đến từ lượt 2 và hoàn toàn có thật. Transcript vẫn in context của riêng lượt (đó là thứ cho biết lượt đó có truy vấn gì không).
- **Giới hạn đã biết — câu trả lời "địa điểm gần đây" của `qa_node` bị chấm thấp oan.** `search_places` lấy hàng gọn từ RPC `match_attractions` (chỉ `id/name/description/category`) rồi hydrate `rating` bằng truy vấn bảng theo ID (`place_search.py:51-68`), mà recorder chỉ bắt `match_*`. Nên khi agent trả lời *"Công Viên Phù Đổng — 4.5★"*, tên thì có căn cứ còn điểm đánh giá thì không có gì đối chiếu: đo được **0.0588** trên một lượt như vậy, dù mọi tên công viên đều lấy từ retrieval. Cùng loại với địa chỉ/khu vực của khách sạn. Muốn phủ thì phải mở rộng recorder sang đường đọc-theo-ID, không phải nới luật chấm.
- Chỉ những trường **đi qua retrieval** mới được render (sao, giá/đêm, tổng giá, số đêm). Địa chỉ/khu vực/tiện ích do app hydrate sau nên không đưa vào cả hai phía: judge không có gì để đối chiếu, mọi câu nhắc tới chúng sẽ bị chấm là "không có căn cứ".

## 3. Cách chạy từng test

```bash
cd <repo-root>          # thư mục gốc repo (chứa backend/, eval/, docs/)

# --- Layer 1: retrieval ---
ollama serve &                          # nếu chưa chạy (bge-m3 cần Ollama, xem mục 1)
eval/.venv-eval/bin/python eval/run_ragas.py --layer retrieval --limit 5 --no-llm-metrics   # nhanh, free
eval/.venv-eval/bin/python eval/run_ragas.py --layer retrieval --no-llm-metrics             # full 44 record, free
eval/.venv-eval/bin/python eval/run_ragas.py --layer retrieval --llm-metrics                # có LLM judge, tốn phí

# --- Layer 2: e2e conversation ---
eval/.venv-eval/bin/python eval/run_ragas.py --layer e2e --limit 1 --no-llm-metrics   # 1 hội thoại, free, xem stage có đúng không
eval/.venv-eval/bin/python eval/run_ragas.py --layer e2e --no-llm-metrics             # full 10 hội thoại, free
eval/.venv-eval/bin/python eval/run_ragas.py --layer e2e --limit 1 --llm-metrics      # 1 hội thoại có chấm điểm LLM thật

# --- Cả 2 layer cùng lúc ---
eval/.venv-eval/bin/python eval/run_ragas.py --llm-metrics   # ~15-20 phút, tốn phí, đây là baseline run chính thức
```

Kết quả: `eval/results/ragas-<timestamp>.json` (số liệu tổng hợp) +
`eval/results/transcripts/<conv-id>.md` (đọc lại từng lượt hội thoại — chỗ
tốt nhất để hiểu "vì sao stage không đúng").

### Backend pytest liên quan trực tiếp tới eval harness

```bash
cd backend
python3 -m pytest tests/test_eval_harness_imports.py -v      # eval/harness/*.py còn import được không (skip nếu máy không có ragas)
python3 -m pytest tests/test_rpc_call_sites_known.py -v       # có RPC Supabase nào mới chưa được context_recorder.py nhận diện không
```
