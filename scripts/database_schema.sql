-- V-OTA AI Chat: PostgreSQL Database Schema

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Bảng 1: Điểm đến (Destinations - Tỉnh/Thành phố hoặc Khu vực)
CREATE TABLE destinations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE, -- Khóa UPSERT khi resolve destination từ city thô của OTA
    region VARCHAR(100), -- Vùng / miền
    aliases TEXT[], -- Các biến thể tên gặp trong dữ liệu OTA (VD: '{"Nha Trang", "Nha Trang City"}')
    coordinates VARCHAR(50), -- Tọa độ (Lat, Long)
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 2: Thông tin Khách sạn / Resort (Hotels)
-- Quy ước: 1 dòng = 1 khách sạn theo 1 OTA (source_platform + source_hotel_id), KHÔNG gộp.
-- Agoda/Booking dù trùng khách sạn vật lý — giá và chính sách mỗi OTA khác nhau, giữ cả 2 để
-- chatbot so sánh/tư vấn. Việc gộp khách sạn vật lý trùng nguồn là việc khác, chưa làm ở đây.
--
-- KHÔNG lưu ở bảng này (cố ý): country và highlights chỉ được tính trong ETL — country dùng làm
-- khóa dedupe liên-OTA + payload Qdrant, highlights ghép vào embedding_text — nên không cần cột
-- SQL. review_text / score_distribution / offer_count là dữ liệu chỉ có ở Agoda, không tiêu thụ ở
-- đâu nên bị loại bỏ khỏi cả pipeline (xem _HOTEL_COLUMNS trong hotel_pipeline.py).
CREATE TABLE hotels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    destination_id UUID REFERENCES destinations(id) ON DELETE SET NULL,
    source_platform VARCHAR(20) NOT NULL, -- 'agoda' | 'booking'
    source_hotel_id BIGINT NOT NULL, -- hotel_id gốc từ OTA
    source_url TEXT, -- property_url gốc trên OTA
    name VARCHAR(255) NOT NULL,
    accommodation_type VARCHAR(50), -- Chuẩn hóa lúc ETL (Agoda: nhãn tiếng Việt, Booking: enum tiếng Anh)
    description TEXT, -- Chỉ có ở Agoda
    star_rating DECIMAL(2, 1), -- Agoda có nửa sao (3.5) và cả 0 (chưa xếp hạng)
    address VARCHAR(500),
    city VARCHAR(100), -- Raw text gốc từ nguồn, dùng destination_id cho query chuẩn
    area_name VARCHAR(100),
    location_highlight VARCHAR(255), -- Chỉ có ở Agoda
    coordinates VARCHAR(50), -- Tọa độ GPS (VD: '10.762622, 106.660172') để tính khoảng cách đi bộ
    amenities TEXT[], -- Mảng phẳng tiện ích, ví dụ: '{"Hồ bơi", "Spa", "Wifi"}'
    amenity_groups JSONB, -- Tiện ích nhóm theo danh mục (cấu trúc khác nhau giữa 2 nguồn)
    awards TEXT[], -- Chỉ có ở Agoda
    warnings TEXT[],
    review_score DECIMAL(4, 2),
    review_count SMALLINT,
    category_scores JSONB, -- Subratings, tên tiêu chí khác nhau giữa 2 nguồn
    check_in_time VARCHAR(20),
    check_in_until VARCHAR(20),
    check_out_time VARCHAR(20),
    reception_open_until VARCHAR(50), -- Chỉ có ở Agoda
    image_url TEXT, -- Ảnh đại diện/thumbnail
    images TEXT[], -- Mảng URL toàn bộ hình ảnh cho Gallery
    image_count SMALLINT,
    nearby_attractions JSONB, -- Cấu trúc khác nhau giữa 2 nguồn (Agoda: list string, Booking: list object)
    nearby_essentials JSONB,
    lowest_price DECIMAL(12, 2), -- Cache giá thấp nhất tại lần crawl gần nhất (nguồn xác thực là room_prices)
    currency VARCHAR(10),
    price_check_in_date DATE,
    price_check_out_date DATE,
    rooms_available BOOLEAN, -- Agoda: bool gốc; Booking: số phòng còn trống (int) ép về (>0) lúc ETL
    scraped_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_platform, source_hotel_id) -- Khóa UPSERT khi crawl lại đúng khách sạn/đúng OTA
);

