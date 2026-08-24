---
title: "Admin Dashboard Portal"
description: "Portal quản trị nội bộ: quản lý khách sạn/phòng/giá, chạy lại pipeline embedding, xử lý đơn đặt phòng. Mỗi màn là một phase độc lập, backend và frontend tách rõ."
status: pending
priority: P1
effort: "~17 phases"
tags: [admin, fastapi, react, airflow, supabase]
created: 2026-08-24
blockedBy: []
blocks: []
---

# Admin Dashboard Portal

## Overview

Xây portal quản trị nội bộ cho VSF Trip Planner. Ba yêu cầu gốc: (1) thêm/xoá/sửa
khách sạn, (2) cho bot train/retrain dữ liệu, (3) quản lý và xem tất cả đơn hàng.

Phần admin gần như **greenfield** ở cả 3 tầng: chưa có role/permission, chưa có một
endpoint admin nào, frontend chưa có router. Hạ tầng dữ liệu (bảng, RPC booking,
DAG embedding) thì đã sẵn sàng.

**Nguồn đầu vào:**
- Phân tích màn hình: `plans/reports/analysis-260821-1334-admin-dashboard-screens.md`
- Prompt thiết kế: `plans/reports/prompt-260824-0904-admin-dashboard-claude-design.md`
- Bản thiết kế: `plans/reports/VSF Trip Planner Admin Dashboard/VSF Admin Portal.dc.html`
  và `.../Sidebar.dc.html` (design tokens, layout, 14 artboard)

**Cách chia phase:** mỗi màn hình = 1 phase. Trong mỗi phase, phần **Backend —
hợp đồng API** được đặc tả đầy đủ (path, query, request/response shape, mã lỗi)
TRƯỚC phần **Frontend — màn hình**, để hai nửa làm song song hoặc tách người được.
Frontend chỉ phụ thuộc vào hợp đồng đã chốt, không phụ thuộc vào code backend.

## Quyết định đã chốt

| # | Vấn đề | Quyết định | Nguồn |
|---|--------|-----------|-------|
| 1 | ETL ghi đè khi admin sửa hotel | Khách sạn admin tạo mang `source_platform='manual'` → pipeline không đụng | analysis §5 |
| 2 | Đơn vị "đơn hàng" | `payments` là đơn, `bookings` là dòng chi tiết | analysis §5 |
| 3 | Xoá khách sạn | Soft delete `is_active` — UI gọi là "Ngừng bán" | analysis §5 |
| 4 | Portal user có tài khoản Airflow? | Không → nhóm C giữ đầy đủ, C3 (log) là P0 | analysis §5 |
| 5 | Admin sửa giá phòng? | Có → B6 full CRUD, kéo theo audit log | analysis §5 |
| 6 | Vai trò trung gian | Không — 1 role `admin` duy nhất | analysis §5 |
| 7 | **R1 — hotel từ pipeline** | **(iii) Cảnh báo, vẫn cho sửa.** Không thêm cột khoá, không sửa pipeline. UI banner rõ "pipeline sẽ ghi đè" | user 2026-08-24 |
| 8 | **Frontend routing** | **Vite entry riêng `admin.html`** + `src/admin/`. Không đụng `App.tsx` của chat | user 2026-08-24 |
| 9 | **Airflow** | **Nối thật**, gom vào 4 phase cuối (13–16) | user 2026-08-24 |
| 10 | **Bỏ B4, D4, E1** | Bỏ hẳn 3 màn: hộp thoại Ngừng bán, Đối soát thanh toán, Nhật ký thao tác. Xoá khỏi sidebar và khỏi plan | user 2026-08-24 |
| 11 | Email huỷ đơn | **Không** gửi (user không chọn) — huỷ chỉ trong hệ thống | user 2026-08-24 |
| 12 | Dark mode | **Không** — chỉ light, đúng bản thiết kế | user 2026-08-24 |

## Phát hiện khi scout (sửa lại giả định của 2 report đầu vào)

