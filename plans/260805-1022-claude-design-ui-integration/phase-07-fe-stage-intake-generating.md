---
phase: 7
title: "[FE] Stage: Intake & Generating"
status: pending
priority: P2
effort: "1-1.5 ngày"
dependencies: [5]
track: frontend
---

# Phase 7: [FE] Stage: Intake & Generating

## Tổng quan

Dựng hai trạng thái stage đơn giản nhất: màn hình hero lúc thu thập thông tin, và trạng thái
AI đang xử lý. Cả hai chỉ tiêu thụ `intake` và `pending` đã có sẵn trong `ChatState` — không
cần backend mới, không cần contract mới.

Phase nhỏ nhất trong track frontend. Nên làm ngay sau Phase 5 để có một stage hoàn chỉnh
đầu tiên chứng minh shell hoạt động.

## Yêu cầu

**Chức năng**
- Stage `intake`: hero title, mô tả ngắn, và bảng "THÔNG TIN AI ĐANG THU THẬP" với từng
  dòng có trạng thái đã có / chưa có
- Stage `generating`: các bước xử lý và skeleton card
- Mỗi dòng thông tin đã thu thập hiển thị **giá trị thật** từ `intake`, không phải placeholder
- Mọi chuỗi được dịch

**Phi chức năng**
- Không có bước xử lý nào được bịa: chỉ hiển thị những bước phản ánh trạng thái thật
- Skeleton dùng animation shimmer từ token Phase 1
- Chuyển từ `intake` sang `generating` sang `hotels` phải mượt, không nhảy layout

## Kiến trúc

### Stage intake

Ảnh tham chiếu: `data/design/screenshots/sb.png`.

Bảng checklist bên phải ánh xạ trực tiếp sang `IntakeStatus` đã có:

| Dòng trong design | Nguồn dữ liệu | Hiện khi đã có |
|---|---|---|
| Điểm đến | `intake.destination` | tên điểm đến |
| Số người | `intake.people` | chuỗi đã format (ví dụ "2 người") |
| Ngày đi – về | `intake.start_date` / `end_date` | khoảng ngày theo locale |
| Ngân sách | mức đã chọn | nhãn mức |
| Sở thích | `intake.preferences` | các chip |

Trạng thái "chưa có" suy ra từ `intake.missing`. Dòng chưa có hiển thị dấu `—`, đúng như
design. **Không** đoán hay điền sẵn giá trị.

Lưu ý về `intake.people`: đây là **chuỗi đã format** ở backend (ví dụ `"2 người"`), không
phải số — comment trong `types.ts:85` đã ghi rõ. Không parse nó thành số để render lại; hiển
thị nguyên văn. Điều này cũng có nghĩa dòng này sẽ hiện tiếng Việt kể cả khi UI đang là
tiếng Anh — đây là hạn chế đã biết và đã ghi nhận trong plan i18n hiện có.

### Stage generating

Ảnh tham chiếu: các bước trong `Yêu cầu cập nhật thiết kế.md` §AI Searching State.

Design liệt kê 6 bước ("Phân tích điểm đến", "Phân tích ngân sách", "Tìm khách sạn phù
hợp", …) với dấu tick lần lượt. **Backend không phát ra tiến độ theo bước** — nó chỉ có
`pending: true` và thời gian đã trôi.

Cách xử lý trung thực (mục 14 bảng "Phần chưa làm"), theo đúng tiền lệ đã ghi trong plan
Stitch trước đó — nơi "DeepDive Thinking" với các bước tick giả đã bị loại bỏ:

- **Không** hiển thị danh sách bước có dấu tick tuần tự — đó là tiến độ bịa
- Hiển thị **một** trạng thái đang xử lý kèm số giây thật đã trôi
- Hiển thị skeleton card cho các card khách sạn sắp tới — skeleton là hình dạng chờ, không
  phải tuyên bố về tiến độ, nên hoàn toàn trung thực
- Shimmer + progress bar dạng vô hạn (indeterminate), không phải thanh phần trăm

Nếu sau này backend phát ra tiến độ theo bước thật thì danh sách tick có thể thêm vào mà
không đổi gì khác. Ghi điều này lại trong component.

## File liên quan

- Tạo: `frontend/src/components/stage-intake.tsx`
- Tạo: `frontend/src/components/stage-generating.tsx`
- Tạo: `frontend/src/components/intake-checklist.tsx` — bảng thông tin đã thu thập
- Tạo: `frontend/src/components/skeleton-card.tsx` — dùng lại ở Phase 8
- Sửa: `frontend/src/components/stage-router.tsx` — nối hai stage thật vào
- Sửa: `frontend/src/i18n/locales/{en,vi}.json`
- Tái dùng: `trip-parameters-card.tsx` — cân nhắc gộp vào `intake-checklist` nếu trùng lặp;
  nếu gộp thì xoá file cũ, không để hai component làm cùng một việc

## Các bước thực hiện

1. `intake-checklist.tsx` — render 5 dòng từ `IntakeStatus`, dấu `—` cho dòng chưa có.
   So sánh với `trip-parameters-card.tsx` hiện có: nếu trùng chức năng thì gộp và xoá cái cũ
   (quy tắc dự án: tránh component trùng lặp).
2. `stage-intake.tsx` — hero + mô tả + checklist, theo typography 5 cấp của Phase 1.
3. `skeleton-card.tsx` — khối shimmer tái dùng được, nhận `variant` để khớp hình dạng card
   khách sạn ở Phase 8.
4. `stage-generating.tsx` — trạng thái đang xử lý + số giây thật + skeleton. Ghi comment nêu
   rõ vì sao không có danh sách bước tick.
5. Nối cả hai vào `stage-router`; kiểm tra transition giữa các stage không gây nhảy layout.
6. Thêm chuỗi vào cả hai catalog i18n.
7. Kiểm chứng bằng mock: lượt 1-2 phải ra stage intake với checklist điền dần; độ trễ 3 giây
   ở lượt 3 của mock phải ra stage generating rồi chuyển sang hotels.

## Tiêu chí hoàn thành

- [ ] Stage intake hiển thị hero + checklist với giá trị `intake` thật
- [ ] Dòng chưa có hiện `—`, không có giá trị đoán hay điền sẵn
- [ ] Stage generating hiện trạng thái đang xử lý + số giây thật + skeleton
- [ ] Không có danh sách bước tick tuần tự giả
- [ ] `intake.people` hiển thị nguyên văn, không parse lại
- [ ] Không còn component trùng chức năng với `trip-parameters-card`
- [ ] Chuyển stage mượt, không nhảy layout
- [ ] Mọi chuỗi được dịch ở cả hai catalog
- [ ] `npm run typecheck` và `npm run lint` pass

## Đánh giá rủi ro

**Sức ép muốn ship danh sách bước có tick.** Nó trông rất đẹp trong design và rất dễ làm giả.
Đây là chính xác cái mà plan trước đã từ chối và cùng lý do: nó tuyên bố với người dùng rằng
hệ thống đang ở bước 4/6 trong khi hệ thống không hề biết điều đó. Giữ nguyên quyết định;
mục này đã nằm trong đoạn ghi chú của component.

**Trùng lặp với `trip-parameters-card`.** Component đó hiện đã hiển thị tham số chuyến đi
trong luồng chat. Nếu để cả hai tồn tại, chúng sẽ trôi dạt khác nhau. Quyết định gộp hay giữ
riêng phải xong trong bước 1, không để lại sau.
