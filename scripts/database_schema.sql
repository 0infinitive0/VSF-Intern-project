-- V-OTA AI Chat: PostgreSQL Database Schema

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Bảng 1: Điểm đến (Destinations - Tỉnh/Thành phố hoặc Khu vực)
CREATE TABLE destinations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    region VARCHAR(100), -- Vùng / miền
    coordinates VARCHAR(50), -- Tọa độ (Lat, Long)
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 2: Thông tin Khách sạn / Resort (Hotels)
CREATE TABLE hotels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    destination_id UUID REFERENCES destinations(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    star_rating SMALLINT CHECK (star_rating >= 1 AND star_rating <= 5),
    amenities TEXT[], -- Lưu mảng các tiện ích, ví dụ: '{"Hồ bơi", "Spa", "Wifi"}'
    coordinates VARCHAR(50), -- Tọa độ GPS (VD: '10.762622, 106.660172') để tính khoảng cách đi bộ
    images TEXT[], -- Mảng URL hình ảnh cho Gallery
    videos TEXT[], -- Mảng URL video dọc cho Modal
    source_urls TEXT[], -- Mảng các link gốc (Booking, Agoda...) nếu khách sạn bị trùng (Deduplicated)
    source_ids TEXT[], -- Mảng các ID gốc trên OTA để đối chiếu
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 3: Thông tin Loại Phòng (Rooms)
CREATE TABLE rooms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    hotel_id UUID REFERENCES hotels(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    max_adults SMALLINT DEFAULT 2, -- Số người lớn tối đa
    max_children SMALLINT DEFAULT 0, -- Số trẻ em tối đa ngủ cùng
    number_of_beds SMALLINT, -- Số lượng giường
    bed_type VARCHAR(100), -- Loại giường (VD: 1 Giường đôi siêu lớn, 2 giường đơn)
    room_facilities TEXT[], -- Tiện ích riêng của phòng
    images TEXT[], -- Mảng URL hình ảnh của phòng
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 4: Giá phòng (Room Prices - Chỉ lưu giá mới nhất theo ngày check-in/check-out)
CREATE TABLE room_prices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    room_id UUID REFERENCES rooms(id) ON DELETE CASCADE,
    price DECIMAL(12, 2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'VND',
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    source_url TEXT NOT NULL, -- Link affiliate/gốc trang đặt phòng
    package_details TEXT, -- VD: 'Bao gồm bữa sáng, Không hoàn tiền'
    available_rooms SMALLINT, -- Số phòng còn trống ở mức giá này (cảnh báo khan hiếm)
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Unique constraint để cho phép thao tác UPSERT (ON CONFLICT DO UPDATE)
    UNIQUE(room_id, check_in_date, check_out_date, source_url, package_details) 
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