| # | Report nói | Thực tế trong code | Hệ quả |
|---|-----------|-------------------|--------|
| F1 | `source_hotel_id` sinh **UUID** cho hotel manual (analysis R3) | `hotels.source_hotel_id` là **BIGINT NOT NULL** (`database_schema.sql:31`); `rooms.source_room_id` cũng BIGINT | Phải cấp phát bằng **sequence Postgres**, không phải UUID → Phase 01 |
| F2 | `room_prices` là "giá theo khoảng ngày" | **Một dòng cho MỖI ĐÊM**: `check_in_date` = đêm đó, `check_out_date` = hôm sau (`place_details.py:54`) | B6 phải ghi n dòng cho n đêm → Phase 11 |
| F3 | — | Đêm bị crawl nhiều lần: `_average_price` chỉ lấy dòng **`crawled_at` mới nhất** | Admin ghi giá với `crawled_at=now()` sẽ **thắng** dòng OTA cũ → quyết định (iii) hoạt động mà không cần sửa pipeline |
| F4 | — | `match_hotels_with_rooms` đếm `count(*)` dòng `room_prices` và so bằng số đêm | Hai dòng cùng một đêm (admin + OTA) làm phép so **sai** → khách sạn **biến mất khỏi tìm kiếm**. Phải đổi sang `count(DISTINCT check_in_date)` → **P0, Phase 01** |
| F5 | "7 pipeline" (prompt C1) | Chỉ có **4 DAG nghiệp vụ** thật: `embed_supabase_tables_pipeline`, `google_maps_poc_attractions_pipeline_supabase`, `hotel_nearby_attractions_pipeline_supabase`, `tour_pipeline`. `hotel_pipeline.py`/`ota_pipeline.py`/`osm_pipeline.py` là **module thư viện**, không phải DAG | C1 vẽ 4 thẻ, không phải 7 → Phase 14. `clear_airflow_history` là housekeeping, **không** đưa vào allowlist |
| F6 | — | Airflow **3.3.0**, API là **`/api/v2`**, auth = `POST /auth/token` lấy JWT rồi `Authorization: Bearer` (không phải basic auth kiểu Airflow 2) | Phase 13 |
| F7 | — | Airflow chạy ở **compose stack riêng** (`backend/src/airflow/docker-compose.yaml`, api-server `8088:8080`), không cùng network với backend | Phase 13 phải xử lý network/credential trước |
| F8 | — | `bookings`/`payments` bị `REVOKE ALL FROM anon, authenticated` | Frontend **không được** dùng `supabase-js` để đọc đơn; mọi thứ qua backend service-role |

## Sidebar cuối cùng (sau khi bỏ B4/D4/E1)

Khớp đúng `Sidebar.dc.html` — file thiết kế **đã** loại D4/E1/Lịch phòng:

```
Tổng quan
KHÁCH SẠN     → Danh sách khách sạn · Trạng thái embedding
DỮ LIỆU BOT   → Pipeline · Độ phủ embedding
ĐƠN HÀNG      → Danh sách đơn  [badge 7 — số đơn cần xử lý]
```

Mục đang chọn: nền `--acc-soft`, chữ `--acc`, weight 600, `inset 2px 0 0 var(--acc)`.
Đáy sidebar: avatar tròn `--acc-soft` + tên + email + nút đăng xuất `⏻`.

## Bám sát thiết kế — quy tắc chung

`plans/reports/VSF Trip Planner Admin Dashboard/VSF Admin Portal.dc.html` +
`Sidebar.dc.html` là **nguồn sự thật cho giao diện**. Mỗi phase có màn hình đều có
mục **"Bám sát thiết kế — checklist đối chiếu 1:1"** liệt kê từng thành phần, nhãn,
màu và style lấy trực tiếp từ artboard tương ứng.

Quy tắc khi code:

1. **Copy hằng số, đừng gõ lại.** Khối `BK`/`PAY` (chip trạng thái), `:root` (token),
   `CHIP`, `CELL`, `STRIPE`… nằm trong `renderVals()` cuối file thiết kế — chuyển
   thẳng sang TypeScript, không tự đặt nhãn hay tự chọn màu.
