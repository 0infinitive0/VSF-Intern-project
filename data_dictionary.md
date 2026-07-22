# V-OTA AI Chat: Từ Điển Dữ Liệu (Data Dictionary)

Tài liệu này cung cấp chi tiết về cấu trúc các bảng trong cơ sở dữ liệu PostgreSQL và Vector DB (Qdrant) cho hệ thống V-OTA AI Chat, bám sát mô hình dữ liệu trong BRD (Hình 4).

## 1. Cấu trúc PostgreSQL (Dữ liệu có cấu trúc)

### 1.1. Bảng `destinations` (Điểm đến)
Lưu trữ thông tin về các địa danh, vùng miền hoặc thành phố lớn. (Trong BRD gọi là "Địa điểm").
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính, tự động sinh (`uuid_generate_v4`) |
| `name` | VARCHAR(100) | | Tên địa điểm (VD: Nha Trang, Phú Quốc) |
| `region` | VARCHAR(100) | | Vùng / miền |
| `coordinates` | VARCHAR(50) | | Tọa độ GPS |
| `description` | TEXT | | Mô tả tổng quan về địa điểm |
| `created_at` | TIMESTAMP | | Thời gian tạo bản ghi |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật bản ghi |

### 1.2. Bảng `hotels` (Khách sạn)
Lưu trữ thông tin cốt lõi của các cơ sở lưu trú được thu thập từ OTA.
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `destination_id` | UUID | FK | Liên kết đến bảng `destinations`. `ON DELETE SET NULL` |
| `name` | VARCHAR(255) | | Tên khách sạn (VD: Vinpearl Resort Nha Trang) |
| `description` | TEXT | | Bài viết mô tả tổng quan |
| `star_rating` | SMALLINT | | Hạng sao (1-5) |
| `amenities` | TEXT[] | | Mảng các tiện ích (VD: Wifi, Hồ bơi) |
| `coordinates` | VARCHAR(50) | | Tọa độ GPS (Dùng để tính khoảng cách đi bộ/di chuyển) |
| `images` | TEXT[] | | Mảng URL hình ảnh ngang (Gallery) |
| `videos` | TEXT[] | | Mảng URL video dọc |
| `source_urls` | TEXT[] | | Mảng các link gốc đến khách sạn trên nhiều OTA |
| `source_ids` | TEXT[] | | Mảng các ID gốc của khách sạn trên các hệ thống OTA |
| `created_at` | TIMESTAMP | | Thời gian tạo |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật |

### 1.3. Bảng `rooms` (Phòng)
Lưu trữ các loại phòng khác nhau thuộc một khách sạn.
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `id` | UUID | PK | Khóa chính |
| `hotel_id` | UUID | FK | Liên kết đến `hotels`. `ON DELETE CASCADE` |
| `name` | VARCHAR(255) | | Tên loại phòng (VD: Deluxe Ocean View) |
| `max_adults` | SMALLINT | | Số lượng người lớn tối đa |
| `max_children` | SMALLINT | | Số lượng trẻ em tối đa ngủ cùng |
| `number_of_beds` | SMALLINT | | Số lượng giường |
| `bed_type` | VARCHAR(100) | | Loại giường (VD: 1 King, 2 Twin) |
| `room_facilities`| TEXT[] | | Các tiện ích riêng có trong phòng này |
| `images` | TEXT[] | | Mảng URL hình ảnh của phòng |
| `created_at` | TIMESTAMP | | Thời gian tạo |
| `updated_at` | TIMESTAMP | | Thời gian cập nhật |

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
| `source_url` | TEXT | UK | Link chuyển hướng (Affiliate/gốc) trang đặt phòng |
| `package_details`| TEXT | UK | Gói đi kèm (VD: 'Bữa sáng miễn phí', 'Không hoàn tiền') |
| `available_rooms`| SMALLINT | | Số lượng phòng còn trống tại mức giá này |
| `crawled_at` | TIMESTAMP | | Thời điểm hệ thống lấy được giá này |

*(Lưu ý: Khóa Unique là tổ hợp của `room_id`, `check_in_date`, `check_out_date`, `source_url`, `package_details` để UPSERT chính xác giá mới nhất cho từng nền tảng và từng gói tiện ích).*

### 1.5. Bảng `attractions` (Điểm tham quan & Tour)
Lưu trữ thông tin chi tiết về các địa điểm tham quan hoặc các Tour tuyến hoạt động tại điểm đến.
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
| `status` | VARCHAR(50) | | 'Draft' hoặc 'Finalized' |

### 1.8. Bảng `itinerary_items` (Chi tiết Lịch trình)
Chi tiết từng điểm đến (khách sạn, tour, điểm tham quan) trong một lịch trình.
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

### 1.9. Bảng `sessions` (Phiên hội thoại)
Quản lý Context (Ngữ cảnh) cho AI.
| Tên Cột | Kiểu Dữ Liệu | Khóa | Ràng Buộc / Mô Tả |
| :--- | :--- | :--- | :--- |
| `session_id` | VARCHAR(255) | PK | Khóa chính (ID phiên chat) |
| `context_data` | JSONB | | Lưu trữ profiling (Đi đâu, khi nào, với ai, vibe) |
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

---

## 2. Cấu trúc Qdrant (Dữ liệu Vector Ngữ nghĩa)
Hệ thống sử dụng Qdrant làm Vector Database để xử lý các truy vấn tìm kiếm ngữ nghĩa (Semantic Search) bằng ngôn ngữ tự nhiên.
- **Model Nhúng (Embedding Model):** OpenAI `text-embedding-3-small` (Đề xuất vì hỗ trợ Tiếng Việt cực tốt).
- **Vector Size (Kích thước):** `1536`
- **Distance Metric:** `Cosine`

### 2.1. Collection: `hotels_vector`
Lưu trữ vector của Khách sạn. Vector được tạo ra từ chuỗi văn bản gộp giữa: Tên khách sạn + Mô tả + Tiện ích.
**Cấu trúc Payload (Metadata dùng để Pre-filtering):**
```json
{
    "hotel_id": "UUID (Khóa ngoại trỏ về PostgreSQL)",
    "name": "Tên khách sạn",
    "destination_id": "UUID (Dùng để lọc cứng theo thành phố trước khi search vector)",
    "star_rating": 5.0,
    "price_tier": "Budget / Mid-range / Luxury",
    "amenities": ["Hồ bơi", "Spa", "Đưa đón sân bay"]
}
```

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
