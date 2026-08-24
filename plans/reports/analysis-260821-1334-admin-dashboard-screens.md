# Phân tích màn hình Admin Dashboard Portal

Ngày: 2026-08-21 · Nguồn: scout codebase (`backend/src`, `frontend/src`, `supabase/seed.sql`, `backend/scripts/migrations`, `backend/src/airflow`)

Yêu cầu gốc:
1. Thêm/xóa/sửa khách sạn
2. Cho phép bot train/retrain lại dữ liệu
3. Quản lý và xem tất cả các đơn hàng

---

## 1. Hiện trạng (bằng chứng từ code)

| Hạng mục | Hiện trạng | File |
|---|---|---|
| Auth | Verify Supabase JWT → `AuthenticatedUser{id, email, is_anonymous}`. **Không có role/permission** | `backend/src/auth/dependencies.py`, `jwt_verifier.py` |
| API admin | **Không tồn tại**. 26 route hiện có đều là chat/booking/payment cho end-user | `backend/src/api/routes.py` |
| Frontend | SPA 1 màn hình, **không có router** (`App.tsx` → `AppShell` trực tiếp) | `frontend/src/App.tsx` |
| Hotel data | `hotels` (44 cột, có `embedding vector(1024)`), `rooms`, `room_prices` — sinh ra từ ETL, khóa `(source_platform, source_hotel_id NOT NULL)` | `supabase/seed.sql:443` |
| Orders | `bookings` (PENDING/RESERVED/CONFIRMED/CANCELLED/EXPIRED) + `payments` (PENDING/PAID/FAILED/CANCELLED). RLS bật, `REVOKE ALL FROM anon, authenticated`, chỉ `service_role` | `backend/scripts/database_schema.sql:290`, `migrations/20260818_add_payments_table.sql` |
| Ghi booking | Qua RPC `create_booking_reservation` / `confirm_booking_reservation` / `cancel_booking` (advisory lock) | `migrations/20260818_add_booking_reservation_rpcs.sql` |
| Retrain | DAG `embed_supabase_dag` (bge-m3), điều khiển bằng Airflow Variables: `embed_supabase_only_null`, `embed_supabase_force_tables`, `embed_supabase_batch_limit`, `embed_supabase_chunk_size`. Ngoài ra: `hotel_pipeline`, `ota_pipeline`, `google_maps_supabase_dag`, `osm_pipeline`, `tour_pipeline_dag`, `hotel_nearby_supabase_dag` | `backend/src/airflow/dags/data_pipeline/` |
| Dashboard nội bộ | Đã có 1 FastAPI app read-only duyệt bảng + xem itinerary (`/api/data/{table}`, `/api/itineraries`, `/api/trip_plan`) | `backend/src/airflow/dashboard/app.py` |

**Kết luận hiện trạng:** hạ tầng dữ liệu + RPC đã sẵn sàng; phần admin gần như là **greenfield** ở cả 3 tầng (auth role, API, UI).

---

## 2. Đánh giá — 5 vấn đề cần chốt trước khi làm màn hình

Đây là phần "làm rõ" quan trọng hơn danh sách màn hình, vì mỗi vấn đề đổi thiết kế màn hình.

### V1. Không có mô hình phân quyền — **chặn toàn bộ**
`AuthenticatedUser` không có trường role. Cần:
- Thêm custom claim (Supabase `app_metadata.role = 'admin'`) và đọc claim trong `jwt_verifier`
- Dependency `require_admin()` mới, tách khỏi `get_current_user` (vốn trả `None` khi `AUTH_REQUIRED=false` — **không được** để logic đó rò sang route admin)

### V2. Sửa khách sạn bằng tay sẽ bị ETL ghi đè
Pipeline upsert theo `(source_platform, source_hotel_id)`. Admin sửa giá/mô tả → lần chạy DAG kế tiếp ghi đè mất.
**→ ĐÃ CHỐT (b): `source_platform='manual'`.** Khách sạn admin tạo mang `source_platform='manual'`, pipeline không upsert vào. Hệ quả:
- Chỉ khách sạn `manual` mới sửa được an toàn ở mọi field.
- Khách sạn ETL (`booking`, `agoda`…) sửa tay **vẫn bị ghi đè** ở lần chạy DAG kế tiếp → UI phải khóa/cảnh báo rõ, xem R1 mục 6.

### V3. Sửa khách sạn làm **hỏng RAG** nếu không re-embed
`hotels.embedding` sinh từ text mô tả. Sửa tên/mô tả/tiện ích mà không re-embed → search ngữ nghĩa trả kết quả cũ; khách sạn tạo mới có `embedding NULL` → **bot không bao giờ tìm thấy**.
**Chỉ 3 bảng có cột `embedding`**: `hotels`, `rooms`, `attractions` (`embed_supabase_dag.py:55`). **`room_prices` KHÔNG có embedding** → sửa giá / `sold_out` / khoảng ngày **không cần re-embed**.

