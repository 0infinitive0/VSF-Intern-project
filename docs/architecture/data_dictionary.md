# V-OTA AI Chat: Từ Điển Dữ Liệu (Data Dictionary)

Tài liệu này cung cấp chi tiết về cấu trúc các bảng trong cơ sở dữ liệu PostgreSQL và Vector DB (Qdrant) cho hệ thống V-OTA AI Chat, bám sát mô hình dữ liệu trong BRD (Hình 4).

## 1. Cấu trúc PostgreSQL (Dữ liệu có cấu trúc)

### 1.1. Bảng `destinations` (Điểm đến)
Lưu trữ thông tin về các địa danh, vùng miền hoặc thành phố lớn. (Trong BRD gọi là "Địa điểm").
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính, tự động sinh (`uuid_generate_v4`) |
| `name` | VARCHAR(100) | UK | Tên địa điểm (VD: Nha Trang, Phú Quốc). Unique — dùng để resolve `destination_id` từ `city` thô của OTA |
| `region` | VARCHAR(100) | | Vùng / miền |
| `aliases` | TEXT[] | | Không null, mặc định `{}`. Các tên thay thế từ người dùng hoặc OTA dùng để resolve về `name` chuẩn, ví dụ `{"TP HCM", "TPHCM", "Sài Gòn"}` cho Hồ Chí Minh |
| `coordinates` | VARCHAR(50) | | Tọa độ GPS |
| `description` | TEXT | | Mô tả tổng quan về địa điểm |
| `created_at` | TIMESTAMP | | Thời gian tạo bản ghi |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật bản ghi |

Terminal trip intake tải cả `name` và `aliases`, chuẩn hóa dấu và chữ hoa/thường,
sau đó đối chiếu theo cụm từ đầy đủ. Giá trị được giữ trong trạng thái và truyền
sang planner luôn là `name` chuẩn; alias không thay thế tên chuẩn trong lịch trình.

### 1.2. Bảng `hotels` (Khách sạn)
Lưu trữ thông tin cốt lõi của các cơ sở lưu trú được thu thập từ OTA. **Quy ước: 1 dòng = 1 khách sạn theo 1 OTA** (`source_platform` + `source_hotel_id`), KHÔNG gộp — một khách sạn vật lý xuất hiện trên cả Agoda và Booking sẽ có 2 dòng riêng, vì giá và chính sách mỗi OTA khác nhau (giữ cả 2 để chatbot so sánh/tư vấn). Việc gộp khách sạn vật lý trùng nguồn là công việc riêng, chưa triển khai.
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `destination_id` | UUID | FK | Liên kết đến bảng `destinations`. `ON DELETE SET NULL` |
| `source_platform` | VARCHAR(20) | UK | `'agoda'` \| `'booking'` |
| `source_hotel_id` | BIGINT | UK | `hotel_id` gốc từ OTA |
| `source_url` | TEXT | | `property_url` gốc trên OTA |
| `name` | VARCHAR(255) | | Tên khách sạn (VD: Vinpearl Resort Nha Trang) |
| `accommodation_type` | VARCHAR(50) | | Chuẩn hóa lúc ETL (Agoda: nhãn tiếng Việt, Booking: enum tiếng Anh) |
| `description` | TEXT | | Bài viết mô tả tổng quan (chỉ có ở Agoda) |
| `star_rating` | DECIMAL(2,1) | | Hạng sao (0-5, Agoda có nửa sao) |
| `address` | VARCHAR(500) | | Địa chỉ đầy đủ |
| `city` | VARCHAR(100) | | Raw text gốc từ nguồn, dùng `destination_id` cho query chuẩn |
| `area_name` | VARCHAR(100) | | Khu vực |
| `coordinates` | VARCHAR(50) | | Tọa độ GPS (Dùng để tính khoảng cách đi bộ/di chuyển) |
| `amenities` | TEXT[] | | Mảng phẳng tiện ích (VD: Wifi, Hồ bơi) |
| `amenity_groups` | JSONB | | Tiện ích nhóm theo danh mục (cấu trúc khác nhau giữa 2 nguồn) |
| `review_score` | DECIMAL(4,2) | | Điểm đánh giá |
| `review_count` | SMALLINT | | Số lượng đánh giá (tối đa 32767) |
| `category_scores` | JSONB | | Subratings, tên tiêu chí khác nhau giữa 2 nguồn |
| `image_url` | TEXT | | Ảnh đại diện/thumbnail |
| `images` | TEXT[] | | Mảng URL toàn bộ hình ảnh (Gallery) |
| `nearby_attractions` | JSONB | | Cấu trúc khác nhau giữa 2 nguồn (Agoda: list string, Booking: list object) |
| `nearby_essentials` | JSONB | | Tương tự `nearby_attractions` |
| `lowest_price` | DECIMAL(12,2) | | Cache giá thấp nhất tại lần crawl gần nhất (nguồn xác thực là `room_prices`) |
| `created_at` | TIMESTAMP | | Thời gian tạo |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật |

