# Spike: đo reasoning summary thật

Ngày: 2026-08-18 · Plan: `260818-0924-deepdive-thinking-loader` Phase 1
Script: `backend/scripts/spike_reasoning_summary.py`

## Kết luận ngắn

**Reasoning summary hoạt động trên cả hai model — nhưng độ phủ không dự đoán được.**
Summary chỉ xuất hiện khi model thực sự suy luận. Với prompt lập lịch trình thông thường,
`gpt-5.1` nhảy thẳng vào viết (TTFT 2.8s) nên không có gì để tóm tắt; với prompt khó thì
nó phát summary đầy đủ. Một thành phần UI phải luôn có nội dung thì không dựa được vào
nguồn lúc có lúc không.

→ **Dự án chuyển sang tường thuật từ dữ kiện thật của graph** (quyết định 2026-08-18).
Xem plan `260818-0924-deepdive-thinking-loader`.

Phát hiện tốt ngoài dự kiến: bật reasoning **không làm chậm**, và làm **thời gian tới nội
dung đầu tiên giảm 17.6s → 1.0s** — hữu ích để tham khảo nếu sau này quay lại hướng này.

> **ĐÍNH CHÍNH 2026-08-18.** Bản đầu của báo cáo này kết luận "`gpt-5.1` gần như không trả
> summary" và dùng đó làm lý do thu hẹp phạm vi. **Kết luận đó sai.** Phép đo chỉ dùng một
> prompt lập lịch trình, và bỏ sót việc `gpt-5.1` đơn giản là không suy luận trên prompt đó.
> Đo lại với prompt cần suy luận thật (bài xác suất) cho **59 block non-empty**, stream
> từng token, cùng hình dạng với `gpt-5-mini`. Mục 2 đã được sửa.

## 1. Ma trận đo — `gpt-5-mini-2025-08-07`

Model của `get_fast_llm` → `qa_node`, `intake_qa`, `supervisor`.

| effort | mode | blocks | reasoning ký tự | text ký tự | TTFT | tổng |
|---|---|---|---|---|---|---|
| low | baseline | 0 | 0 | 2225 | 15.9s | 23.0s |
| low | **reasoning** | 76 | 405 | 2424 | **4.5s** | 20.3s |
| medium | baseline | 0 | 0 | 2246 | 17.6s | 27.1s |
| medium | **reasoning** | 406 | 2086 | 2306 | **1.0s** | 31.1s |
| high | baseline | 0 | 0 | 1804 | 72.7s | 82.7s |
| high | **reasoning** | 470 | 2161 | 1251 | **1.1s** | 50.0s |
| medium | reasoning+épVI | 601 | 2822 | 2484 | 1.2s | 22.2s |

## 2. Ma trận đo — `gpt-5.1-2025-11-13`

Model của `get_reasoning_llm`/`get_llm` → `extract_patch`, `trip_planner`, `trip_edit_planner`.

| effort | mode | blocks | reasoning ký tự | text ký tự | TTFT | tổng |
|---|---|---|---|---|---|---|
Tất cả các dòng dưới đây dùng **prompt lập lịch trình Đà Nẵng**:

| effort | mode | blocks | reasoning ký tự | text ký tự | TTFT | tổng |
|---|---|---|---|---|---|---|
| low | baseline | 0 | 0 | 6208 | 2.8s | 19.8s |
| low | reasoning | 0 | 0 | 4114 | 5.6s | 23.3s |
| medium | baseline | 0 | 0 | 4896 | 15.9s | 29.4s |
| medium | reasoning | 0 | 0 | 2778 | 10.4s | 27.0s |

Với `summary` khác, vẫn prompt lịch trình: `detailed` → 0 block; `concise` → 2 block chỉ có
tiêu đề (`**Planning Da Nang itinerary**`), không thân đoạn.

**Nhưng với prompt cần suy luận thật** (bài xác suất tổ hợp), cùng `summary: "auto"`,
`effort: medium`:

| prompt | block non-text | block có `summary.text` |
|---|---|---|
| lập lịch trình Đà Nẵng | — | **0** |
| xác suất tổ hợp | 61 | **59** |

Mẫu thô, stream từng token, hình dạng giống hệt `gpt-5-mini`:

```json
{"summary":[{"index":0,"type":"summary_text","text":"**Calculating probabilities**\n\nI"}],"type":"reasoning"}
{"summary":[{"index":0,"type":"summary_text","text":" need"}],"type":"reasoning"}
```

