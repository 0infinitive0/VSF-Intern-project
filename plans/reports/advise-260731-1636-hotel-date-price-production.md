# Advise: Crawl + query giá khách sạn theo ngày check-in/check-out (production thực tế, quy mô POC)

## Reframed problem
Chatbot đặt trip hiện dùng `hotels.lowest_price` — 1 giá cache tĩnh từ lần crawl gần nhất, không theo ngày trip user nhập. Schema `room_prices` (đã có, key `(room_id, check_in_date, check_out_date, source_url, package_details)`) sẵn sàng lưu giá theo ngày nhưng (a) không có crawler tự động feed nhiều cặp ngày vào, và (b) query path chưa đọc bảng này. Đây là POC thực tập, chưa có user thật, không cần đầu tư anti-bot/proxy. Mục tiêu: pipeline crawl tự refresh giá theo ngày + chatbot trả giá đúng ngày trip, chạy được ổn định trên Airflow sẵn có, KISS.

## Exact requirements
1. Crawl job tự động (không thao tác tay) quét rolling window ~30 ngày tới × LOS 1-3 đêm cho các khách sạn/destination đang track.
2. Job chạy theo lịch (daily) qua Airflow DAG có sẵn (repo đã có `hotel_pipeline.py` DAG), output đúng format JSON hiện tại để tái dùng `load_hotels_to_db`/`_upsert_price` không sửa.
3. `hotel_selection.py`/`recommend_hotels.py` chuyển sang query `room_prices` theo `check_in_date`/`check_out_date` thực của trip, có fallback rõ ràng khi thiếu đúng ngày.
4. Không cần proxy rotation / anti-bot platform ở giai đoạn này — script đơn giản, lịch sự (rate-limit, retry, UA hợp lệ) là đủ.

## Goals
- Chatbot trả giá theo đúng ngày đến/về user nhập, không còn giá tĩnh lỗi thời.
- Data tự refresh hàng ngày không cần thao tác tay.
- Demo được cuối kỳ thực tập với data "sống" thay vì dump 1 lần.

## Non-goals
- Enterprise scraping platform (proxy pool, CAPTCHA solving, distributed workers).
- Lịch sử giá đầy đủ / phân tích xu hướng giá theo thời gian (room_prices chỉ giữ giá mới nhất mỗi cặp ngày, không phải time-series).
- Tích hợp OTA affiliate API chính thức (có thể là hướng sau này, không phải bây giờ).
- Đảm bảo 100% mọi cặp ngày user chọn đều có giá crawl sẵn.

## Constraints
- Không có ngân sách dịch vụ scraping trả phí ở giai đoạn này.
- Một mình intern maintain — pipeline phải đơn giản, dễ debug.
- Tái dùng Airflow + schema đã có, không đổi schema.

---

## Verdict
Hạ tầng bạn cần không phải "sản xuất doanh nghiệp" (proxy, anti-bot, queue phân tán) — đó là over-engineering cho 1 POC chưa có user thật. Cái thật sự thiếu là 2 việc rẻ tiền: (1) một DAG mới chạy lặp lại crawler hiện có (ở đâu đó ngoài repo) theo nhiều cặp ngày thay vì 1 lần, và (2) sửa lại 1 hàm query trong `hotel_selection.py` để đọc `room_prices` thay vì `hotels.lowest_price`. "Production thực tế" ở quy mô này nghĩa là: chạy tự động, có log/alert khi fail, có fallback khi thiếu data — không phải infra phức tạp.

## Nên làm
1. **Viết 1 script "generate JSON theo N cặp ngày"** gọi lại đúng cơ chế scrape đang dùng (bất kể là script tự viết hay tool nào), lặp qua danh sách `(check_in, check_out)` — ví dụ check_in = hôm nay+1 .. hôm nay+30, LOS ∈ {1,2,3} đêm → sinh nhiều file JSON (hoặc gộp 1 file lớn) đúng format hiện tại của `agoda.json`/`booking.json`.
2. **Thêm 1 Airflow DAG mới** (tách khỏi DAG load hiện tại) chạy schedule `@daily`, gọi script trên rồi trigger lại `hotel_pipeline` load JSON vào DB — tái dùng toàn bộ `_upsert_price` (upsert theo key ngày đã có sẵn, không cần sửa DB code).
3. **Rate-limit tối thiểu**: sleep ngẫu nhiên giữa các request, retry có backoff khi lỗi mạng/5xx, log rõ khách sạn/ngày nào fail để biết coverage thực tế sau mỗi lần chạy — không cần proxy, chỉ cần không bắn request dồn dập.
4. **Sửa query path**: trong `select_hotel_candidates`/`hotel_selection.py`, khi đã biết `check_in`/`check_out` của trip, query thêm `room_prices` (join qua `rooms.hotel_id`) lấy `MIN(price)` cho đúng cặp ngày đó thay vì đọc `hotels.lowest_price`.
5. **Fallback rõ ràng khi thiếu đúng ngày**: nếu không có row đúng `(check_in, check_out)`, dùng lại `hotels.lowest_price` (đổi label thành "giá tham khảo, có thể thay đổi") — không throw lỗi, không silent-return giá sai ngày mà không cảnh báo.

## Không nên làm
- Đừng dựng proxy pool / anti-bot service ngay bây giờ — user đã xác nhận rủi ro bị chặn IP không quan trọng ở giai đoạn này; đầu tư này chỉ trả giá trị khi có traffic thật cần độ tin cậy cao.
- Đừng biến `room_prices` thành time-series đầy đủ (giữ mọi lần crawl thay vì upsert đè) — chưa ai cần phân tích xu hướng giá, thêm bảng lịch sử giờ là YAGNI.
- Đừng cố crawl coverage 100% (mọi khách sạn × mọi ngày × mọi LOS) — tốn quota vô ích cho POC; ưu tiên đúng theo destination/khách sạn đang active trong app.
- Đừng chuyển sang OTA affiliate API ngay — đó là quyết định pháp lý/hợp đồng riêng, không nên trộn vào task kỹ thuật này.

