-- V-OTA AI Chat: PostgreSQL Database Schema

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Bảng 1: Điểm đến (Destinations - Tỉnh/Thành phố hoặc Khu vực)
CREATE TABLE destinations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE, -- Khóa UPSERT khi resolve destination từ city thô của OTA
    region VARCHAR(100), -- Vùng / miền
    aliases TEXT[] NOT NULL DEFAULT '{}'::TEXT[], -- Tên thay thế từ người dùng/OTA để resolve tên chuẩn
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
    amenities TEXT[], -- Canonical amenity_catalog IDs, e.g. '{"swimming_pool", "wifi"}'
    embedding vector(1024), -- Semantic hotel-search vector
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
    room_facilities TEXT[], -- Canonical amenity_catalog IDs for this room
    available_room_count INTEGER CHECK (available_room_count >= 0), -- Latest inventory snapshot for this room type; it is not date-specific
    embedding vector(1024), -- Semantic room-search vector
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
    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Expression unique index (không dùng UNIQUE(...) thường trong CREATE TABLE) vì source_url
-- có thể NULL — Postgres coi mỗi NULL là khác nhau nên UNIQUE thường sẽ không
-- dedupe đúng lúc UPSERT. COALESCE về '' để NULL so khớp được với nhau.
CREATE UNIQUE INDEX ux_room_prices_natural_key ON room_prices (
    room_id,
    check_in_date,
    check_out_date,
    COALESCE(source_url, '')
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
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE, -- Chủ sở hữu (kể cả user ẩn danh), thêm ở migration 20260814
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sessions_user_id_updated_at ON sessions (user_id, updated_at DESC);

-- Bảng 8: Tin nhắn Chat (Lịch sử hội thoại)
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL, -- 'user' hoặc 'ai'
    message_content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Dữ kiện của khối thinking cho lượt sinh ra tin nhắn này (dữ kiện, KHÔNG
    -- phải câu chữ — câu chữ do FE dựng theo ngôn ngữ đang chọn).
    -- NULL với mọi tin nhắn có trước cột này, và đó là đường chính.
    thinking_trace JSONB
);