Cột thực sự được đưa vào text embedding (`TABLE_COLUMNS`):
- `hotels`: `name`, `accommodation_type`, `area_name`, `address`, `location_highlight`, `description`, `amenities`
- `rooms`: `name`, `bed_description`, `view`, `room_facilities`

→ Chỉ khi sửa đúng các cột trên (hoặc tạo hàng mới) mới `SET embedding = NULL` + trigger DAG (`only_null=true`). Sửa ảnh, giờ check-in, `star_rating`, giá phòng → bỏ qua re-embed. Backend nên tự so field đã đổi với danh sách này thay vì để admin bấm tay.

⚠️ `_build_text` ghi rõ: text template của `rooms`/`attractions` **không được đổi** vì vector đã lưu sinh từ nó — chỉ nhánh `hotels` được phép sửa.

### V4. Xóa cứng khách sạn là không an toàn
`bookings.room_id` có `ON DELETE RESTRICT`. Xóa hotel có booking CONFIRMED sẽ lỗi DB (hoặc mất lịch sử đơn).
**→ ĐÃ CHỐT: soft delete** (`is_active boolean`) + filter ở `match_hotels_with_rooms`. "Xóa" trong UI = "Ngừng bán". Cần migration thêm cột `is_active` cho `hotels` (và cân nhắc `rooms`).

### V5. Đơn hàng **không có danh tính khách** ở bảng `bookings`
`bookings` chỉ có `temporary_user_ref` + `session_id`. Tên/email/SĐT khách nằm ở `payments.guest_name/guest_email/guest_phone`, và 1 payment gom nhiều `booking_ids[]`.
**→ ĐÃ CHỐT: đơn vị đơn hàng = `payment`**, booking là dòng chi tiết. Hệ quả: booking PENDING chưa gắn payment sẽ không xuất hiện trong danh sách đơn chính → cần tab/filter riêng "Booking chưa thanh toán" ở D1 để không mất dấu đơn treo.

**Ràng buộc kỹ thuật kèm theo:** `bookings`/`payments` bị REVOKE khỏi `anon`/`authenticated` → frontend **không được** query trực tiếp bằng `supabase-js`; mọi thứ phải qua backend service-role. Frontend hiện đã có `@supabase/supabase-js` cho auth, dễ nhầm.

---

## 3. Danh sách màn hình

### Nhóm A — Nền tảng (bắt buộc, không thuộc 3 yêu cầu nhưng không có thì không chạy được)

| # | Màn hình | Nội dung | Ưu tiên |
|---|---|---|---|
| A1 | Đăng nhập Admin | Tái dùng Supabase auth, chặn tài khoản không có `role=admin`. **1 role duy nhất**, không phân cấp | P0 |
| A2 | Layout + Route guard | Sidebar 3 nhóm, redirect khi thiếu quyền. **Cần thêm router vào frontend** (hiện chưa có) | P0 |
| A3 | Trang tổng quan (KPI) | Đơn hôm nay, doanh thu, số hotel active, số row `embedding IS NULL`, trạng thái DAG gần nhất | P2 |

### Nhóm B — Quản lý khách sạn (yêu cầu 1)

| # | Màn hình | Nội dung | Ưu tiên |
|---|---|---|---|
| B1 | Danh sách khách sạn | Bảng phân trang + tìm theo tên/thành phố; filter `source_platform`, `is_active`, trạng thái embedding; badge "manual/ETL" | P0 |
| B2 | Tạo khách sạn | Form: thông tin cơ bản, địa chỉ + `coordinates`, `star_rating`, `check_in/out_time`. Set `source_platform='manual'`, `embedding=NULL` | P0 |
| B3 | Chi tiết / Sửa khách sạn | Dạng tab: **Cơ bản** · **Vị trí** · **Tiện ích** (`amenities[]`, `amenity_groups` jsonb — dùng `amenity_catalog.py` làm nguồn chọn) · **Hình ảnh** (`images[]`) · **Lân cận** (`nearby_attractions/essentials`). Hiển thị field nào do ETL quản lý (V2) | P0 |
| B4 | Ngừng bán / Xóa | Confirm dialog, chặn nếu còn booking CONFIRMED tương lai, mặc định soft delete (V4) | P0 |
| B5 | **Quản lý phòng** (con của B3) | CRUD `rooms`: `name`, `max_guests`, `bed_description`, `room_size_sqm`, `room_facilities[]`, ảnh. **Bắt buộc** — booking gắn vào `room_id`, hotel không có room thì không bán được | P0 |
| B6 | **Quản lý giá phòng** (con của B5) | CRUD `room_prices` theo khoảng ngày: `price`, `currency`, `sold_out`. **ĐÃ CHỐT: admin được sửa giá** → mọi thao tác ghi phải vào audit log (E1). Với hotel ETL, giá sửa tay sẽ bị `ota_pipeline` ghi đè — xem R1 | P0 |
| B7 | Trạng thái embedding | Cột/panel: đã embed / chưa · nút "Re-embed khách sạn này" → set NULL + trigger DAG (V3). Chỉ áp dụng cho `hotels`/`rooms`; **B6 (giá) không liên quan** | P1 |