*(Khóa Unique `(source_platform, source_hotel_id)` dùng cho UPSERT khi crawl lại đúng khách sạn/đúng OTA. Danh sách đầy đủ các cột — bao gồm các trường chỉ có ở một nguồn như `awards`, `warnings`, `check_in_time`, v.v. — xem `scripts/database_schema.sql`.)*

**Không lưu ở bảng `hotels` (cố ý):** `country` và `highlights` chỉ tồn tại trong bản ghi đã normalize của ETL — `country` làm khóa dedupe liên-OTA + payload Qdrant, `highlights` ghép vào `embedding_text` — nên không cần cột SQL. `review_text` / `score_distribution` / `offer_count` là dữ liệu chỉ có ở Agoda, không tiêu thụ ở đâu nên đã loại khỏi cả pipeline (xem `_HOTEL_COLUMNS` trong `hotel_pipeline.py`).

### 1.3. Bảng `rooms` (Phòng)
Lưu trữ các loại phòng khác nhau thuộc một khách sạn — theo đúng 1 OTA của khách sạn đó (không gộp liên-nguồn, tương tự `hotels`).
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `hotel_id` | UUID | FK | Liên kết đến `hotels`. `ON DELETE CASCADE` |
| `source_room_id` | BIGINT | UK | `room_id` gốc từ OTA |
| `name` | VARCHAR(255) | | Tên loại phòng (VD: Deluxe Ocean View) |
| `bed_description` | TEXT | | Text thô mô tả giường — không tách thành số lượng/loại vì dữ liệu 2 nguồn tự do, khác ngôn ngữ |
| `room_size_sqm` | DECIMAL(6,2) | | Diện tích phòng (m²) |
| `max_guests` | SMALLINT | | Sức chứa (best-effort). Lưu ý: Agoda chỉ tính người lớn, Booking là tổng khách — 2 nguồn khác ngữ nghĩa, không so sánh trực tiếp liên-nguồn |
| `room_facilities`| TEXT[] | | Các tiện ích riêng có trong phòng này |
| `amenity_groups` | JSONB | | Nullable, chỉ có ở Agoda |
| `images` | TEXT[] | | Mảng URL hình ảnh của phòng |
| `created_at` | TIMESTAMP | | Thời gian tạo |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật |

*(Khóa Unique `(hotel_id, source_room_id)`.)*

### 1.4. Bảng `room_prices` (Giá theo thời điểm)
Lưu trữ giá phòng. Bảng này được thiết kế theo cơ chế UPSERT (cập nhật đè) để chỉ lấy giá mới nhất cho mỗi khoảng thời gian check-in/check-out.
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `room_id` | UUID | FK | Liên kết đến `rooms`. `ON DELETE CASCADE` |
| `price` | DECIMAL(12,2)| | Mức giá phòng |
| `currency` | VARCHAR(10) | | Đơn vị tiền tệ (Mặc định: 'VND') |
| `check_in_date` | DATE | UK | Ngày nhận phòng |
| `check_out_date`| DATE | UK | Ngày trả phòng |
| `sold_out` | BOOLEAN | | Cờ hết phòng (thay cho `available_rooms` cũ — không nguồn nào có số phòng trống thực tế) |
| `crossed_out` | BOOLEAN | | Cờ hiển thị giá gạch ngang (khuyến mãi), chỉ có ở Agoda |
| `source_url` | TEXT | UK | Link chuyển hướng (Affiliate/gốc) trang đặt phòng; fallback dùng `hotels.source_url` nếu không có link riêng |
| `crawled_at` | TIMESTAMP | | Thời điểm hệ thống lấy được giá này |