-- Bảng 9: Lịch trình (Itineraries)
CREATE TABLE itineraries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE SET NULL,
    start_date DATE, -- Ngày nhận phòng / bắt đầu chuyến đi
    end_date DATE, -- Ngày trả phòng (exclusive), được tính từ start_date + duration_days
    duration_days SMALLINT, -- Số ngày của lịch trình
    number_of_adults SMALLINT DEFAULT 1, -- Số lượng người lớn
    number_of_children SMALLINT DEFAULT 0, -- Số lượng trẻ em
    budget DECIMAL(12, 2), -- Ngân sách
    preferences TEXT[], -- Sở thích
    day_themes JSONB NOT NULL DEFAULT '[]'::jsonb, -- Chủ đề theo ngày: [{day_number, title, query}]
    planning_constraints JSONB NOT NULL DEFAULT '{}'::jsonb, -- Ràng buộc người dùng cần giữ qua các lần chỉnh sửa
    status VARCHAR(50) DEFAULT 'Draft', -- Trạng thái (Draft, Finalized)
    destination_id UUID REFERENCES destinations(id) ON DELETE SET NULL, -- Lọc reuse chính xác theo điểm đến
    hotel_id UUID REFERENCES hotels(id) ON DELETE SET NULL, -- Khách sạn đã chọn để hydrate/revalidate
    summary TEXT, -- Input embedding xác định, không chứa dữ liệu biến động
    parent_itinerary_id UUID REFERENCES itineraries(id) ON DELETE SET NULL,
    reuse_root_id UUID REFERENCES itineraries(id) ON DELETE SET NULL,
    reuse_count INTEGER NOT NULL DEFAULT 0 CHECK (reuse_count >= 0), -- Total finalized descendants
    embedding vector(1024),
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
    item_kind VARCHAR(20) CHECK (item_kind IN ('breakfast', 'attraction', 'lunch', 'rest', 'coffee', 'dinner', 'evening')),
    route_to_next JSONB, -- Lưu tuyến đường đến điểm tiếp theo {"distance_km": float, "duration_mins": float, "polyline": string}
    route_from_hotel JSONB, -- Lưu tuyến đường từ khách sạn đến điểm đầu tiên
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bảng 11: Tour / Hoạt động du lịch (Tours) — dữ liệu OTA từ Booking.com qua
-- Apify actor (xem backend/src/airflow/dags/data_pipeline/tour_pipeline.py).
-- Một dòng / (source_platform, source_id), cùng tinh thần với hotels: không
-- gộp tour trùng liên-OTA ở bảng này, giữ nguyên từng bản ghi để so sánh giá.
CREATE TABLE tours (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    destination_id UUID REFERENCES destinations(id) ON DELETE SET NULL,
    source_platform VARCHAR(20) NOT NULL, -- 'booking'
    source_id VARCHAR(50) NOT NULL, -- tour_id gốc — STRING (VD "PRo2nc0TvHBe"), không phải BIGINT
    source_url TEXT, -- tour_url
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100), -- Chuẩn hóa từ taxonomy_type ("Tours"/"Tour du lịch" → "Tours")
    duration_minutes SMALLINT, -- Parse từ duration_iso (VD "PT10H") khi có thể
    duration_label VARCHAR(100), -- Text thô (VD "10 giờ - 12 giờ"), fallback khi không parse được
    price DECIMAL(12, 2), -- Chỉ 1 mức giá/người, Booking tour không tách người lớn/trẻ em
    currency VARCHAR(10), -- VD 'USD' — khác hotels/room_prices thường là VND
    rating DECIMAL(3, 2),
    review_count INT,
    category_scores JSONB, -- Subrating lồng nhau (facilitiesRating, easyToAccess...)
    has_free_cancellation BOOLEAN,
    is_bookable BOOLEAN,
    whats_included TEXT[],
    not_included TEXT[],
    highlights TEXT[], -- Tag nổi bật (VD 'guest_pickup')
    accessibility TEXT[],
    restrictions TEXT[],
    additional_info TEXT,
    image_url TEXT,
    image_count INT,
    images TEXT[], -- all_images
    itinerary_details JSONB, -- Nguyên khối `itinerary` gốc (stops/days lồng nhau) — không chuẩn hóa cứng
    scraped_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_platform, source_id) -- Khóa UPSERT, giống tinh thần hotels(source_platform, source_hotel_id)
);

-- Booking records are intentionally separate from the crawler's room-price
-- snapshots. Inventory stays as the latest count on rooms for now.
CREATE TABLE bookings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    temporary_user_ref TEXT,
    session_id VARCHAR(255) REFERENCES sessions(session_id) ON DELETE SET NULL, -- Phiên chat đã tạo hold này, thêm ở migration 20260819 (badge sidebar)
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE RESTRICT,
    check_in_date DATE NOT NULL,
    check_in_time TIME,
    check_out_date DATE NOT NULL,
    check_out_time TIME,
    room_count INTEGER NOT NULL DEFAULT 1 CHECK (room_count > 0),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RESERVED', 'CONFIRMED', 'CANCELLED', 'EXPIRED')),
    expires_at TIMESTAMPTZ,
    total_amount NUMERIC(12, 2),
    currency VARCHAR(10),
    cancelled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (check_out_date > check_in_date),
    CHECK (status <> 'RESERVED' OR expires_at IS NOT NULL)
);

CREATE INDEX bookings_room_dates_idx ON bookings (room_id, check_in_date, check_out_date)
    WHERE status = 'CONFIRMED';

ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE bookings FROM anon, authenticated, PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE bookings TO service_role;

