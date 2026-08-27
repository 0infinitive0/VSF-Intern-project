# Kịch bản thuyết trình — 14 slide đầu (VP-OTA)

Tổng thời lượng mục tiêu: ~8–10 phút. Mỗi slide 30–50 giây.

---

## Slide 1 — Tiêu đề (20s)
Chào mọi người, nhóm em xin giới thiệu **VP-OTA** — một AI Agent lập kế hoạch du lịch đa lượt dành cho du khách Việt Nam.
Hệ thống được xây dựng trên LangGraph, GPT-5.1, FastAPI, Supabase pgvector và React.

## Slide 2 — Vấn đề (40s)
Hiện nay việc tự lên kế hoạch đi chơi vẫn rất thủ công. Nhóm em thấy ba điểm nghẽn lặp lại:
Thứ nhất, **tốn thời gian** — khách phải mở hàng chục tab để so sánh khách sạn, vé, lịch trình.
Thứ hai, **thiếu cá nhân hóa** — gợi ý chung chung, không bám ngân sách và sở thích từng nhóm.
Thứ ba, **lịch trình rời rạc** — tự ghép lịch rất dễ bỏ sót khoảng cách di chuyển, giờ mở cửa, bữa ăn.

## Slide 3 — Giải pháp (45s)
VP-OTA giải quyết bằng một trợ lý AI trò chuyện tiếng Việt tự nhiên: tự thu thập nhu cầu, tìm kiếm theo ngữ nghĩa và lập lịch trình tối ưu.
Bốn năng lực cốt lõi: **hội thoại đa lượt** để hỏi làm rõ nhu cầu; **tìm kiếm ngữ nghĩa RAG** trên Supabase pgvector; **lập lịch tự động** tối ưu khoảng cách và chèn bữa ăn, nghỉ ngơi; và **tái sử dụng lịch trình** bằng fingerprint BGE-M3 cho các chuyến tương đồng.

## Slide 4 — Quy trình (40s)
Luồng đi từ hội thoại đến lịch trình hoàn chỉnh qua 5 bước: thu thập nhu cầu → tìm kiếm ngữ nghĩa → lập lịch tự động → khách chọn và chỉnh sửa → chốt và đặt phòng.
Điểm đáng chú ý: trước bước lập lịch, hệ thống kiểm tra **Tier 1 Cache**. Nếu có lịch trình mẫu đủ tương đồng thì tái sử dụng ngay, không cần tính lại từ đầu.

## Slide 5 — Kiến trúc (45s)
Kiến trúc gồm bốn tầng.
**Frontend** React 19 + Vite với ChatPanel, ItineraryPanel và streaming SSE.
**Orchestrator** FastAPI + LangGraph — một StateGraph 14 node, dùng GPT-5.1 cho suy luận và GPT-4o-mini cho tác vụ nhanh.
**Domain services** là Python thuần, tất định: chọn khách sạn, lập lịch, tái sử dụng lịch trình, tìm kiếm.
**Data layer** là Supabase Postgres với pgvector cho RAG và cache, cùng pipeline Airflow ETL.
Chi tiết từng phần nhóm em để ở phụ lục.

## Slide 6 — Luồng LangGraph (50s)
Mỗi tin nhắn của người dùng đi qua 14 node, chia 3 giai đoạn.
**Giai đoạn 1 — hiểu yêu cầu (7 node):** nạp context, chặn tin nhắn độc hại, LLM trích xuất patch thay đổi, validate rồi mới ghi vào state; nếu thiếu thông tin thì hỏi lại, nếu khách hỏi ngang thì trả lời rồi thoát sớm.
**Giai đoạn 2 — điều phối (5 node):** supervisor chọn worker phù hợp — khách sạn, lịch trình, đặt phòng hoặc hỏi đáp — lặp tối đa 5 lần.
**Giai đoạn 3 — hoàn tất (2 node):** kiểm tra ngân sách, tự re-plan một lần nếu vượt, rồi gộp câu trả lời gửi về frontend.
Một lưu ý: `booking_node` **luôn từ chối trong graph — đây là thiết kế có chủ đích**. Đặt phòng và thanh toán VNPay chạy thật, nhưng qua REST API riêng, tách khỏi vòng lặp LLM để bước tài chính không phụ thuộc AI.

## Slide 7 — Sản phẩm (35s)
Về trải nghiệm: ChatPanel và ItineraryPanel hiển thị song song, khách vừa chat vừa thấy lịch trình cập nhật.
Card khách sạn trực quan để so sánh và chọn nhanh; chỉnh sửa lịch trình, đổi khách sạn tức thời; đặt phòng và thanh toán VNPay tích hợp sẵn; phản hồi streaming qua SSE và hỗ trợ song ngữ Việt–Anh.

