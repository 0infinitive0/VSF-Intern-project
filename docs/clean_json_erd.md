# ERD — `data/interim/manual__2026-07-22T08-08-01.190130-00-00/clean.json`

File là mảng JSON gồm 10 bản ghi khách sạn (nested). Sơ đồ dưới chuẩn hoá cấu trúc nested đó thành các thực thể quan hệ.

```mermaid
erDiagram
    HOTEL ||--o{ HOTEL_AMENITY : "amenities[]"
    HOTEL ||--o{ HOTEL_IMAGE : "images[]"
    HOTEL ||--o{ ROOM : "rooms[]"
    ROOM  ||--o{ ROOM_FACILITY : "facilities[]"
    ROOM  ||--o{ ROOM_IMAGE : "images[]"
    ROOM  ||--o{ ROOM_PRICE : "prices[]"

    HOTEL {
        string source PK "agoda"
        string source_id PK
        string source_url
        string canonical_url
        string name
        string description
        string accommodation_type
        int    star_rating "nullable"
        string city_raw
        string destination_key
        string address
        float  latitude
        float  longitude
        string coordinates "lat,lon"
        float  rating
        int    review_count
        string check_in_time
        string check_out_time
        string area_name "nullable"
        string crawl_profile
        string scraped_at
        string source_file
    }

    HOTEL_AMENITY {
        string source FK
        string source_id FK
        string amenity
    }

    HOTEL_IMAGE {
        string source FK
        string source_id FK
        string image_url
    }

    ROOM {
        string source_room_id PK
        string source FK
        string source_id FK
        bool   synthetic_room_id
        string name
        int    max_adults "nullable"
        int    max_children "nullable"
        string bed_type "nullable"
        int    number_of_beds "nullable"
    }

    ROOM_FACILITY {
        string source_room_id FK
        string facility
    }

    ROOM_IMAGE {
        string source_room_id FK
        string image_url
    }

    ROOM_PRICE {
        string source_room_id FK
        int    price
        string currency "VND"
        date   check_in_date
        date   check_out_date
        string source_url
        string package_details "standard"
        int    available_rooms "nullable"
        string crawled_at
    }
```

## Ghi chú

- Khoá tự nhiên của HOTEL là cặp `(source, source_id)`; `canonical_url` dùng để dedupe cross-source.
- `synthetic_room_id = true` nghĩa là `source_room_id` do pipeline sinh ra, không phải ID gốc từ nguồn.
- `amenities`, `images`, `facilities` là mảng string thuần → tách thành bảng con (hoặc giữ dạng `text[]`/JSONB nếu dùng Postgres).
- `ROOM_PRICE` là bảng fact theo thời gian: 1 dòng / (phòng, khoảng ngày, lần crawl). Trong dữ liệu hiện tại có 48 bản ghi giá.
- `rating` thang 10 (Agoda), khác `star_rating` (1–5, có thể null).
