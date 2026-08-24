# Prompt cho Claude Design — Admin Dashboard Portal (VSF Trip Planner)

Nguồn: `plans/reports/analysis-260821-1334-admin-dashboard-screens.md` (đã chốt 6 quyết định 2026-08-24)

Cách dùng: mở phiên Claude Code mới → `/design` → dán khối dưới đây.
Nếu 15 màn quá nặng cho 1 canvas, chạy 3 lần với 3 khối "PHẦN" ở cuối, dùng chung khối "BỐI CẢNH" + "DESIGN SYSTEM".

---

## PROMPT

```text
Thiết kế Admin Dashboard Portal cho VSF Trip Planner — hệ thống chatbot đặt phòng khách sạn Việt Nam.
Toàn bộ chữ trong UI dùng TIẾNG VIỆT. Desktop-first (1440px), không cần mobile.

━━━ BỐI CẢNH ━━━

Người dùng: 1 nhân viên vận hành nội bộ (1 role `admin` duy nhất, không phân cấp).
Họ KHÔNG có tài khoản Airflow — portal này là nơi duy nhất họ xem/chạy pipeline dữ liệu.

Portal làm 3 việc:
1. Quản lý khách sạn / phòng / giá phòng
2. Chạy lại (retrain) pipeline embedding để bot "học" dữ liệu mới
3. Quản lý và xử lý đơn đặt phòng

Tính chất giao diện: DATA-DENSE — bảng nhiều dòng, filter, form dài, trạng thái máy (state machine).
Đây KHÔNG phải giao diện chat cho khách hàng. Ưu tiên: đọc nhanh, quét cột, thao tác chính xác, không lỡ tay.

━━━ DESIGN SYSTEM (bắt buộc dùng lại) ━━━

Sản phẩm đã có design system từ giao diện chat. Portal admin phải nhận ra ngay là cùng một sản phẩm,
nhưng đặc hơn và ít hiệu ứng kính hơn.

Token màu (light) — dùng nguyên tên biến này:
  --t1:#15181C          chữ chính
  --t2:rgba(21,24,28,.66)  chữ phụ
  --t3:rgba(21,24,28,.60)  chữ mờ
  --t4:rgba(21,24,28,.44)  chữ rất mờ
  --acc:#3A73DE         xanh thương hiệu (nút chính, link, tab active)
  --acc-soft:rgba(58,115,222,.12)
  --ok:#2A9187   --ok-soft:rgba(42,145,135,.14)   --ok-ink:#1F6F67
  --warn:#C8802F --warn-soft:rgba(200,128,47,.16) --warn-ink:#8A5A21
  --err:#C05E70
  --on-acc:#FCFDFE
  --btn:#1B1F24  --btn-fg:#FBFCFD    nút đen (hành động dứt khoát)
  --g0..--g3: rgba(255,255,255,.44 / .60 / .76 / .92)   nền kính
  --line:rgba(21,24,28,.07)  --stroke:rgba(21,24,28,.11)  đường kẻ
  --fill:rgba(21,24,28,.05)  --fill2:rgba(21,24,28,.085)  nền chip/hover
  --page:linear-gradient(165deg,#EAF0F9 0%,#F5F2EE 48%,#E8EFF6 100%)

Điều chỉnh cho môi trường admin:
- Vùng bảng dùng nền đặc (--g3) thay vì kính mờ — chữ số phải sắc nét.
- Hiệu ứng kính chỉ giữ ở sidebar, thanh header dính, và panel/drawer nổi.
- Chiều cao 1 dòng bảng: 44–48px. Cỡ chữ bảng 13–14px. Số tiền dùng tabular-nums, canh phải.
- Bo góc: card 16px, input/nút 10px, chip 999px.
- Bảng màu trạng thái (dùng nhất quán ở MỌI màn):
    PENDING / chờ      → warn-soft nền, warn-ink chữ
    RESERVED / đang giữ → acc-soft nền, acc chữ
    CONFIRMED / PAID   → ok-soft nền, ok-ink chữ
    CANCELLED/FAILED/EXPIRED → fill nền, t3 chữ, có gạch/biểu tượng phân biệt
  Không được chỉ dựa vào màu — mỗi chip phải có nhãn chữ.

━━━ KHUNG CHUNG ━━━

Sidebar trái 240px, cố định, 3 nhóm:
  Tổng quan
  KHÁCH SẠN → Danh sách khách sạn · Trạng thái embedding
  DỮ LIỆU BOT → Pipeline · Độ phủ embedding
  ĐƠN HÀNG → Danh sách đơn · Đối soát thanh toán · Lịch phòng
  NHẬT KÝ → Nhật ký thao tác
Đáy sidebar: avatar + email admin + nút đăng xuất.
Header nội dung: breadcrumb + tiêu đề màn + nút hành động chính bên phải.

━━━ CÁC MÀN CẦN THIẾT KẾ ━━━

[A1] Đăng nhập Admin
  Màn giữa trang, nền --page. Email + mật khẩu + nút "Đăng nhập".
  Cần vẽ thêm 1 trạng thái LỖI PHÂN QUYỀN: đăng nhập đúng nhưng tài khoản không phải admin
  → thông báo "Tài khoản này không có quyền truy cập trang quản trị" + nút quay lại.

[A2] Khung layout + trạng thái rỗng
  Vẽ shell hoàn chỉnh (sidebar + header + vùng nội dung) với 1 trang mẫu.
  Kèm 3 trạng thái dùng lại toàn hệ thống: đang tải (skeleton bảng), rỗng (chưa có dữ liệu), lỗi tải.

[B1] Danh sách khách sạn
  Thanh công cụ: ô tìm theo tên/thành phố · filter nguồn dữ liệu (manual / booking / agoda...) ·
    filter đang bán / ngừng bán · filter trạng thái embedding · nút "Thêm khách sạn".
  Cột: Tên khách sạn (kèm ảnh thumbnail nhỏ + địa chỉ dòng dưới) · Thành phố · Hạng sao ·
    Nguồn (chip "Tự nhập" xanh / "Từ pipeline" xám) · Số phòng · Trạng thái embedding
    (chấm tròn: đã embed / chưa embed) · Đang bán (switch) · menu ⋯
  Phân trang dưới cùng. Chọn nhiều dòng bằng checkbox → thanh hành động hàng loạt nổi lên.
  QUAN TRỌNG: dòng "Từ pipeline" phải có dấu hiệu thị giác cho biết dữ liệu bị ETL ghi đè định kỳ.

[B2] Tạo khách sạn mới
  Form 1 cột rộng ~760px, chia nhóm có tiêu đề: Thông tin cơ bản (tên, loại hình, mô tả, hạng sao) ·
  Vị trí (địa chỉ, thành phố, toạ độ + ô bản đồ nhỏ xem trước) · Giờ nhận/trả phòng.
  Banner thông tin phía trên: "Khách sạn tạo tay sẽ không bị pipeline ghi đè."
  Banner cảnh báo phía dưới nút lưu: "Khách sạn mới chưa được embedding — bot chưa tìm thấy cho tới khi chạy lại pipeline."
  Nút: Huỷ · Lưu nháp · Lưu và tạo phòng.

[B3] Chi tiết / Sửa khách sạn
  Đầu trang: tên + chip nguồn + chip trạng thái embedding + switch đang bán.
  Tabs: Cơ bản · Vị trí · Tiện ích · Hình ảnh · Phòng · Lân cận.
  Vẽ chi tiết tab "Cơ bản" và tab "Tiện ích".
  Tab Tiện ích: chọn từ danh mục có sẵn, nhóm theo loại (Bể bơi, Ăn uống, Đưa đón...), dạng chip bật/tắt.
  CƠ CHẾ THEN CHỐT — phải thể hiện rõ: một số ô do pipeline quản lý.
    Khi khách sạn là "Từ pipeline": các ô đó hiện biểu tượng khoá + tooltip
    "Ô này do pipeline cập nhật, sửa tay sẽ bị ghi đè ở lần chạy kế tiếp".
  Ở các ô ẢNH HƯỞNG TỚI TÌM KIẾM (tên, mô tả, địa chỉ, điểm nổi bật vị trí, tiện ích) hiện nhãn nhỏ
    "ảnh hưởng tìm kiếm của bot" — sửa xong sẽ phải embedding lại.
  Khi có thay đổi chưa lưu: thanh dính đáy màn hình "Bạn có N thay đổi chưa lưu · Huỷ · Lưu".
  Sau khi lưu ô ảnh hưởng tìm kiếm → hộp thoại hỏi "Chạy lại embedding ngay?" (Để sau / Chạy ngay).

[B4] Hộp thoại Ngừng bán
  KHÔNG phải xoá vĩnh viễn — nhãn là "Ngừng bán khách sạn".
  Nội dung: hậu quả (bot ngừng gợi ý, không nhận đơn mới, đơn cũ giữ nguyên).
  Trường hợp CHẶN: còn N đơn đã xác nhận trong tương lai → liệt kê ngắn + vô hiệu hoá nút xác nhận.
  Có nút "Bán lại" cho khách sạn đang ngừng bán.

[B5] Quản lý phòng (bên trong B3)
  Danh sách phòng dạng card hoặc bảng: tên phòng · sức chứa · mô tả giường · diện tích m² ·
    số tiện nghi · ảnh · giá thấp nhất hiện có · nút Sửa/Xoá.
  Trạng thái rỗng phải nói rõ hậu quả: "Khách sạn chưa có phòng — chưa thể bán."
  Panel/drawer sửa phòng trượt từ phải: tên, sức chứa tối đa, mô tả giường, hướng nhìn,
    diện tích, tiện nghi phòng (chip), ảnh (kéo thả).

[B6] Quản lý giá phòng (bên trong B5)
  Đây là màn hình phức tạp nhất — thiết kế kỹ.
  Bảng giá theo NGÀY, không phải một giá cố định.
  Đề xuất: lịch tháng, mỗi ô ngày hiện giá + cờ hết phòng; chọn nhiều ngày bằng kéo thả
    → panel "Đặt giá cho 12 ngày đã chọn": giá, đơn vị tiền, đánh dấu hết phòng.
  Kèm chế độ xem dạng bảng theo khoảng ngày (từ ngày – đến ngày – giá – hết phòng).
  Với khách sạn "Từ pipeline": banner cảnh báo giá sửa tay sẽ bị pipeline ghi đè.
  Sửa giá KHÔNG cần embedding lại — đừng hiện bất kỳ nhắc nhở embedding nào ở màn này.

[C1] Danh sách pipeline
  7 pipeline dạng card: Embedding · Khách sạn · OTA · Google Maps · OSM · Tour · Địa điểm lân cận.
  Mỗi card: tên + mô tả một dòng bằng tiếng Việt thường (người dùng không biết khái niệm DAG) ·
    trạng thái lần chạy cuối (thành công/lỗi/đang chạy) · thời điểm · thời lượng ·
    biểu đồ thanh nhỏ 10 lần chạy gần nhất · nút "Chạy" và "Xem log".
  Card đang chạy có thanh tiến trình và trạng thái sống.

[C2] Hộp thoại chạy pipeline embedding
  Đây là nơi tốn tiền API — thiết kế phải chống bấm nhầm.
  Hai lựa chọn dạng thẻ radio lớn:
    ① "Chỉ dữ liệu mới" (khuyến nghị) — chỉ embedding các bản ghi chưa có, kèm số lượng ước tính
    ② "Chạy lại toàn bộ" — cảnh báo rõ: tốn phí API, chạy lâu, kèm số bản ghi
  Chọn bảng áp dụng: Khách sạn / Phòng / Địa điểm (chip nhiều lựa chọn).
  Tuỳ chọn nâng cao (thu gọn): giới hạn số bản ghi mỗi lần, kích thước lô.
  Với lựa chọn ②: yêu cầu gõ xác nhận hoặc tick "Tôi hiểu chi phí" mới bật được nút.
  LƯU Ý: chỉ có 3 bảng có embedding (Khách sạn, Phòng, Địa điểm). Bảng giá phòng KHÔNG có — đừng đưa vào.

[C3] Chi tiết lần chạy + log
  Trái: danh sách task theo thứ tự với trạng thái. Phải: khung log monospace, cuộn được,
    tô màu dòng lỗi, ô lọc log. Đầu trang: tóm tắt (bắt đầu, thời lượng, số bản ghi xử lý, số lỗi)
    + nút "Chạy lại task lỗi".

[D1] Danh sách đơn hàng
  Đơn vị = MỘT LẦN THANH TOÁN (có thể gồm nhiều phòng), không phải từng phòng lẻ.
  Hai tab: "Đơn hàng" (có thanh toán) · "Đặt phòng chưa thanh toán" (chưa gắn thanh toán, dễ treo/hết hạn).
  Thanh công cụ: tìm theo email/số điện thoại · filter trạng thái đơn · filter trạng thái thanh toán ·
    chọn khoảng ngày · filter khách sạn · nút xuất CSV.
  Cột: Mã đơn · Khách (tên + email, dòng nhỏ) · Khách sạn · Ngày nhận–trả · Số phòng ·
    Tổng tiền (canh phải) · Trạng thái đặt phòng · Trạng thái thanh toán · Tạo lúc · ⋯
  Dòng cần chú ý (đã thanh toán nhưng chưa xác nhận, hoặc sắp hết hạn giữ chỗ) có dải màu bên trái.
  Trên cùng: 4 ô số liệu — Đơn hôm nay · Doanh thu hôm nay · Chờ xử lý · Bất thường cần đối soát.

[D2] Chi tiết đơn hàng
  Bố cục 2 cột. Trái: thông tin khách (tên/email/điện thoại), danh sách các phòng trong đơn
    (mỗi phòng: khách sạn, loại phòng, ngày, số đêm, giá), tổng tiền.
  Phải: dòng thời gian dọc (tạo → giữ chỗ, kèm đếm ngược hết hạn → xác nhận / huỷ),
    khối thông tin thanh toán VNPay (mã giao dịch, thời điểm, trạng thái),
    liên kết "Xem cuộc trò chuyện gốc" dẫn sang phiên chat của khách.
  Đầu trang: nút Xác nhận đơn · Huỷ đơn (nút huỷ dùng viền đỏ, không phải nền đỏ).

[D3] Hộp thoại xác nhận / huỷ đơn
  Vẽ cả hai. Huỷ đơn: chọn lý do, cảnh báo không hoàn tác, hậu quả (phòng được trả lại kho,
    khách nhận email). Nút chính ghi rõ hành động: "Huỷ 2 phòng" chứ không phải "OK".
  Hiện rõ hành động này được ghi vào nhật ký thao tác.

[D4] Đối soát thanh toán
  Bảng gom theo nhóm bất thường: "Đã trả tiền nhưng chưa xác nhận" (lỗi callback ngân hàng) ·
    "Chờ thanh toán quá 30 phút" · "Thanh toán thất bại".
  Mỗi nhóm có số đếm và hành động khắc phục theo dòng.

[E1] Nhật ký thao tác
  Dòng thời gian có thể lọc: ai · làm gì · lúc nào · trên đối tượng nào.
  Bấm mở rộng hiện so sánh trước/sau (ví dụ đổi giá 1.200.000 → 1.500.000).
  Filter theo loại hành động: sửa giá · huỷ đơn · chạy pipeline · ngừng bán khách sạn.

━━━ YÊU CẦU CHUNG ━━━

- Mỗi màn cần trạng thái đầy dữ liệu; riêng B1, D1, B5 vẽ thêm trạng thái rỗng.
- Số tiền định dạng Việt Nam: 1.500.000 ₫. Ngày: 24/08/2026.
- Mọi hành động không hoàn tác (huỷ đơn, ngừng bán, chạy lại toàn bộ embedding) phải có bước xác nhận
  nêu rõ hậu quả, không dùng nút xác nhận chung chung.
- Vẽ luôn bộ thành phần dùng chung trên một artboard riêng: nút (chính/phụ/nguy hiểm/mờ),
  ô nhập, ô chọn, chip trạng thái, hàng bảng, phân trang, tab, chuyển đổi bật tắt, banner cảnh báo,
  khung rỗng, khung skeleton.
- Đừng thêm biểu đồ trang trí. Mỗi con số trên màn phải là số thật admin cần.
```

---

## Chia nhỏ nếu canvas quá tải

Dùng chung "BỐI CẢNH" + "DESIGN SYSTEM" + "KHUNG CHUNG" + "YÊU CẦU CHUNG", đổi phần màn hình:

- **Phần 1 — Nền tảng + Đơn hàng** (rủi ro thấp nhất, làm trước): A1, A2, D1, D2, D3, D4, E1 + bộ thành phần dùng chung
- **Phần 2 — Khách sạn**: B1, B2, B3, B4, B5, B6
- **Phần 3 — Pipeline**: C1, C2, C3

## Câu chưa chốt ảnh hưởng thiết kế

1. **R1** — khách sạn "Từ pipeline": ô/giá bị pipeline quản lý sẽ (i) khoá hẳn, (ii) có nút mở khoá, hay (iii) chỉ cảnh báo? Prompt hiện mô tả (i)+(iii); nếu chọn (ii) phải thêm cơ chế mở khoá vào B3/B6.
2. Đơn huỷ có gửi email cho khách không? Prompt đang giả định có (ghi trong D3).
3. Có cần dark mode cho portal admin không? Prompt hiện chỉ yêu cầu light.