2. **Không sáng tác thành phần mới.** Thiếu primitive thì thêm vào bộ Z (Phase 3 sở
   hữu `src/admin/ui/`), không vẽ riêng cho một màn.
3. **Không bỏ tín hiệu ngữ nghĩa.** Nền kẻ sọc của dòng ETL (B1), dải màu trái của
   dòng cần chú ý (D1), chấm rỗng ở mốc "đang chờ" (D2) — đó là ngữ nghĩa, không phải
   trang trí.
4. **Thiết kế lệch với code thì code thắng, nhưng phải ghi lại.** Mỗi phase có bảng
   **"Lệch giữa thiết kế và code — phải xử lý"** đánh số `L1…L78`, nêu rõ giữ / sửa
   copy / bỏ hẳn và lý do. Không im lặng làm khác thiết kế.

### Artboard đã có / chưa có

| Có artboard | Chưa có — phải suy từ mẫu đã có |
|---|---|
| A1, A2 (+3 trạng thái), B1, B2, B3 (Cơ bản + Tiện ích + hộp thoại re-embed), B5 (+rỗng), B6 (+bảng khoảng ngày), C1, C2 (2 biến thể), C3, D1 (+tab 2 +rỗng), D2, D3 (2 hộp thoại), Z | **B7** (Trạng thái embedding), **C4** (Độ phủ embedding) — xem Phase 12 |

A3 (Tổng quan) không có artboard riêng nhưng **trang mẫu trong A2 chính là A3** —
xem Phase 17.

### Chỉ mục các điểm lệch quan trọng nhất

| Mã | Nội dung | Phase |
|---|---|---|
| L1 | Chip `↩ Đã hoàn tiền` không có state tương ứng trong DB | 4 |
| L2 | Bỏ nút `Tạo đơn thủ công` (không có endpoint, không có yêu cầu) | 4 |
| L9 | `Thuế & phí dịch vụ` — schema không có, phải suy ra từ hiệu | 5 |
| L10 | Bỏ ô `Ngân hàng NCB ****4412` — không lưu `vnp_BankCode` | 5 |
| L16 | Bỏ dòng `Khách nhận email huỷ đơn` — quyết định #11 | 6 |
| L19 | Bỏ nút hàng loạt `Xoá` — chỉ soft delete | 7 |
| L21 | Sửa câu `pipeline ghi đè lúc 06:00 hằng ngày` — không có DAG nào như vậy | 7, 9, 11 |
| L25 | Bỏ nút `Lưu nháp` — không có trạng thái nháp | 8 |
| L33 | 5 nhóm tiện ích thiết kế ↔ 14 `category` thật, cần bảng ánh xạ | 9 |
| L40 | Bỏ `Kéo thả ảnh` — không có object storage, đổi sang nhập URL | 10 |
| L47 | Bỏ `Nhập từ CSV` ở B6 | 11 |
| L53 | **7 thẻ pipeline → 4 thẻ** (3 cái kia là module, không phải DAG) | 14 |
| L66–L68 | `run_id` là chuỗi không phải số; `task_id` thật khác nhãn thiết kế | 16 |
| L74 | Bỏ khối nhật ký thao tác ở Tổng quan — E1 đã bỏ | 17 |

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Admin đăng nhập được, tài khoản không phải admin bị chặn ở cả FE và BE | P0 |
| 2 | Xem, lọc, xác nhận, huỷ đơn đặt phòng — qua RPC có sẵn, không UPDATE thẳng bảng | P0 |
| 3 | CRUD khách sạn / phòng / giá theo đêm, không làm hỏng RAG và không làm hotel biến mất khỏi tìm kiếm | P0 |
| 4 | Chạy lại pipeline embedding từ portal, xem được log lỗi, không cần tài khoản Airflow | P0 |
| 5 | Mọi thao tác ghi của admin để lại vết trong `admin_audit_log` | P1 |
| 6 | Bundle admin tách hẳn khỏi app chat, không gây regression cho luồng khách hàng | P0 |

