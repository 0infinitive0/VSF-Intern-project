# AI Travel Chatbot - Entity Relationship Diagram (ERD)

Bản đồ thực thể liên kết (ERD) chi tiết dưới đây thể hiện kiến trúc dữ liệu **ĐẦY ĐỦ 100% CÁC CỘT (FIELDS)** của toàn bộ 10 bảng trong PostgreSQL, bao gồm cả mảng, thời gian, và tracking.

```mermaid
erDiagram
    destinations {
        UUID id PK
        VARCHAR name
        VARCHAR region
        VARCHAR coordinates
        TEXT description
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
    
    hotels {
        UUID id PK
        UUID destination_id FK
        VARCHAR source_platform
        BIGINT source_hotel_id
        TEXT source_url
        VARCHAR name
        VARCHAR accommodation_type
        TEXT description
        DECIMAL star_rating
        VARCHAR address
        VARCHAR city
        VARCHAR area_name
        VARCHAR country
        VARCHAR location_highlight
        VARCHAR coordinates
        TEXT_ARRAY amenities
        JSONB amenity_groups
        TEXT_ARRAY highlights
        TEXT_ARRAY awards
        TEXT_ARRAY warnings
        DECIMAL review_score
        INT review_count
        VARCHAR review_text
        JSONB category_scores
        JSONB score_distribution
        VARCHAR check_in_time
        VARCHAR check_in_until
        VARCHAR check_out_time
        VARCHAR reception_open_until
        TEXT image_url
        TEXT_ARRAY images
        INT image_count
        JSONB nearby_attractions
        JSONB nearby_essentials
        DECIMAL lowest_price
        VARCHAR currency
        DATE price_check_in_date
        DATE price_check_out_date
        BOOLEAN rooms_available
        SMALLINT offer_count
        TIMESTAMP scraped_at
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
    
    rooms {
        UUID id PK
        UUID hotel_id FK
        BIGINT source_room_id
        VARCHAR name
        TEXT bed_description
        DECIMAL room_size_sqm
        VARCHAR max_occupancy_raw
        SMALLINT max_guests
        VARCHAR view
        TEXT_ARRAY room_facilities
        JSONB amenity_groups
        TEXT_ARRAY images
        INT image_count
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
    
    room_prices {
        UUID id PK
        UUID room_id FK
        DECIMAL price
        VARCHAR currency
        DATE check_in_date
        DATE check_out_date
        BOOLEAN sold_out
        BOOLEAN crossed_out
        DECIMAL review_score
        VARCHAR review_text
        TEXT source_url
        TIMESTAMP crawled_at
    }
    
    attractions {
        UUID id PK
        UUID destination_id FK
        VARCHAR name
        VARCHAR category
        BOOLEAN is_tour
        SMALLINT estimated_duration_minutes
        TIME opening_time
        TIME closing_time
        TEXT departure_schedule
        DECIMAL ticket_price_adult
        DECIMAL ticket_price_child
        DECIMAL rating
        INT review_count
        VARCHAR coordinates
        TEXT_ARRAY images
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
    
    events {
        UUID id PK
        UUID destination_id FK
        UUID attraction_id FK "nullable"
        VARCHAR name
        TEXT description
        TIMESTAMP start_date
        TIMESTAMP end_date
        TEXT_ARRAY images
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
    
    sessions {
        VARCHAR session_id PK
        JSONB context_data
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
    
    chat_messages {
        UUID id PK
        VARCHAR session_id FK
        VARCHAR sender_type
        TEXT message_content
        TIMESTAMP created_at
    }
    
    itineraries {
        UUID id PK
        VARCHAR session_id FK
        SMALLINT duration_days
        SMALLINT number_of_adults
        SMALLINT number_of_children
        DECIMAL budget
        TEXT_ARRAY preferences
        VARCHAR status
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }
    
    itinerary_items {
        UUID id PK
        UUID itinerary_id FK
        SMALLINT day_number
        SMALLINT order_index
        TIME start_time
        TIME end_time
        VARCHAR reference_type "Hotel/Attraction/Event"
        UUID reference_id "Polymorphic"
        DECIMAL estimated_cost
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    %% Quan hệ Địa lý & Điểm đến
    destinations ||--o{ hotels : "có các Khách sạn"
    destinations ||--o{ attractions : "có Điểm tham quan/Nhà hàng"
    destinations ||--o{ events : "tổ chức Sự kiện"
    
    %% Quan hệ Khách sạn
    hotels ||--o{ rooms : "có các Hạng phòng"
    rooms ||--o{ room_prices : "có các Gói giá theo ngày"
    
    %% Quan hệ Điểm tham quan - Sự kiện
    attractions |o--o{ events : "là địa điểm tổ chức (Tùy chọn)"
    
    %% Quan hệ AI Chat & Lịch trình
    sessions ||--o{ chat_messages : "lưu Lịch sử Chat"
    sessions ||--o{ itineraries : "sinh ra Lịch trình"
    
    %% Quan hệ Chi tiết Lịch trình
    itineraries ||--o{ itinerary_items : "chứa các Hoạt động"
    
    %% Mối quan hệ Đa hình (Polymorphic) - Nét đứt (---) thể hiện Logical Link
    itinerary_items }o..o| hotels : "Có thể trỏ tới"
    itinerary_items }o..o| attractions : "Có thể trỏ tới"
    itinerary_items }o..o| events : "Có thể trỏ tới"
```
