# Kế hoạch Thực hiện Data Pipeline (Tuần 1 - Sprint 1)

Dựa trên yêu cầu của BRD đối với Sprint 1, mục tiêu cốt lõi của tuần này là xây dựng thành công 2 luồng dữ liệu (Flows) độc lập để lấy dữ liệu từ 2 nguồn OTA mục tiêu. 

Bạn và đồng nghiệp có thể tự do chọn xem ai sẽ "ôm" Flow nào từ đầu đến cuối.

---

## Flow 1: Data Pipeline cho Booking.com
**Người phụ trách:** `[Thảo luận và điền tên]`

*   **Ngày 1 (Chuẩn bị):** Khảo sát rủi ro pháp lý (`robots.txt`, rate-limit) và DOM HTML của Booking.com. Phác thảo Schema các trường dữ liệu lấy từ nguồn này.
*   **Ngày 2 (Extract):** Viết script Python (Scrapy/Playwright) crawl dữ liệu thô (tên, giá, mô tả phòng) của 500+ khách sạn tại VN (ưu tiên Vinpearl). Xuất ra file `booking_raw.json`.
*   **Ngày 3 (Transform):** Dùng Pandas làm sạch dữ liệu Booking (xử lý null, chuẩn hóa tiền VND). Gọi Gemini/OpenAI API để tạo Vectors (Embeddings) cho phần mô tả.
*   **Ngày 4 (Load):** Viết script đẩy dữ liệu có cấu trúc vào **PostgreSQL** và đẩy vectors vào **Qdrant**.
*   **Ngày 5 (Test):** Chạy thử pipeline Booking từ đầu đến cuối, đảm bảo không có lỗi gãy luồng.

---

## Flow 2: Data Pipeline cho Agoda
**Người phụ trách:** `[Thảo luận và điền tên]`

*   **Ngày 1 (Chuẩn bị):** Khảo sát rủi ro pháp lý (`robots.txt`) và các API ẩn / DOM của Agoda. Cân đối Schema sao cho tương thích với luồng của Booking.
*   **Ngày 2 (Extract):** Viết script Python crawl dữ liệu thô từ Agoda cho các điểm đến tương tự ở VN. Xuất ra file `agoda_raw.json`.
*   **Ngày 3 (Transform):** Dùng Pandas làm sạch dữ liệu Agoda. *Lưu ý quan trọng:* Xây dựng logic gộp/khử trùng lặp (Deduplication) nếu khách sạn đó đã tồn tại bên luồng Booking. Tạo Vectors bằng API.
*   **Ngày 4 (Load):** Viết script đẩy dữ liệu Agoda vào cùng bảng **PostgreSQL** và collection **Qdrant** mà Flow 1 đang dùng.
*   **Ngày 5 (Test):** Chạy thử pipeline Agoda. Đảm bảo dữ liệu Agoda hòa trộn tốt vào CSDL chung.

---

## Công việc chung (Cả 2 cùng phối hợp)
*   **Môi trường Database:** Cùng nhau chốt thiết kế ERD cuối cùng và viết file `docker-compose.yml` để dựng PostgreSQL + Qdrant dưới local.
*   **Đóng gói Báo cáo (Ngày 5):** Viết một kịch bản test nhỏ nghiệm thu (VD gõ: *"Tìm resort có hồ bơi lớn ở Nha Trang"* xem Qdrant trả về có chuẩn không). Gom chung dataset >1000 bản ghi để gửi báo cáo cho Mentor.

---
> **Lưu ý gửi Mentor:** Kế hoạch này bám sát tiêu chí nghiệm thu của Cột mốc M1 (Kết thúc Sprint 1) trong BRD, đảm bảo chúng ta có sẵn dữ liệu sạch để team làm UI/Hội thoại bắt tay vào việc ở Sprint 2.