→ **`gpt-5.1` hỗ trợ summary đầy đủ.** Nó không phát gì trên prompt lịch trình vì nó không
suy luận trên prompt đó — bằng chứng nằm ngay trong bảng trên: TTFT 2.8s ở `low` (bắt đầu
viết gần như tức thì) và 6208 ký tự output, so với `gpt-5-mini` cần 15.9s và chỉ viết 2225
ký tự. Model mạnh hơn nhảy thẳng vào viết; model yếu hơn phải nghĩ.

## 3. Trả lời 5 câu hỏi của Phase 1

### Q1 — Summary có ra chữ không?
**Có, trên `gpt-5-mini`.** Ở `medium` cho ~2086 ký tự chia thành 406 chunk streaming — đúng
dạng đoạn văn chạy dần như ảnh mẫu. Ở `low` chỉ 405 ký tự, quá mỏng để lấp một khối UI.

**Có, trên `gpt-5.1` — nhưng chỉ khi prompt đủ khó.** Rỗng trên prompt lịch trình, đầy đủ
trên prompt xác suất. Xem mục 2. Đây là giới hạn quyết định: **độ phủ phụ thuộc độ khó của
câu hỏi, không dự đoán trước được.**

**Khuyến nghị effort: `medium`.** `high` không cho thêm nội dung đáng kể (2161 vs 2086 ký tự)
nhưng cắt mất text trả lời (1251 vs 2306) và tổng thời gian tệ hơn nhiều.

### Q2 — Ngôn ngữ?
**Tiếng Anh, trong mọi trường hợp.** Kể cả khi system prompt là tiếng Việt, câu hỏi người
dùng là tiếng Việt, và có chỉ dẫn tường minh *"toàn bộ quá trình suy luận nội bộ của bạn
phải viết bằng tiếng Việt"*.

Mẫu thực tế với chỉ dẫn ép tiếng Việt:

> **Creating a budget for Da Nang trip**
> I'm looking at a budget for a 3-day, 2-night trip to Da Nang. The major costs will include
> transport, accommodation, food, local transport, attractions, and extras…

→ **Prompt không kiểm soát được ngôn ngữ summary.** Quyết định "ép tiếng Việt qua prompt"
không khả thi. Theo đúng điều đã ghi trong Phase 4 bước 8: hiện tiếng Anh, ghi giới hạn,
không leo thang sang lớp dịch.

### Q3 — Latency tăng bao nhiêu?
**Không tăng — phần lớn còn giảm.** Đây là kết quả ngược với giả định của cả plan.

| effort | tổng baseline → reasoning | TTFT baseline → reasoning |
|---|---|---|
| low | 23.0s → 20.3s (**-2.7s**) | 15.9s → 4.5s (**-11.4s**) |
| medium | 27.1s → 31.1s (+4.0s) | 17.6s → 1.0s (**-16.6s**) |
| high | 82.7s → 50.0s (**-32.7s**) | 72.7s → 1.1s (**-71.6s**) |

Lý do: ở chế độ baseline, model suy luận ẩn xong hết mới bắt đầu phát chữ — người dùng
nhìn 3 chấm suốt 17.6s. Khi bật summary, phần suy luận **chính là** thứ được stream ra
ngay, nên có nội dung sau 1.0s.

**Đánh đổi latency mà bạn đã chấp nhận gần như không xảy ra.** Chi phí token suy luận vẫn
tồn tại như trước (nó vốn đã được tính tiền dù bị ẩn); cái thêm vào chỉ là token của bản
tóm tắt.

### Q4 — Hình dạng `content`?
**Là `list`, không phải `str`.** Xác nhận dự đoán: guard `isinstance(content, str)` ở
`routes.py:548` sẽ thành `False` và nuốt sạch `delta`.

`.content` thô mang hình dạng OpenAI:
```json
{"type": "reasoning", "index": 0,
 "summary": [{"index": 0, "type": "summary_text", "text": " starting"}]}
```

`.content_blocks` của LangChain chuẩn hoá lại:
```json
{"type": "reasoning", "index": "lc_rs_305f30", "reasoning": " starting"}
```

→ **Phase 3 dùng `.content_blocks`**, không parse `.content` thô. Mẫu code trong Phase 3
đang đúng khoá (`block.get("reasoning")`) nhưng phải đọc từ `content_blocks`.

### Q5 — Tool-calling còn sống không?
**Còn.** `bind_tools` qua Responses API gọi tool bình thường trên `gpt-5-mini`
(`OK — gọi 1 tool: ['recommend_hotels']`). Rủi ro "Cao" số 2 trong plan bị loại bỏ.