## Slide 8 — Bảng quản trị (35s)
Phía vận hành, nhóm em làm một admin dashboard: theo dõi doanh thu, đơn hàng và các giữ chỗ sắp hết hạn theo thời gian thực; quản lý khách sạn, phòng, giá và trạng thái embedding; giám sát pipeline dữ liệu và độ phủ embedding; chuẩn hoá danh mục tiện ích; xử lý đơn, huỷ và giữ chỗ hết hạn.

## Slide 9 — Điểm nổi bật (45s)
Sáu giá trị nhóm em muốn nhấn mạnh:
**Lên lịch tức thì** nhờ cache thông minh ở ngưỡng tương đồng 88%.
**Đáng tin cậy theo thiết kế** — mỗi bước tự kiểm tra chéo, lỗi bị bắt bên trong hệ thống.
**Không vượt ngân sách âm thầm** — hệ thống tự phát hiện và điều chỉnh, luôn báo rõ cho khách.
**Đúng mô hình cho đúng việc** — GPT-5.1 lo suy luận, GPT-4o-mini lo phần nhanh, tối ưu cả tốc độ lẫn chi phí.
**Đặt phòng và thanh toán thật** với VNPay, không chỉ là demo.
Và **trò chuyện tự nhiên thay vì điền form**, song ngữ, phản hồi từng chữ.

## Slide 10 — Tiền Anh Kiệt (25s)
Về đội ngũ. Em phụ trách full-stack, 192 commit: thiết kế và refactor agent graph LangGraph 14 node với conditional routing; làm streaming chat UX gồm thinking block và suggestion chip theo ngữ cảnh; tối ưu tìm kiếm điểm đến bằng RPC tiered search; xử lý lỗi embedding và dẫn dắt bộ eval, kế hoạch dự án; triển khai hạ tầng trên AWS EC2 với Docker Compose và Caddy.

## Slide 11 — Nguyễn Hữu Đức (25s)
Bạn Đức phụ trách backend và data, 147 commit: cải thiện tìm kiếm và lọc khách sạn — lọc theo số khách ngay trong SQL, tính giá phòng trung bình theo kỳ ở; thiết kế schema Supabase/Postgres và pgvector; hoàn thiện Tier 1 Cache lưu lịch trình làm template; xây pipeline Airflow ETL; và tích hợp các LLM provider như Cloudflare, OpenRouter.

## Slide 12 — Đinh Nguyễn Nhật Lâm (25s)
Bạn Lâm phụ trách frontend và luồng đặt phòng, 135 commit: toàn bộ luồng booking và thanh toán VNPay gồm giữ chỗ, đổi phòng, biên nhận; bản đồ tương tác Mapbox GL JS với animation tuyến đường; tích hợp pipeline embedding Cloudflare Workers AI vào Airflow; và crawl dữ liệu khách sạn, triển khai database lên Supabase.

## Slide 13 — Kết / Demo (20s)
Đó là VP-OTA. Nhóm em đã deploy bản chạy thật, mọi người có thể trải nghiệm trực tiếp tại link demo, mã nguồn công khai trên GitHub.
Nhóm em sẵn sàng demo trực tiếp và trao đổi thêm. Xin cảm ơn!

## Slide 14 — Lộ trình (30s)
Cuối cùng là lộ trình phát triển, tính từ tháng 08/2026.
**Đã hoàn thành:** hội thoại AI, RAG search, lập lịch tự động, đặt phòng và thanh toán VNPay với giữ chỗ real-time, mở rộng test coverage.
**Q4/2026:** mở rộng dữ liệu điểm đến và khách sạn.
**Q1/2027:** ứng dụng mobile.
**Q2/2027:** đo lường và giám sát chi phí AI theo thời gian thực.

---

## Ghi chú khi trình bày
- Slide 13 hiện là slide kết ("CẢM ƠN!") nhưng đứng **trước** slide 14 lộ trình. Nếu muốn kết thúc gọn, nên nói lộ trình (14) trước rồi quay lại 13 để chốt — hoặc đảo thứ tự hai slide trong file.
- Slide 5 và 6 là phần nặng kỹ thuật nhất; nếu bị giới hạn thời gian, rút gọn slide 6 còn 3 câu (3 giai đoạn) và giữ nguyên phần lưu ý `booking_node`.
- Câu chốt phòng thủ khi bị hỏi "sao bot không đặt phòng được?": *"Bot cố tình không đặt phòng — bước tài chính chạy qua REST API riêng, tách khỏi LLM để đảm bảo tính chính xác."*