-- create_booking_reservation / confirm_booking_reservation / cancel_booking:
-- see scripts/migrations/20260818_add_booking_reservation_rpcs.sql for the
-- full bodies + design notes (advisory lock, dynamic availability).
-- create_booking_reservation was superseded by
-- scripts/migrations/20260819_add_guest_single_hotel_hold_guard.sql (adds a
-- second guest-scoped advisory lock, a cross-hotel hold conflict guard, and
-- p_session_id/bookings.session_id) — that file is now the canonical copy
-- for THIS function specifically; confirm_booking_reservation/cancel_booking
-- are still exactly as defined in the 20260818 migration, unchanged. Not
-- duplicated here to avoid two sources of truth drifting apart.

-- Payment records for the VNPay integration (plan
-- 260818-vnpay-payment-and-email-confirmation) — see
-- scripts/migrations/20260818_add_payments_table.sql for full comments.
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    temporary_user_ref TEXT NOT NULL,
    booking_ids UUID[] NOT NULL CHECK (array_length(booking_ids, 1) > 0),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    currency VARCHAR(10) NOT NULL DEFAULT 'VND',
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PAID', 'FAILED', 'CANCELLED')),
    guest_name TEXT,
    guest_email TEXT,
    guest_phone TEXT,
    vnp_transaction_no TEXT,
    vnp_response_code TEXT,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX payments_temporary_user_ref_idx ON payments (temporary_user_ref);

ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE payments FROM anon, authenticated, PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE payments TO service_role;

-- The result is the minimum remaining count across every requested night.
CREATE FUNCTION public.get_room_availability(
    p_room_id UUID,
    p_check_in_date DATE,
    p_check_out_date DATE
)
RETURNS INTEGER
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_availability INTEGER;
BEGIN
    IF p_check_out_date <= p_check_in_date THEN
        RAISE EXCEPTION 'check-out date must be after check-in date';
    END IF;

    SELECT min(
        room.available_room_count - coalesce((
            SELECT sum(b.room_count)::integer
            FROM public.bookings AS b
            WHERE b.room_id = room.id
              AND (
                  b.status = 'CONFIRMED'
                  OR (b.status = 'RESERVED' AND b.expires_at > now())
              )
              AND b.check_in_date <= night.stay_date
              AND b.check_out_date > night.stay_date
        ), 0)
    ) INTO v_availability
    FROM public.rooms AS room
    CROSS JOIN LATERAL generate_series(
        p_check_in_date::timestamp,
        (p_check_out_date - 1)::timestamp,
        interval '1 day'
    ) AS night(stay_date)
    WHERE room.id = p_room_id;

    RETURN greatest(coalesce(v_availability, 0), 0);
END;
$$;
REVOKE ALL ON FUNCTION public.get_room_availability(UUID, DATE, DATE) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_room_availability(UUID, DATE, DATE)
    TO service_role;