## 4. Hai phát hiện ngoài phạm vi

### 4.1 `gpt-4o-mini` từ chối cả hai tham số
```
BadRequestError 400: Unsupported parameter: 'reasoning.effort' is not supported with this model.
```
Cả `reasoning` **và** `reasoning_effort` đều bị từ chối. Khẳng định guard model-family trong
Phase 2 là bắt buộc, không phải phòng xa.

### 4.2 Hai file `.env` khai `LLM_MODEL` khác nhau — nhưng backend không bị ảnh hưởng
- `.env:71` (gốc repo) → `LLM_MODEL=gpt-4o-mini`
- `backend/.env:69` → `LLM_MODEL=gpt-5.1-2025-11-13`

`llm.py:108-112` đọc `os.environ.get("LLM_MODEL")` **trước** settings, nên biến nào có mặt
lúc khởi động sẽ thắng. Trong shell tương tác, root `.env` thắng — spike phải chạy
`env -u LLM_MODEL` mới đo được gpt-5.1.

**Nhưng backend thật không bị ảnh hưởng:** `docker-compose.yml:18-19` cho service `backend`
chỉ `env_file: ./backend/.env`. Root `.env` phục vụ frontend build (`VITE_MAPBOX_TOKEN`,
`docker-compose.yml:39`). Backend luôn chạy `gpt-5.1`. Không có bug cấu hình — chỉ là bẫy
cho ai chạy script tay từ shell.

## 5. Ảnh hưởng lên plan

| Mục | Trước spike | Sau spike |
|---|---|---|
| Effort | chưa biết | **`medium`** |
| Ngôn ngữ | ép tiếng Việt qua prompt | **không khả thi — tiếng Anh** |
| Latency | chấp nhận tăng | **không tăng; TTFT giảm mạnh** |
| Rủi ro tool-call | Cao | **loại bỏ** |
| Rủi ro guard `isinstance` | Cao | **xác nhận có thật** |
| Độ phủ reasoning | giả định đều | **phụ thuộc độ khó prompt, không dự đoán được** |

### Vì sao dự án chuyển hướng

Reasoning summary chạy được trên cả hai model, nhưng chỉ xuất hiện khi model thấy câu hỏi
đủ khó. Cùng một bước "Dựng lịch trình" có thể cho 2000 ký tự với yêu cầu phức tạp và rỗng
hoàn toàn với yêu cầu đơn giản. Một khối UI phải luôn có nội dung thì không dựa được vào
nguồn như vậy.

Thêm vào đó, bước gọi tool (`hotel_search`) về bản chất không có suy luận LLM nào để tóm tắt
— nó sẽ luôn rỗng, không phụ thuộc prompt.

Ngược lại, dữ kiện thật của graph thì **luôn có**: `hotel_node` luôn biết nó tìm ở đâu, lọc
theo gì, còn lại bao nhiêu kết quả. Đó là lý do chọn tường thuật từ dữ kiện thay vì reasoning.

## 6. Câu hỏi cần người dùng quyết

Đã chốt hết (2026-08-18):

1. **Hướng tiếp cận** → tường thuật từ dữ kiện thật của graph, không dùng reasoning summary.
2. **Render** → template i18n ở FE; BE chỉ phát dữ kiện có cấu trúc.
3. **Model** → `backend/.env:69` (`gpt-5.1-2025-11-13`) là nguồn đúng; xem mục 4.2.

## 7. Giới hạn của phép đo

- Mỗi ô đo **1 lần**, không phải 2 như plan viết. Chênh lệch giữa các lần chạy của cùng một
  cấu hình có thật (baseline `gpt-5-mini` low đo được 14.9s ở lần chạy `--quick` và 23.0s ở
  lần chạy đầy đủ). Các con số latency nên đọc theo **bậc độ lớn**, không theo số lẻ.
- **Ma trận chính chỉ dùng một prompt** (lịch trình Đà Nẵng 3N2Đ). Đây chính là chỗ bản đầu
  của báo cáo rút kết luận sai về `gpt-5.1` — một prompt không đủ để kết luận về năng lực
  của model. Prompt thứ hai (xác suất) mới lộ ra sự thật, và chỉ được đo ở một cấu hình.
- Chưa đo qua graph thật, chỉ đo model trực tiếp + một phép thử `bind_tools` rời.
- Chưa đo `gpt-5-mini` trên prompt khó, nên không biết chênh lệch độ phủ giữa hai model khi
  cùng gặp câu hỏi cần suy luận.