## Có thể tốt hơn / hiệu quả hơn
- Nếu số khách sạn đang track nhỏ (~vài trăm theo tên file dataset hiện có), crawl 30 ngày × 3 LOS mỗi khách sạn vẫn là quy mô nhỏ — chạy 1 lần/ngày trong vài giờ là đủ, không cần song song hóa phức tạp.
- Có thể giảm LOS xuống chỉ 1-2 đêm (thay vì 1-3) nếu muốn giảm 1/3 khối lượng crawl mà vẫn cover phần lớn nhu cầu — đánh đổi coverage lấy tốc độ, hợp lý cho demo.
- Dùng `crawled_at` đã có sẵn trong `room_prices` để tự phát hiện data "cũ" (vd > 2 ngày chưa refresh) và cảnh báo trong dashboard Airflow sẵn có (`src/airflow/dashboard/app.py`) thay vì xây riêng.

## My take và đường đi
Thứ tự triển khai theo rủi ro thấp → cao, mỗi bước tự chạy được độc lập:
1. Xác định lại cơ chế lấy `agoda.json`/`booking.json` hiện tại là gì (script ở đâu, chạy thế nào) — đây là tiền đề bắt buộc, nếu chưa rõ thì việc đầu tiên là làm rõ/khôi phục lại đúng cách các file JSON này được sinh ra.
2. Bọc cơ chế đó thành hàm nhận `(check_in, check_out)` làm tham số, thay vì hardcode 1 cặp ngày.
3. Viết vòng lặp sinh N cặp ngày + gọi hàm trên, ghi JSON.
4. Thêm Airflow DAG daily gọi bước 3 rồi trigger DAG load hiện có.
5. Sửa `hotel_selection.py` để query `room_prices` theo ngày trip, có fallback.
6. Test end-to-end: đặt trip với ngày cụ thể → xác nhận giá trả về khớp `room_prices`, không phải `lowest_price` cache.

## Benefits
- Chatbot trả giá đúng ngày trip → tăng độ tin cậy demo so với giá tĩnh hiện tại.
- Tái dùng 100% schema + pipeline load đã có — rủi ro thay đổi thấp, không phá vỡ contract hiện tại.
- Chi phí hạ tầng gần bằng 0 (không proxy, không dịch vụ trả phí), phù hợp ngân sách intern.

## Trade-offs
- Không có lịch sử giá — nếu sau này cần phân tích xu hướng giá theo thời gian, phải thiết kế thêm bảng riêng (không phải bây giờ).
- Coverage ngày không đảm bảo 100% — user chọn ngày ngoài window 30 ngày hoặc LOS khác 1-3 đêm sẽ rơi vào fallback giá tĩnh.
- Không có anti-bot đồng nghĩa rủi ro bị chặn tăng nếu sau này traffic/tần suất crawl tăng lên — chấp nhận được ở POC nhưng là nợ kỹ thuật cần revisit trước khi có user thật.

## Work checklist
- [ ] Xác định/khôi phục cơ chế sinh `agoda.json`/`booking.json` hiện tại (script, vị trí, cách chạy)
- [ ] Refactor cơ chế đó nhận tham số `(check_in_date, check_out_date)` thay vì hardcode
- [ ] Viết script sinh danh sách N cặp ngày (default: 30 ngày tới × LOS 1-3 đêm) và gọi crawler cho từng cặp
- [ ] Thêm rate-limit (sleep + backoff retry) vào crawler
- [ ] Tạo Airflow DAG mới `@daily` gọi script crawl rồi trigger DAG load hiện có (`hotel_pipeline`)
- [ ] Sửa `hotel_selection.py`/`select_hotel_candidates` để query `room_prices` theo `check_in`/`check_out` thực của trip (JOIN `rooms` → `room_prices`, `MIN(price)`)
- [ ] Thêm fallback: dùng `hotels.lowest_price` (gắn nhãn "giá tham khảo") khi không có row đúng ngày
- [ ] Test end-to-end: trip với ngày cụ thể trả đúng giá từ `room_prices`, ngày ngoài coverage trả đúng fallback có nhãn rõ ràng
- [ ] (Tuỳ chọn) Thêm cảnh báo data cũ dựa trên `crawled_at` vào Airflow dashboard sẵn có

## Success metrics
- Ít nhất 1 lần chạy DAG crawl daily thành công tự động (không thao tác tay), log ghi rõ số cặp ngày/khách sạn crawl thành công/fail.
- `room_prices` có ≥ 1 row cho ≥ 90% khách sạn active × ít nhất 1 cặp ngày trong window 30 ngày sau mỗi lần chạy.
- Test trip với ngày nằm trong window trả về giá khớp đúng row `room_prices` tương ứng (verify bằng query trực tiếp DB so với response chatbot).
- Test trip với ngày ngoài window trả về fallback có nhãn rõ ràng, không throw lỗi, không giả vờ là giá chính xác.

## Unresolved questions
- Chưa xác định được cơ chế crawl hiện tại (script nào tạo `agoda.json`/`booking.json`) — cần làm rõ trước khi viết bước 1-3 của checklist.
- Chưa biết số lượng khách sạn/destination đang active thực tế trong app (chỉ suy từ tên file dataset) — ảnh hưởng ước lượng thời gian chạy crawl daily.