> Yêu cầu ghi "thêm/xóa/sửa khách sạn" nhưng thực tế **cần tối thiểu 6 màn** vì hotel không tự bán được nếu thiếu room + price.

### Nhóm C — Train/Retrain bot (yêu cầu 2)

| # | Màn hình | Nội dung | Ưu tiên |
|---|---|---|---|
| C1 | Danh sách pipeline | Liệt kê DAG (embed, hotel, ota, google_maps, osm, tour, nearby): lần chạy cuối, trạng thái, thời lượng. Đọc qua Airflow REST API | P0 |
| C2 | Kích hoạt chạy | Form theo DAG. Với `embed_supabase`: chọn `only_null` (backfill) / full re-embed, `force_tables` (hotels/rooms/attractions), `batch_limit`, `chunk_size`. Có confirm cho full re-embed (tốn tiền API + lâu) | P0 |
| C3 | Chi tiết lần chạy + log | Danh sách task, trạng thái từng task, log lỗi. Cho phép retry | P0 |
| C4 | Độ phủ embedding | Đếm `embedding IS NULL` cho `hotels`, `rooms`, `attractions` (3 bảng duy nhất có cột này) → biết còn bao nhiêu dữ liệu bot chưa "học" | P1 |
| C5 | Kết quả đánh giá RAG | Hiển thị kết quả từ `eval/` (RAGAS: context relevance…) để so trước/sau retrain | P2 |

> **ĐÃ CHỐT: người dùng portal KHÔNG có tài khoản Airflow** → nhóm C giữ nguyên phạm vi (C1–C3 là bắt buộc, không rút gọn thành link sang Airflow UI). Backend phải giữ credential Airflow REST phía server, không lộ ra frontend. C3 (log lần chạy) lên **P0** vì không còn đường nào khác để xem lỗi pipeline.

### Nhóm D — Quản lý đơn hàng (yêu cầu 3)

| # | Màn hình | Nội dung | Ưu tiên |
|---|---|---|---|
| D1 | Danh sách đơn hàng | Join `payments` → `bookings` → `rooms` → `hotels`. Cột: mã, khách (từ payments), khách sạn, ngày ở, số phòng, tiền, trạng thái booking + trạng thái thanh toán. Filter: trạng thái, khoảng ngày, khách sạn; tìm theo email/SĐT | P0 |
| D2 | Chi tiết đơn hàng | Thông tin khách, các booking con, timeline (created → reserved/expires_at → confirmed/cancelled), thông tin VNPay, link sang phiên chat gốc (`session_id`) | P0 |
| D3 | Hành động trên đơn | Xác nhận / Hủy — **gọi RPC `confirm_booking_reservation` / `cancel_booking`**, không UPDATE thẳng bảng (RPC giữ advisory lock + state machine) | P0 |
| D4 | Đối soát thanh toán | Danh sách `payments`: lọc PENDING treo quá lâu, PAID nhưng booking chưa CONFIRMED (IPN lỗi), FAILED. Đây là lỗi vận hành thực tế của luồng VNPay IPN | P1 |
| D5 | Lịch phòng / công suất | Xem phòng đã kín theo ngày (đã có view `room_night_occupancy` từ migration 20260820) | P2 |
| D6 | Xuất CSV | Xuất danh sách đơn theo filter cho kế toán | P2 |

### Nhóm E — Xuyên suốt

| # | Màn hình | Nội dung | Ưu tiên |
|---|---|---|---|
| E1 | Nhật ký thao tác (audit log) | Ai sửa giá / hủy đơn / trigger re-embed, lúc nào. Cần **bảng mới** `admin_audit_log`. **Lên P0** vì đã chốt admin được sửa giá (Q5) + hủy đơn (D3) | P0 |
| E2 | Quản lý tài khoản admin | **Bỏ** — đã chốt 1 role `admin` duy nhất, set claim thủ công trong Supabase | — |

---

## 4. Tổng hợp