-- Bảng 3: Thông tin Loại Phòng (Rooms) — theo đúng 1 OTA của khách sạn đó
CREATE TABLE rooms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    hotel_id UUID REFERENCES hotels(id) ON DELETE CASCADE,
    source_room_id BIGINT NOT NULL, -- room_id gốc từ OTA
    name VARCHAR(255) NOT NULL,
    bed_description TEXT, -- Text thô (VD: '1 giường đơn', '1 Large double bed') — không tách number_of_beds/bed_type
                          -- vì dữ liệu 2 nguồn tự do, khác ngôn ngữ, không tin cậy để parse cứng
    room_size_sqm DECIMAL(6, 2), -- Diện tích phòng (m²), parse từ "20 m²"
    max_occupancy_raw VARCHAR(100), -- Text/số gốc mô tả sức chứa, giữ nguyên để không mất ngữ cảnh
    max_guests SMALLINT, -- Parse best-effort. LƯU Ý: Agoda chỉ tính người lớn, Booking là tổng khách
                         -- — 2 nguồn khác ngữ nghĩa, không so sánh trực tiếp liên-nguồn
    view VARCHAR(255),
    room_facilities TEXT[], -- Tiện ích riêng của phòng (flatten amenity_groups với Agoda)
    amenity_groups JSONB, -- Nullable, chỉ có ở Agoda
    images TEXT[], -- Mảng URL hình ảnh của phòng
    image_count INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hotel_id, source_room_id)
);

-- Bảng 4: Giá phòng (Room Prices - Chỉ lưu giá mới nhất theo ngày check-in/check-out)
CREATE TABLE room_prices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    room_id UUID REFERENCES rooms(id) ON DELETE CASCADE,
    price DECIMAL(12, 2),
    currency VARCHAR(10) DEFAULT 'VND',
    check_in_date DATE,
    check_out_date DATE,
    sold_out BOOLEAN DEFAULT FALSE, -- Thay cho available_rooms cũ: không nguồn nào có số phòng trống, chỉ có cờ hết phòng
    crossed_out BOOLEAN DEFAULT FALSE, -- Cờ hiển thị giá gạch ngang (khuyến mãi). Chỉ có ở Agoda, không kèm giá gốc
    review_score DECIMAL(4, 2), -- Review điểm theo phòng, chỉ có ở Agoda
    review_text VARCHAR(100),
    source_url TEXT, -- Link affiliate/gốc trang đặt phòng; fallback dùng hotels.source_url nếu không có link riêng
    package_details TEXT, -- VD: 'Bao gồm bữa sáng, Không hoàn tiền' — 2 nguồn hiện tại chưa cung cấp field này
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Expression unique index (không dùng UNIQUE(...) thường trong CREATE TABLE) vì source_url/
-- package_details có thể NULL — Postgres coi mỗi NULL là khác nhau nên UNIQUE thường sẽ không
-- dedupe đúng lúc UPSERT. COALESCE về '' để NULL so khớp được với nhau.
CREATE UNIQUE INDEX ux_room_prices_natural_key ON room_prices (
    room_id,
    check_in_date,
    check_out_date,
    COALESCE(source_url, ''),
    COALESCE(package_details, '')
);

-- Bảng 4a: Nhóm khách sạn vật lý trùng lặp liên-OTA (cross-OTA physical-hotel identity groups)
-- Không gộp dòng hotels — bảng này chỉ nhóm các dòng hotels cùng 1 khách sạn vật lý để AI/RAG
-- không đề xuất trùng lặp. review_status 'pending_review' (điểm 0.72-0.86) CHẶN nhóm dùng cho
-- AI/vector cho tới khi duyệt thủ công; chỉ nhóm điểm >= 0.86 mới 'auto_approved' ngay.
-- Nhóm được tính trong pipeline (xem hotel_pipeline.py group_physical_hotels); ghi bảng này là
-- việc riêng, chưa gắn vào load_hotels_to_db ở M2 (xem rủi ro "Extra schema slows M2" trong
-- plans/260724-0925-hotel-normalize-dedupe-for-vector-rag/phase-03-dedupe-canonical-identity.md).
CREATE TABLE hotel_identity_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_hotel_id UUID REFERENCES hotels(id) ON DELETE SET NULL, -- dòng hotels đại diện (tên/toạ độ đầy đủ nhất)
    display_name VARCHAR(255) NOT NULL,
    review_status VARCHAR(20) NOT NULL DEFAULT 'auto_approved', -- 'auto_approved' | 'pending_review' | 'rejected'
    confidence DECIMAL(4, 3) NOT NULL, -- điểm match cao nhất trong nhóm, 0-1
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CHECK (review_status IN ('auto_approved', 'pending_review', 'rejected'))
);