*(Lưu ý: Khóa Unique là expression index trên tổ hợp `room_id`, `check_in_date`, `check_out_date`, `COALESCE(source_url, '')` để UPSERT chính xác giá mới nhất — dùng `COALESCE` vì Postgres coi mỗi NULL là khác nhau, một `UNIQUE` thường sẽ không dedupe đúng khi cột này NULL.)*

### 1.4a/1.4b. Bảng `hotel_identity_groups` / `hotel_identity_members` (Nhóm khách sạn vật lý trùng lặp liên-OTA)
Nhóm các dòng `hotels` cùng 1 khách sạn vật lý (VD: cùng khách sạn trên cả Agoda và Booking) để AI/RAG không đề xuất trùng lặp — **không gộp dòng `hotels`**, cả hai dòng OTA luôn được giữ nguyên. `review_status` = `'pending_review'` (điểm match `0.72-0.86`) chặn nhóm dùng cho AI/vector cho tới khi duyệt thủ công; chỉ nhóm điểm `>= 0.86` mới `'auto_approved'` ngay. Xem `hotel_pipeline.group_physical_hotels()`/`assign_physical_hotel_groups()` cho thuật toán tính điểm và `plans/260724-0925-hotel-normalize-dedupe-for-vector-rag/phase-03-dedupe-canonical-identity.md` cho thiết kế đầy đủ. Nhóm được **tính trong pipeline** (in-memory) mỗi lần chạy; việc ghi persist vào 2 bảng này chưa gắn vào `load_hotels_to_db()` ở M1/M2.

**Nguồn nạp dữ liệu:** `booking_agoda_hotel_loader_pipeline` (`src/airflow/dags/data_pipeline/hotel_dag.py`) đọc `data/agoda.json` và `data/booking.json`, gọi `hotel_pipeline.py` theo chuỗi Extract -> Validate -> Normalize -> Dedupe -> Load -> QualityCheck. Lần xác thực 2026-07-23 nạp 1,103 khách sạn, 6,375 phòng và 6,375 giá phòng; cross-OTA physical-hotel dedup chưa nằm trong phạm vi M1.

### 1.5. Bảng `attractions` (Điểm tham quan & Nhà hàng)
Lưu trữ thông tin chi tiết về các địa điểm tham quan / nhà hàng tại điểm đến. Cờ `is_tour` là di sản; tour tuyến từ Booking.com nay nằm ở bảng riêng **`tours`** (xem §1.10a).
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `destination_id` | UUID | FK | Liên kết đến `destinations`. `ON DELETE CASCADE` |
| `name` | VARCHAR(255) | | Tên điểm tham quan, Nhà hàng, hoặc Tên Tour |
| `description` | TEXT | | Mô tả chi tiết |
| `category` | VARCHAR(100) | | Phân loại (VD: 'Bảo tàng', 'Biển', 'Tour', 'Nhà hàng') |
| `is_tour` | BOOLEAN | | Cờ đánh dấu nếu đây là Tour tuyến thay vì địa điểm vật lý (`DEFAULT FALSE`) |
| `estimated_duration_minutes` | SMALLINT | | Thời gian tham quan/đi tour dự kiến (phút) |
| `opening_time` | TIME | | Giờ mở cửa |
| `closing_time` | TIME | | Giờ đóng cửa |
| `departure_schedule`| TEXT | | Lịch khởi hành (dành cho Tour - VD: '8h sáng hàng ngày') |
| `ticket_price_adult` | DECIMAL(12, 2) | | Giá vé / Giá Tour (Người lớn) |
| `ticket_price_child` | DECIMAL(12, 2) | | Giá vé / Giá Tour (Trẻ em) |
| `rating` | DECIMAL(3, 2) | | Điểm đánh giá trung bình (Dùng để lọc các địa điểm Must-go) |
| `review_count` | INT | | Số lượng đánh giá (Độ phổ biến) |
| `coordinates` | VARCHAR(50) | | Tọa độ GPS |
| `images` | TEXT[] | | Mảng URL hình ảnh |

