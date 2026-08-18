-- Add the `tours` table: Booking.com tour/activity OTA listing data, fetched
-- via an Apify actor (see backend/src/airflow/dags/data_pipeline/tour_pipeline.py).
-- Same UPSERT spirit as hotels(source_platform, source_hotel_id): one row per
-- (source_platform, source_id), no cross-OTA merging at this table.
-- Safe to apply to an existing Supabase project more than once.
CREATE TABLE IF NOT EXISTS tours (
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