## Phases

| # | Phase | Màn | Status |
|---|-------|-----|--------|
| 1 | [Migration nền dữ liệu](./phase-01-migrations.md) | — | Done |
| 2 | [Backend: role admin, require_admin, khung router](./phase-02-admin-auth-backend.md) | — | Done |
| 3 | [Frontend: entry admin.html, shell, đăng nhập](./phase-03-admin-shell-frontend.md) | A1, A2, Z | Done |
| 4 | [Danh sách đơn hàng](./phase-04-orders-list.md) | D1 | Pending |
| 5 | [Chi tiết đơn hàng](./phase-05-order-detail.md) | D2 | Pending |
| 6 | [Xác nhận / Huỷ đơn](./phase-06-order-actions.md) | D3 | Pending |
| 7 | [Danh sách khách sạn](./phase-07-hotels-list.md) | B1 | Done |
| 8 | [Tạo khách sạn mới](./phase-08-hotel-create.md) | B2 | Done |
| 9 | [Chi tiết / Sửa khách sạn](./phase-09-hotel-edit.md) | B3 | Done |
| 10 | [Quản lý phòng](./phase-10-rooms.md) | B5 | Pending |
| 11 | [Quản lý giá phòng theo đêm](./phase-11-room-prices.md) | B6 | Pending |
| 12 | [Trạng thái & độ phủ embedding](./phase-12-embedding-status.md) | B7, C4 | Pending |
| 13 | [Airflow client + hạ tầng mạng/credential](./phase-13-airflow-client.md) | — | Pending |
| 14 | [Danh sách pipeline](./phase-14-pipelines-list.md) | C1 | Pending |
| 15 | [Chạy pipeline embedding](./phase-15-pipeline-trigger.md) | C2 | Pending |
| 16 | [Chi tiết lần chạy + log](./phase-16-run-detail-logs.md) | C3 | Pending |
| 17 | [Tổng quan KPI](./phase-17-overview-kpi.md) | A3 | Pending |

## Known gap — chưa phase nào chặn booking ở khách sạn `is_active = false`

Phase 1 làm đúng theo spec: `is_active = false` khiến bot **không gợi ý** khách sạn đó
(`match_hotels_with_rooms`), và các phase sau (07-09) là nơi admin bấm "Ngừng bán".
Nhưng **chưa phase nào** chặn ở biên đặt phòng thật: `create_booking_reservation`
(guest booking flow, ngoài phạm vi plan admin này) và `place_details.get_hotel_detail`
không kiểm tra `is_active`. Một khách đang giữ link chat cũ / itinerary đã lưu vẫn có
thể đặt được khách sạn đã ngừng bán. Quyết định (2026-08-24): để việc này lại cho một
phase sau (không mở rộng phạm vi Phase 1) — cần chốt trước khi phase 07-09 launch nút
"Ngừng bán" cho người dùng thật.

## Known gap — `log_api_io` middleware ghi cả body request/response admin ra stdout

`backend/src/main.py`'s `log_api_io` middleware in log toàn bộ response body (tới
2000 ký tự) ra stdout cho mọi path `/api/`, không phân biệt — đã có từ trước Phase
2, vô hại với `/admin/me`. Nhưng prefix `/api/v1/admin` mà Phase 2 mở ra là nơi
Phase 4-6 (đơn hàng) sẽ đặt danh sách đơn, chi tiết khách, thông tin thanh toán —
dữ liệu nhạy cảm nhất hệ thống, log nguyên văn không che. Quyết định (2026-08-24):
để việc định biên redaction lại cho Phase 4 (không mở rộng phạm vi Phase 2) — cần
chốt **trước khi** Phase 4 log request/response chứa dữ liệu khách thật.

## Phụ thuộc giữa các phase