### 1.6. Bảng `events` (Sự kiện địa phương)
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `destination_id` | UUID | FK | Thuộc về điểm đến nào |
| `attraction_id` | UUID | FK | Tùy chọn. Thuộc về điểm tham quan nào (nếu có) |
| `name` | VARCHAR(255) | | Tên sự kiện (VD: Lễ hội pháo hoa quốc tế) |
| `description` | TEXT | | Nội dung sự kiện |
| `start_date` | TIMESTAMP | | Thời gian bắt đầu |
| `end_date` | TIMESTAMP | | Thời gian kết thúc |
| `images` | TEXT[] | | Mảng URL hình ảnh |

### 1.7. Bảng `itineraries` (Lịch trình)

Lưu trữ các bản nháp hoặc lịch trình chính thức của một phiên chat.

| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `session_id` | VARCHAR(255)| FK | Thuộc về phiên chat nào |
| `duration_days` | SMALLINT | | Số ngày đi |
| `number_of_adults`| SMALLINT | | Số lượng người lớn |
| `number_of_children`| SMALLINT | | Số lượng trẻ em |
| `budget` | DECIMAL(12, 2) | | Ngân sách ước tính |
| `preferences` | TEXT[] | | Sở thích (Vibe) |
| `day_themes` | JSONB | | Chủ đề và truy vấn semantic search của từng ngày |
| `status` | VARCHAR(50) | | `Draft` hoặc `Finalized`; lịch trình đã Finalized không được chỉnh sửa |
| `destination_id` | UUID | FK | Điểm đến dùng để giới hạn tìm kiếm và tái sử dụng lịch trình |
| `hotel_id` | UUID | FK | Khách sạn được chọn để hydrate và kiểm tra lại lịch trình |
| `summary` | TEXT | | Nội dung chuẩn hóa, ổn định dùng làm đầu vào embedding |
| `parent_itinerary_id` | UUID | FK | Lịch trình mẫu trực tiếp được clone để tạo bản hiện tại |
| `reuse_root_id` | UUID | FK | Lịch trình gốc của lineage, dùng để gộp kết quả semantic search cùng dòng |
| `reuse_count` | INTEGER | | Tổng số hậu duệ đã Finalized; mỗi lần finalize clone sẽ cộng cho parent |
| `embedding` | VECTOR(1024) | | Vector BGE-M3 dùng để tìm lịch trình tương tự |
| `created_at` | TIMESTAMP | | Thời gian tạo lịch trình |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật lịch trình |

### 1.8. Bảng `itinerary_items` (Chi tiết Lịch trình)

Chi tiết từng hoạt động, bữa ăn hoặc khoảng nghỉ trong một lịch trình.

| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `itinerary_id` | UUID | FK | Liên kết đến `itineraries` |
| `day_number` | SMALLINT | | Ngày thứ mấy |
| `order_index` | SMALLINT | | Thứ tự trong ngày |
| `start_time` | TIME | | Giờ bắt đầu dự kiến (Dùng để hiển thị lịch trình) |
| `end_time` | TIME | | Giờ kết thúc dự kiến |
| `reference_type`| VARCHAR(50) | | Phân loại (Hotel, Attraction, Event) |
| `reference_id` | UUID | | ID của dịch vụ được trỏ đến |
| `estimated_cost`| DECIMAL(12, 2) | | Chi phí dự kiến |
| `item_kind` | VARCHAR(20) | | Vai trò của item trong lịch trình: `breakfast`, `attraction`, `lunch`, `rest`, `coffee`, `dinner`, hoặc `evening` |
| `created_at` | TIMESTAMP | | Thời gian tạo |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật |

`reference_type` xác định bảng/loại thực thể được tham chiếu, còn `item_kind`
xác định vai trò của item trong ngày. Ví dụ, một item có thể có
`reference_type = Hotel` và `item_kind = breakfast`, hoặc
`reference_type = Attraction` và `item_kind = lunch` khi nhà hàng được lưu trong
bảng `attractions`.