-- Bảng 4b: Thành viên của mỗi nhóm khách sạn vật lý — mỗi dòng hotels chỉ thuộc tối đa 1 nhóm
CREATE TABLE hotel_identity_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id UUID REFERENCES hotel_identity_groups(id) ON DELETE CASCADE,
    hotel_id UUID REFERENCES hotels(id) ON DELETE CASCADE,
    pair_confidence DECIMAL(4, 3), -- điểm match riêng của dòng hotels này so với canonical_hotel_id
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hotel_id)
);

-- Bảng 5: Điểm tham quan / Hoạt động (Attractions)
CREATE TABLE attractions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    destination_id UUID REFERENCES destinations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100), -- VD: 'Bảo tàng', 'Thiên nhiên', 'Vui chơi giải trí', 'Tour', 'Nhà hàng'
    is_tour BOOLEAN DEFAULT FALSE, -- Cờ đánh dấu nếu đây là Tour tuyến (Guided tour) thay vì địa điểm vật lý
    estimated_duration_minutes SMALLINT, -- Thời gian tham quan/tour dự kiến (phút)
    opening_time TIME,
    closing_time TIME,
    departure_schedule TEXT, -- VD: '8h sáng hằng ngày' (chủ yếu dùng cho Tour)
    ticket_price_adult DECIMAL(12, 2), -- Giá vé/Giá tour cho người lớn
    ticket_price_child DECIMAL(12, 2), -- Giá vé/Giá tour cho trẻ em
    rating DECIMAL(3, 2),
    review_count INT,
    coordinates VARCHAR(50), -- Tọa độ (Lat, Long)
    images TEXT[], -- Mảng URL hình ảnh
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 6: Sự kiện địa phương (Events)
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    destination_id UUID REFERENCES destinations(id) ON DELETE CASCADE,
    attraction_id UUID REFERENCES attractions(id) ON DELETE CASCADE, -- Tùy chọn, nếu sự kiện diễn ra tại một khu vui chơi cụ thể
    name VARCHAR(255) NOT NULL,
    description TEXT,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    images TEXT[], -- Mảng URL hình ảnh
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 7: Quản lý Phiên (Session/Context) cho AI
CREATE TABLE sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    context_data JSONB, -- Lưu trữ profiling (Đi đâu, khi nào, với ai, vibe)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 8: Tin nhắn Chat (Lịch sử hội thoại)
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL, -- 'user' hoặc 'ai'
    message_content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 9: Lịch trình (Itineraries)
CREATE TABLE itineraries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE SET NULL,
    duration_days SMALLINT, -- Số ngày của lịch trình
    number_of_adults SMALLINT DEFAULT 1, -- Số lượng người lớn
    number_of_children SMALLINT DEFAULT 0, -- Số lượng trẻ em
    budget DECIMAL(12, 2), -- Ngân sách
    preferences TEXT[], -- Sở thích
    status VARCHAR(50) DEFAULT 'Draft', -- Trạng thái (Draft, Finalized)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 10: Mục lịch trình (Itinerary Items)
CREATE TABLE itinerary_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    itinerary_id UUID REFERENCES itineraries(id) ON DELETE CASCADE,
    day_number SMALLINT NOT NULL, -- Ngày thứ mấy trong lịch trình
    order_index SMALLINT NOT NULL, -- Thứ tự trong ngày
    start_time TIME, -- Giờ bắt đầu dự kiến
    end_time TIME, -- Giờ kết thúc dự kiến
    reference_type VARCHAR(50) NOT NULL, -- 'Hotel', 'Attraction', 'Event'
    reference_id UUID NOT NULL, -- ID trỏ đến bảng tương ứng
    estimated_cost DECIMAL(12, 2), -- Chi phí dự tính
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

/*
=========================================================
QDRANT VECTOR DATABASE SCHEMA (Mô phỏng Metadata Payload)
=========================================================
Collection Name: hotels_vector
Vector Size: 768 (hoặc 1536 tùy vào mô hình Embedding)
Distance Metric: Cosine

Payload Structure (Metadata):
{
    "hotel_id": "UUID string (Map trực tiếp với bảng hotels ở trên)",
    "name": "Vinpearl Resort Nha Trang",
    "destination_id": "UUID string",
    "star_rating": 5,
    "amenities": ["Hồ bơi", "Spa", "Wifi miễn phí"]
}
*/