```
01 (migration) ──┬─> 02 (auth BE) ──> 03 (shell FE) ──┬─> 04 ──> 05 ──> 06     [Đơn hàng]
                 │                                     ├─> 07 ──> 08 ──> 09 ──> 10 ──> 11   [Khách sạn]
                 │                                     ├─> 12                  [Embedding status]
                 │                                     └─> 13 ──> 14 ──> 15 ──> 16          [Pipeline]
                 └────────────────────────────────────────────────────────────> 17 (cần 04,07,12)
```

Sau phase 03, ba nhánh **Đơn hàng / Khách sạn / Pipeline** độc lập nhau — có thể làm
song song bởi ba người, file không giao nhau (xem "Sở hữu file" trong từng phase).

## Thứ tự khuyến nghị

1. **01 → 02 → 03**: nền tảng, mọi thứ phụ thuộc.
2. **04 → 05 → 06** (Đơn hàng): rủi ro thấp nhất — chủ yếu đọc, hai hành động ghi đều
   dùng RPC đã có và đã test. Giao được giá trị vận hành sớm nhất.
3. **07 → 11** (Khách sạn): nặng nhất, đụng vào dữ liệu nuôi RAG.
4. **12**: đóng vòng "sửa hotel → biết bot chưa học".
5. **13 → 16** (Pipeline): rủi ro hạ tầng tập trung ở phase 13.
6. **17**: cuối, vì KPI lấy số từ cả ba nhánh.

## Ranh giới không được vượt

- **Không** thêm route admin vào `backend/src/api/routes.py` (đã 1098 dòng). Tạo package
  mới `backend/src/api/admin/`.
- **Không** dùng `get_current_user` cho route admin — nó trả `None` khi `AUTH_REQUIRED=false`.
  Route admin phải dùng `require_admin` và luôn 401/403, bất kể cờ rollout.
- **Không** đổi template text embedding của `rooms`/`attractions` trong `embed_supabase_dag.py`
  (`_build_text` ghi rõ: vector đã lưu sinh từ nó). Chỉ nhánh `hotels` được sửa.
- **Không** UPDATE thẳng `bookings.status`. Dùng `confirm_booking_reservation` /
  `cancel_booking` (giữ advisory lock + state machine).
- **Không** đọc `bookings`/`payments` từ frontend bằng `supabase-js`.
- **Không** sửa `frontend/src/App.tsx` hoặc bất cứ file nào trong `frontend/src/components/`
  của app chat.

- **Không** hiện tên kỹ thuật (`dag_id`, tên bảng, tên cột) trên UI. Ngoại lệ duy
  nhất: chân khung log ở C3 (Phase 16, L67).
- **Không** render nút/ô dẫn tới ngõ cụt. Tính năng chưa có thì **ẩn**, không disabled
  kèm tooltip "Sắp có".

## Success Criteria

- [ ] Tài khoản không có `app_metadata.role = 'admin'` bị chặn ở FE (màn lỗi phân quyền) và BE (403), kể cả khi `AUTH_REQUIRED=false`
- [ ] Mọi mục trong "Bám sát thiết kế — checklist đối chiếu 1:1" của từng phase đã được đối chiếu
- [ ] 15 màn (A1, A2, B1, B2, B3, B5, B6, B7, C1, C2, C3, C4, D1, D2, D3) chạy được với dữ liệu thật
- [ ] Sửa giá một đêm cho phòng thuộc hotel ETL: giá mới có hiệu lực ngay ở `place_details`, và khách sạn **vẫn** xuất hiện trong `match_hotels_with_rooms` (không bị lỗi F4)
- [ ] Tạo hotel manual → embedding NULL → C4 đếm đúng → C2 chạy `only_null` → hotel xuất hiện trong tìm kiếm của bot
- [ ] Huỷ đơn từ D3 làm `bookings.status` chuyển CANCELLED qua RPC và ghi 1 dòng `admin_audit_log`
- [ ] `npm run build` sinh cả `index.html` và `admin.html`; bundle chat không tăng kích thước
- [ ] `npm run openapi:check` sạch sau mỗi phase backend
- [ ] `pytest backend/tests` xanh; app chat không có regression

<!-- slug: admin-dashboard-portal -->
