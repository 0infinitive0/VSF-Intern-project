# Sơ đồ tổng thể kiến trúc — V-OTA AI Chat (M1 → M3)

Nguồn: `plans/260723-1015-v-ota-poc-master-roadmap/plan.md` (BRD §13.2 L2), đối chiếu với trạng thái repo thực tế ngày 2026-07-24.

Màu sắc thể hiện **trạng thái đã xác minh**, không phải kỳ vọng: xanh lá = đã xong, cam = stub/khung rỗng, xám nét đứt = chưa có, tím chấm = kế hoạch M3.

## Ảnh xuất bản (publish-grade, qua `/ak:tech-graph`)

![Sơ đồ kiến trúc tổng thể V-OTA AI Chat](./architecture-overview.png)

- SVG: [`architecture-overview.svg`](./architecture-overview.svg)
- PNG (2x, 2000px): [`architecture-overview.png`](./architecture-overview.png)

## Phiên bản Mermaid (chỉnh sửa nhanh / nhúng vào tài liệu khác)

```mermaid
flowchart TD
  subgraph L1["Người dùng"]
    user(["Người dùng · VI/EN"])
  end

  subgraph L2["Giao diện"]
    ui["Web Chat UI<br/><small>Giai đoạn 5 · chưa có</small>"]
  end

  subgraph L3["Lõi hội thoại"]
    orch["Điều phối hội thoại<br/><small>stub, 29 dòng · Giai đoạn 3</small>"]
    nlu["NLU song ngữ VI/EN<br/><small>chưa có · Giai đoạn 3</small>"]
    search["Tìm kiếm &amp; bộ lọc<br/><small>chưa có · Giai đoạn 4</small>"]
    gen["Sinh trả lời + Grounding<br/><small>stub, 12 dòng · Giai đoạn 3</small>"]
    handoff["Handoff đặt phòng<br/><small>chưa có · Giai đoạn 4</small>"]
    itin["Lập lịch trình &amp; tối ưu<br/><small>kế hoạch M3 · Giai đoạn 7</small>"]
  end

  subgraph L4["Kho dữ liệu"]
    pg[("Postgres CSDL<br/><small>đã xong, 10 bảng</small>")]
    qd[("Qdrant chỉ mục vector<br/><small>chưa có · Giai đoạn 2</small>")]
  end

  subgraph L5["Thu thập &amp; chuẩn hóa"]
    norm["Chuẩn hóa dữ liệu<br/><small>đã xong, 7 bước qua XCom</small>"]
    conn["Connector OTA<br/><small>đã xong, Airflow DAGs</small>"]
  end

  subgraph L6["Nguồn dữ liệu"]
    src["Agoda · Booking.com · OSM/Wikidata"]
  end

  user --> ui --> orch
  orch --> nlu --> search
  orch --> gen
  orch --> handoff
  orch -.-> itin
  search --> pg
  search --> qd
  gen --> pg
  gen -.-> qd
  itin -.-> pg
  norm --> pg
  norm -.-> qd
  conn --> norm
  src --> conn

  classDef shipped fill:#4d7c0f22,stroke:#4d7c0f,stroke-width:2px;
  classDef stub fill:#b4530922,stroke:#b45309,stroke-width:2px;
  classDef absent fill:#88888822,stroke:#888888,stroke-width:1.5px,stroke-dasharray:5 4;
  classDef planned fill:#9f123922,stroke:#9f1239,stroke-width:1.5px,stroke-dasharray:3 3;

  class pg,norm,conn shipped;
  class orch,gen stub;
  class ui,nlu,search,handoff,qd absent;
  class itin planned;
```

## Ghi chú xác minh

| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Connector OTA | Đã xong | `src/airflow/dags/data_pipeline/` — DAG hotel/hotel_nearby/osm/ota/google_maps |
| Chuẩn hóa dữ liệu | Đã xong | Pipeline 7 bước qua XCom, khử trùng lặp |
| Postgres CSDL | Đã xong | `scripts/database_schema.sql` — 10 bảng, 1.103 khách sạn đã nạp |
| Qdrant chỉ mục vector | Chưa có | `grep -ri qdrant` trên toàn repo → không kết quả |
| Điều phối hội thoại | Stub | `src/agents/graph.py` — 29 dòng |
| Sinh trả lời + Grounding | Stub | `src/services/llm.py` — 12 dòng |
| NLU song ngữ, Tìm kiếm & bộ lọc, Handoff đặt phòng, Web Chat UI | Chưa có | Không tìm thấy module tương ứng dưới `src/` |
| Lập lịch trình & tối ưu | Kế hoạch M3 | Giai đoạn 7, sau cổng M2 (Giai đoạn 6) |

Chi tiết đối chiếu đầy đủ (bao phủ yêu cầu BR, sổ rủi ro, kế hoạch liên quan): xem [`../visuals/plan-review.html`](../visuals/plan-review.html).