| Ưu tiên | Số màn hình | Phạm vi |
|---|---|---|
| **P0 (MVP)** | **15** | A1, A2, B1–B6, C1–C3, D1–D3, E1 |
| P1 | 3 | B7, C4, D4 |
| P2 | 5 | A3, C5, D5, D6 |
| **Tổng** | **23** | E2 bị loại (1 admin duy nhất) |

### Backend cần bổ sung (chưa có 1 endpoint admin nào)
- `require_admin` dependency + role claim
- `GET/POST/PATCH/DELETE /admin/hotels`, `/admin/hotels/{id}/rooms`, `/admin/rooms/{id}/prices`
- `POST /admin/hotels/{id}/reembed`
- `GET /admin/pipelines`, `POST /admin/pipelines/{dag_id}/trigger`, `GET /admin/pipelines/runs/{run_id}`
- `GET /admin/orders` (đơn vị = payment), `GET /admin/orders/{id}`, `POST /admin/orders/{id}/cancel|confirm`
- `GET /admin/payments`
- Ghi audit vào `admin_audit_log` ở mọi endpoint mutate (E1)

### Migration cần thêm
- `hotels.is_active boolean NOT NULL DEFAULT true` (V4) + cập nhật `match_hotels_with_rooms` lọc `is_active`
- Bảng `admin_audit_log` (actor, action, entity, entity_id, before/after jsonb, created_at)
- Nới ràng buộc `source_hotel_id NOT NULL` cho hàng `source_platform='manual'` (dùng UUID sinh tay làm `source_hotel_id`)

### Frontend cần bổ sung
- Router (chưa có) + tách bundle `/admin`
- Bộ component bảng/form admin (khác hoàn toàn UI chat hiện tại)

### Thứ tự đề xuất
1. Nền tảng: role claim + `require_admin` + router + layout (A1, A2) — mọi thứ khác phụ thuộc
2. Đơn hàng (D1–D3) — giá trị vận hành cao nhất, chỉ đọc + 2 RPC có sẵn, **rủi ro thấp nhất**
3. Khách sạn (B1–B6) — nặng nhất, phụ thuộc quyết định V2/V3/V4
4. Retrain (C1, C2) — nối vào B7 để đóng vòng "sửa hotel → bot học lại"

---

## 5. Quyết định đã chốt (2026-08-24)

| # | Câu hỏi | Quyết định |
|---|---|---|
| 1 | V2 — chống ETL ghi đè | **`source_platform='manual'`** (không làm `locked_fields`) |
| 2 | V5 — đơn vị "đơn hàng" | **`payment`** (nhiều phòng), booking là dòng chi tiết |
| 3 | V4 — xóa khách sạn | **Soft delete** `is_active` |
| 4 | C — portal user có tài khoản Airflow? | **Không có** → giữ nguyên nhóm C, C3 lên P0 |
| 5 | Admin sửa giá phòng? | **Có** → B6 đầy đủ CRUD, kéo theo E1 lên P0 |
| 6 | Vai trò trung gian? | **Không** — 1 role `admin` duy nhất, E2 bị loại |

---

## 6. Rủi ro còn lại sau các quyết định

**R1 — Sửa giá/thông tin khách sạn ETL vẫn bị pipeline ghi đè.** (Đây là rủi ro ETL, không phải rủi ro RAG — `room_prices` không có embedding, xem V3.)
Chốt (b) chỉ bảo vệ khách sạn `manual`, trong khi Q5 cho phép admin sửa giá — mà phần lớn `room_prices` thuộc hotel ETL. Không xử lý thì admin sửa giá xong DAG chạy là mất.
Cần chọn 1 trong 3 khi làm B3/B6:
- (i) UI chỉ cho sửa khách sạn `source_platform='manual'`, hotel ETL read-only;
- (ii) thêm cờ `is_price_locked` ở `rooms`/`room_prices` để `ota_pipeline` bỏ qua (thực chất là `locked_fields` thu hẹp);
- (iii) chấp nhận ghi đè, UI cảnh báo rõ "giá này do pipeline quản lý".

**R2 — Booking chưa thanh toán không có tên khách.** Đơn vị = payment nên D1 cần tab phụ cho booking PENDING/RESERVED chưa có payment, tránh mất dấu đơn treo/hết hạn.

**R3 — `source_hotel_id NOT NULL`.** Khách sạn tạo tay phải tự sinh `source_hotel_id` (UUID) để không vi phạm khóa `(source_platform, source_hotel_id)`.

**R4 — Credential Airflow.** Portal thay thế hoàn toàn Airflow UI cho nhóm vận hành → backend giữ token Airflow REST, cần giới hạn danh sách DAG được trigger để tránh chạy nhầm pipeline tốn tiền API.