`poc_trip_planner.py` đã tạo `item_kind` từ `ScheduledItem.kind`. Lớp persistence
ưu tiên `item_kind` và chỉ đọc `kind` làm fallback tương thích cho JSON cũ trước
khi ghi vào Supabase.

### 1.9. Bảng `sessions` (Phiên hội thoại)
Quản lý Context (Ngữ cảnh) cho AI.
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `session_id` | VARCHAR(255) | PK | Khóa chính (ID phiên chat) |
| `context_data` | JSONB | | Lưu trữ profiling (Đi đâu, khi nào, với ai, vibe) |
| `user_id` | UUID | FK | `auth.users.id` (Supabase Auth) — nullable; plan `260814`. Mọi visitor kể cả khách vãng lai đều có row `auth.users` thật qua Anonymous Auth |
| `created_at` | TIMESTAMP | | Thời gian tạo |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật |

### 1.10. Bảng `chat_messages` (Tin nhắn Chat)
Lưu trữ lịch sử hội thoại chi tiết.
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `session_id` | VARCHAR(255) | FK | Thuộc về phiên chat nào. `ON DELETE CASCADE` |
| `sender_type`| VARCHAR(20) | | Người gửi ('user' hoặc 'ai') |
| `message_content`| TEXT | | Nội dung tin nhắn |
| `created_at` | TIMESTAMP | | Thời điểm gửi tin nhắn |

### 1.10a. Bảng `tours` (Tour Booking.com)
Tour tuyến từ Booking.com — tách khỏi `attractions` (migration `20260817_add_tours_table.sql`). Khóa UPSERT `(source_platform, source_id)`; `source_id` là **STRING** (VD `"PRo2nc0TvHBe"`), không phải BIGINT. Cột chính: `destination_id` FK, `name`, `category`, `duration_minutes` / `duration_label`, `price` + `currency` (thường USD), `rating` / `review_count`, `is_bookable`, `has_free_cancellation`, `whats_included` / `not_included` (TEXT[]), `itinerary_details` (JSONB nguyên khối), `images`, `scraped_at`.