-- Approved, server-managed amenity definitions. Hotels and rooms store these
-- canonical English IDs in their TEXT[] amenity columns; the backend resolves
-- them to labels for search results and UI display.
CREATE TABLE amenity_catalog (
    id TEXT PRIMARY KEY CHECK (id ~ '^[a-z0-9_]{1,64}$'),
    label_vi TEXT NOT NULL CHECK (char_length(btrim(label_vi)) BETWEEN 1 AND 80),
    label_en TEXT NOT NULL CHECK (char_length(btrim(label_en)) BETWEEN 1 AND 80),
    scope TEXT NOT NULL CHECK (scope IN ('hotel', 'room', 'both')),
    category TEXT NOT NULL CHECK (category IN (
        'accessibility', 'business', 'connectivity', 'facility', 'family', 'food', 'general', 'language',
        'outdoor', 'policies', 'room_comfort', 'safety', 'transport', 'wellness'
    )),
    icon_key TEXT CHECK (icon_key IS NULL OR char_length(btrim(icon_key)) BETWEEN 1 AND 64),
    match_keywords TEXT[] NOT NULL DEFAULT '{}',
    is_approved BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE amenity_catalog ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE amenity_catalog FROM anon, authenticated, PUBLIC;
GRANT SELECT, INSERT, UPDATE ON TABLE amenity_catalog TO service_role;

INSERT INTO amenity_catalog (
    id, label_vi, label_en, scope, category, icon_key, match_keywords, is_approved
) VALUES
    ('wifi', 'Wi-Fi', 'Wi-Fi', 'both', 'connectivity', 'wifi', ARRAY['wifi', 'wi-fi', 'wi fi', 'wireless internet'], TRUE),
    ('swimming_pool', 'Hồ bơi', 'Swimming pool', 'hotel', 'wellness', 'pool', ARRAY['hồ bơi', 'bể bơi', 'swimming pool', 'pool'], TRUE),
    ('tv', 'TV', 'TV', 'room', 'room_comfort', 'tv', ARRAY['tv', 'tivi', 'television'], TRUE),
    ('parking', 'Bãi đỗ xe', 'Parking', 'hotel', 'transport', 'local_parking', ARRAY['bãi đỗ xe', 'chỗ để xe', 'parking', 'car park', 'garage'], TRUE),
    ('family', 'Phù hợp gia đình', 'Family friendly', 'hotel', 'family', 'family_restroom', ARRAY['gia đình', 'trẻ em', 'kids club', 'family room'], TRUE),
    ('non_smoking', 'Không hút thuốc', 'Non-smoking', 'both', 'policies', 'smoke_free', ARRAY['không hút thuốc', 'non smoking', 'non-smoking', 'no smoking'], TRUE),
    ('breakfast', 'Bao gồm bữa sáng', 'Breakfast included', 'hotel', 'food', 'breakfast_dining', ARRAY['bữa sáng', 'bao gồm bữa sáng', 'breakfast', 'breakfast included'], TRUE),
    ('sea_view', 'Hướng biển', 'Sea view', 'room', 'room_comfort', 'water', ARRAY['view biển', 'hướng biển', 'sea view', 'ocean view'], TRUE)
ON CONFLICT (id) DO NOTHING;

-- Semantic hotel and room search. The amenities output is a display-ready
-- catalog join, ordered to match the canonical IDs stored on each hotel.
CREATE FUNCTION public.match_hotels_with_rooms(
    filter_exclude_hotel_ids UUID[],
    query_embedding public.vector,
    match_threshold DOUBLE PRECISION DEFAULT 0.3,
    match_count INTEGER DEFAULT 10,
    filter_destination_id UUID DEFAULT NULL::uuid,
    filter_min_price NUMERIC DEFAULT NULL::numeric,
    filter_max_price NUMERIC DEFAULT NULL::numeric,
    root_latitude DOUBLE PRECISION DEFAULT NULL::double precision,
    root_longitude DOUBLE PRECISION DEFAULT NULL::double precision,
    max_radius_km DOUBLE PRECISION DEFAULT NULL::double precision,
    filter_start_date DATE DEFAULT NULL::date,
    filter_end_date DATE DEFAULT NULL::date
)
RETURNS TABLE(
    id UUID,
    name TEXT,
    description TEXT,
    star_rating DOUBLE PRECISION,
    lowest_price NUMERIC,
    average_nightly_price NUMERIC,
    total_stay_price NUMERIC,
    stay_night_count INTEGER,
    currency TEXT,
    priced_room_name TEXT,
    similarity DOUBLE PRECISION,
    matched_room_names TEXT[],
    "amenities" JSONB
)
LANGUAGE sql
STABLE
AS $$
  WITH hotel_scores AS (
    SELECT
      h.id AS hotel_id,
      1 - (h.embedding <=> query_embedding) AS sim,
      NULL::text AS room_name
    FROM public.hotels AS h
    WHERE h.embedding IS NOT NULL
      AND (filter_destination_id IS NULL OR h.destination_id = filter_destination_id)
      AND (
        filter_start_date IS NULL OR filter_end_date IS NULL
        OR EXISTS (
          SELECT 1
          FROM public.rooms AS r
          WHERE r.hotel_id = h.id
            AND (
              SELECT count(*)
              FROM public.room_prices AS rp
              WHERE rp.room_id = r.id
                AND rp.check_in_date >= filter_start_date
                AND rp.check_out_date <= filter_end_date
                AND rp.sold_out = false
            ) = (filter_end_date - filter_start_date)
            AND public.get_room_availability(
              r.id, filter_start_date, filter_end_date
            ) > 0
        )
      )
  ),
  room_scores AS (
    SELECT
      r.hotel_id,
      1 - (r.embedding <=> query_embedding) AS sim,
      r.name AS room_name
    FROM public.rooms AS r
    JOIN public.hotels AS h ON h.id = r.hotel_id
    WHERE r.embedding IS NOT NULL
      AND (filter_destination_id IS NULL OR h.destination_id = filter_destination_id)
      AND (
        filter_start_date IS NULL OR filter_end_date IS NULL
        OR (
          SELECT count(*)
          FROM public.room_prices AS rp
          WHERE rp.room_id = r.id
            AND rp.check_in_date >= filter_start_date
            AND rp.check_out_date <= filter_end_date
            AND rp.sold_out = false
        ) = (filter_end_date - filter_start_date)
        AND public.get_room_availability(
          r.id, filter_start_date, filter_end_date
        ) > 0
      )
  ),
  combined AS (
    SELECT * FROM hotel_scores WHERE sim > match_threshold
    UNION ALL
    SELECT * FROM room_scores WHERE sim > match_threshold
  ),
  aggregated AS (
    SELECT
      hotel_id,
      max(sim) AS max_sim,
      array_remove(array_agg(DISTINCT room_name), NULL) AS matched_rooms
    FROM combined
    GROUP BY hotel_id
  )
  SELECT
    h.id,
    h.name,
    h.description,
    h.star_rating,
    h.lowest_price,
    h.lowest_price AS average_nightly_price,
    h.lowest_price * coalesce(filter_end_date - filter_start_date, 1) AS total_stay_price,
    coalesce(filter_end_date - filter_start_date, 1) AS stay_night_count,
    h.currency,
    NULL::text AS priced_room_name,
    a.max_sim AS similarity,
    a.matched_rooms AS matched_room_names,
    coalesce(
      (
        SELECT jsonb_agg(
          jsonb_build_object(
            'id', catalog.id,
            'label_vi', catalog.label_vi,
            'label_en', catalog.label_en,
            'category', catalog.category,
            'icon_key', catalog.icon_key
          )
          ORDER BY amenity.ordinality
        )
        FROM unnest(coalesce(h.amenities, ARRAY[]::text[])) WITH ORDINALITY
          AS amenity(amenity_id, ordinality)
        JOIN public.amenity_catalog AS catalog ON catalog.id = amenity.amenity_id
        WHERE catalog.is_approved
      ),
      '[]'::jsonb
    ) AS amenities
  FROM aggregated AS a
  JOIN public.hotels AS h ON h.id = a.hotel_id
  WHERE (filter_min_price IS NULL OR h.lowest_price IS NULL OR h.lowest_price >= filter_min_price)
    AND (filter_max_price IS NULL OR h.lowest_price IS NULL OR h.lowest_price <= filter_max_price)
    AND (
      cardinality(coalesce(filter_exclude_hotel_ids, ARRAY[]::uuid[])) = 0
      OR h.id <> ALL(filter_exclude_hotel_ids)
    )
  ORDER BY a.max_sim DESC
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION public.match_hotels_with_rooms(
    UUID[],
    public.vector,
    DOUBLE PRECISION,
    INTEGER,
    UUID,
    NUMERIC,
    NUMERIC,
    DOUBLE PRECISION,
    DOUBLE PRECISION,
    DOUBLE PRECISION,
    DATE,
    DATE
) TO anon, authenticated, service_role;

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