### 1.10b. Bảng `bookings` (Giữ chỗ & Đặt phòng)
Plan `260818-vnpay-payment-and-email-confirmation`. Tách hẳn khỏi snapshot giá của crawler. RLS bật, chỉ `service_role`.
| Cột | Kiểu | Mô tả |
| :--- | :--- | :--- |
| `id` | UUID | PK |
| `temporary_user_ref` | TEXT | Định danh khách vãng lai (UUID trong `localStorage`, không cần đăng nhập) |
| `session_id` | VARCHAR(255) FK | Phiên chat tạo hold (nullable, thêm ở `20260819` cho badge sidebar) |
| `room_id` | UUID FK | `ON DELETE RESTRICT` |
| `check_in_date` / `check_out_date` | DATE | `CHECK (check_out > check_in)` |
| `room_count` | INTEGER | `CHECK (> 0)` |
| `status` | TEXT | `PENDING` \| `RESERVED` \| `CONFIRMED` \| `CANCELLED` \| `EXPIRED` |
| `expires_at` | TIMESTAMPTZ | Hạn giữ chỗ (TTL 15'); `NULL` khi `CONFIRMED`. `CHECK (status <> 'RESERVED' OR expires_at IS NOT NULL)` |
| `total_amount` / `currency` | NUMERIC / VARCHAR | |
| `created_at` / `updated_at` / `cancelled_at` | TIMESTAMPTZ | |

Index riêng `bookings_room_dates_idx` chỉ trên `status = 'CONFIRMED'`.

### 1.10c. Bảng `payments` (Thanh toán VNPay)
| Cột | Kiểu | Mô tả |
| :--- | :--- | :--- |
| `id` | UUID | PK; `vnp_TxnRef` = `id` bỏ dấu `-` |
| `temporary_user_ref` | TEXT | NOT NULL |
| `booking_ids` | UUID[] | `CHECK (array_length >= 1)` — 1 thanh toán phủ N booking |
| `amount` | NUMERIC | `CHECK (>= 0)` |
| `currency` | VARCHAR(10) | mặc định `VND` |
| `status` | TEXT | `PENDING` \| `PAID` \| `FAILED` \| `CANCELLED` |
| `guest_name` / `guest_email` / `guest_phone` | TEXT | Nhập ở wizard bước 2 |
| `vnp_transaction_no` / `vnp_response_code` | TEXT | Từ IPN VNPay |
| `paid_at` / `created_at` / `updated_at` | TIMESTAMPTZ | `PAID` chỉ đặt bởi IPN |

### 1.10d. Bảng `amenity_catalog` (Danh mục tiện nghi chuẩn hóa)
Migration `20260821_hotel_preference_catalog_redesign.sql`. `id` là slug `^[a-z0-9_]{1,64}$`. Cột: `label_vi` / `label_en`, `scope` (`hotel` \| `room` \| `both`), `category` (14 enum: accessibility, business, connectivity, facility, family, food, general, language, outdoor, policies, room_comfort, safety, transport, wellness), `icon_key`, `match_keywords` (TEXT[] — dùng để grounding tiện ích từ câu người dùng), `is_approved`. `hotel_node` mở rộng tiện ích cha → con theo bảng này.

### 1.10e. Bảng `admin_audit_log` (Nhật ký admin)
Migration `20260824_add_admin_audit_log.sql`. Ghi lại mọi thao tác ghi của admin lên dữ liệu khách thật: `actor_id` / `actor_email`, `action`, `entity_type`, `entity_id`, `before` / `after` (JSONB), `created_at`. Index theo `created_at DESC` và `(entity_type, entity_id)`.

### 1.11. Các Hàm Stored Procedures / RPC Functions trong Supabase

Các hàm SQL nguyên tử được triển khai trên Supabase để phục vụ tìm kiếm ngữ nghĩa, chuyển trạng thái và lưu gói lịch trình:

| Tên Hàm RPC | Tham Số Đầu Vào | Mục Đích & Mô Tả |
| :--- | :--- | :--- |
| `match_hotels_with_rooms` | `query_embedding vector(1024)`, `match_threshold float`, `match_count int`, `filter_destination_id uuid`, `root_latitude/root_longitude/max_radius_km` (optional), lọc ngày + sức chứa (`20260820`), lọc giá (`20260730`) | RPC tìm khách sạn chính: similarity + lọc bán kính + đêm còn giá live. Ngưỡng mặc định 0.35. |
| `match_attractions` | `query_embedding vector(1024)`, `match_threshold float`, `match_count int`, `filter_destination_id uuid`, radius (optional) | RPC tìm điểm tham quan / nhà hàng theo theme. Ngưỡng mặc định 0.40. |
| `match_itineraries` | `query_embedding vector(1024)`, `match_threshold float`, `match_count int`, `filter_destination_id uuid`, `filter_duration_days smallint`, `filter_hotel_id uuid` | Tìm kiếm semantic search các lịch trình mẫu đã Finalized trong `pgvector` với bộ lọc cứng theo điểm đến, số ngày và đúng khách sạn người dùng đã chọn. Gom nhóm khử trùng cùng lineage bằng `DISTINCT ON (COALESCE(reuse_root_id, id))`. |
| `finalize_itinerary` | `p_itinerary_id uuid`, `p_summary text` | Chuyển trạng thái lịch trình từ `Draft` sang `Finalized` nguyên tử (`FOR UPDATE` row lock), tự động cộng `reuse_count` cho `parent_itinerary_id` đúng 1 lần (Idempotent). |
| `persist_itinerary_bundle` | `p_itinerary jsonb`, `p_items jsonb` | Ghi nguyên tử toàn bộ lịch trình (Metadata + danh sách tất cả các `itinerary_items`) vào PostgreSQL trong 1 transaction. |
| `create_booking_reservation` / `confirm_booking_reservation` / `cancel_booking` | xem `20260818_add_booking_reservation_rpcs.sql`, `20260819_add_guest_single_hotel_hold_guard.sql` | Giữ chỗ (advisory lock theo `room_id` + `guest_ref`, chặn giữ 2 khách sạn), xác nhận sau IPN VNPay, huỷ. `SECURITY DEFINER`. |
| Admin RPCs | `20260824_add_admin_*` | View đơn hàng, upsert `room_prices`, tạo `source_id` thủ công cho hotel/room, view khách sạn admin. |

---

## 2. Cấu trúc Vector Database (Qdrant & Supabase pgvector)
Hệ thống sử dụng Vector DB để xử lý các truy vấn tìm kiếm ngữ nghĩa bằng ngôn ngữ tự nhiên (`bge-m3`, dimension 1024).
- **Supabase pgvector:** Dùng cho bảng `itineraries` (`embedding vector(1024)`), gọi trực tiếp qua RPC `match_itineraries`.
- **Qdrant Vector DB:** Dùng cho các collection `hotels_vector`, `attractions_vector`, và `rooms_vector` (`src/services/qdrant_schema.py`).

### 2.1. Collection: `hotels_vector`
Lưu trữ vector của Khách sạn. **Đã triển khai** (`hotel_pipeline.build_hotel_embedding_text()`/`build_hotel_payload()`, xem `plans/260724-0925-hotel-normalize-dedupe-for-vector-rag/phase-02-field-normalize-contract.md`). Kết nối/embed thật vào Qdrant hiện qua `scripts/sync_accommodations_to_qdrant.py`; việc gắn `destination_id`/`canonical_hotel_key` vào payload và chạy từ Airflow DAG thuộc `plans/260727-1113-qdrant-vector-store-correctness-and-hybrid-retrieval/phase-04-airflow-runtime-and-supabase-hotel-load.md` trở đi (chưa triển khai).

`embedding_text` gộp có thứ tự: `Hotel: {name}` → `Destination: {destination_name}, {area_name}` → `Type: {accommodation_type}; Stars: {star_rating}` → `Description: {description}` (cắt 500 ký tự) → `Amenities: {top 10}` → `Highlights: {top 5}` → `Nearby: {top 5 tên}`. Loại trừ các trường biến động (giá chính xác, source URL, `scraped_at`, room ID, JSON thô) — các trường này nằm ở `grounding_facts` thay vì embedding text.

**Cấu trúc Payload (Metadata dùng để Pre-filtering) — như `hotel_pipeline.build_hotel_payload()` trả về:**
```json
{
    "source_platform": "agoda",
    "source_hotel_id": 12345,
    "name": "Vinpearl Resort Nha Trang",
    "destination_name": "Nha Trang",
    "area_name": "...",
    "country": "VN",
    "star_rating": 5.0,
    "accommodation_type": "hotel",
    "min_price": 3000000,
    "currency": "VND",
    "price_tier": "budget | mid_range | luxury (chỉ tính cho VND)",
    "amenity_keys": ["ho_boi", "wifi"],
    "lat": 12.238791,
    "lon": 106.660172
}
```
`destination_id` (UUID) join với PostgreSQL sẽ được bổ sung ở bước indexing thật (roadmap Phase 2) vì `destination_id` chỉ được resolve lúc `load_hotels_to_db()` gọi `get_or_create_destination()`, sau khi payload này đã tính xong.

### 2.2. Collection: `attractions_vector`
Lưu trữ vector của Điểm tham quan và Tour tuyến. Vector được tạo từ: Tên + Mô tả + Thể loại.
**Cấu trúc Payload (Metadata dùng để Pre-filtering):**
```json
{
    "attraction_id": "UUID (Khóa ngoại trỏ về PostgreSQL)",
    "name": "Tên điểm tham quan hoặc Tour",
    "destination_id": "UUID (Dùng để lọc theo thành phố)",
    "category": "Tour",
    "is_tour": true,
    "ticket_price_range": "Dưới 500k"
}
```

### 2.3. Collection: `rooms_vector`
Lưu trữ vector của Phòng khách sạn. Vector được tạo từ: Tên phòng + Loại giường + Tiện ích phòng + Hướng nhìn (View).
**Cấu trúc Payload (Metadata dùng để Pre-filtering):**
```json
{
    "room_id": "UUID (Khóa chính của bảng rooms)",
    "hotel_id": "UUID (Khóa ngoại trỏ về bảng hotels)",
    "name": "Tên phòng",
    "max_guests": 2,
    "room_size_sqm": 35.0,
    "view": "Hướng biển"
}
```
