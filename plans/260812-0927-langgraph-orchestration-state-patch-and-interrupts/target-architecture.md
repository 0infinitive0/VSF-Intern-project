# Kiến trúc đích — LangGraph một control plane, sau 14 phase

Trạng thái **sau khi plan hoàn tất**. Hiện trạng xem `capability-map.md`.
Mỗi node gắn nhãn phase xây nó.

## 1. Graph chính

```mermaid
flowchart TD
    START(["Tin nhắn người dùng"]) --> LC["load_context<br/><i>TravelState từ Postgres checkpointer</i><br/>P4"]

    LC --> SG{"scope_guard<br/><i>toán / code / vé máy bay</i><br/>P2"}
    SG -->|ngoài phạm vi| REFUSE["Từ chối 1 câu<br/>+ đề nghị việc làm được"]
    REFUSE --> END1(["END"])

    SG -->|hợp lệ| EX["extract_patch<br/><i>1 LLM call → intent + changes[]</i><br/>P6"]

    EX --> VP{"validate_patch<br/><i>ALLOWED_PATHS + validator/path</i><br/>P3"}

    VP -->|mơ hồ| INT["interrupt<br/><i>thiếu năm · thứ tự ngày/tháng<br/>tâm bán kính · sao hay điểm</i><br/>P7"]
    INT -.->|"Command resume"| VP

    VP -->|từ chối 1 phần| AP
    VP -->|hợp lệ| AP["apply_patch<br/>+ audit trail<br/>P3 · P10"]

    AP --> NQ{"next_question<br/><i>slot UNKNOWN ưu tiên cao nhất</i><br/>P7"}
    NQ -->|còn slot bắt buộc| ASK["Hỏi + xác nhận điều vừa hiểu"]
    ASK --> END2(["END"])

    NQ -->|đủ| DI{"detect_impact<br/><i>IMPACT_MAP</i><br/>P3"}

    DI -->|hotel| HF["hotel_flow<br/><b>node</b>"]
    DI -->|itinerary| IF["itinerary_flow<br/><b>node</b>"]
    DI -->|itinerary_day| IF
    DI -->|general_question| QA["general_qa<br/><b>subgraph</b>"]
    DI -->|none| RESP

    HF --> BC
    IF --> BC{"budget_check<br/><i>tổng chuyến ≤ giới hạn?</i><br/>P14"}

    BC -->|vượt, chưa replan| REPLAN["1 lượt replan<br/><i>tôn trọng locked_days</i><br/>P14"]
    REPLAN --> IF
    BC -->|vượt, đã replan| OVER["Báo chi phí nào chiếm chủ đạo<br/><i>không âm thầm hạ chuẩn</i>"]
    BC -->|đạt| VR["validate_result<br/><i>thời gian · tuyến · thực thể có thật</i>"]

    QA --> RESP
    OVER --> RESP
    VR --> RESP["generate_response<br/><i>reply + state_changes + affected_domains</i>"]
    RESP --> END3(["END"])

    class SG,INT,REFUSE guard
    class EX,VP,AP,NQ state
    class HF,IF,BC,REPLAN,VR flow
    class OVER report

    classDef guard fill:#4a1418,stroke:#b8232c,stroke-width:2px,color:#fff
    classDef state fill:#1a3a52,stroke:#4a90c2,stroke-width:2px,color:#fff
    classDef flow fill:#123d1f,stroke:#2e8b57,stroke-width:2px,color:#fff
    classDef report fill:#4a3d10,stroke:#b8860b,stroke-width:2px,color:#fff
```

**Đảo ngược cốt lõi so với hiện tại:** `extract_patch` chạy **trước** `next_question`.
Hôm nay câu hỏi đang chờ quyết định xem tin nhắn có được phép mang ý nghĩa khác không —
đó chính là nguồn của mọi deadlock. Ở đây patch luôn được thử trước, câu hỏi chỉ hỏi lại sau.

## 2. hotel_flow — P8

```mermaid
flowchart TD
    IN(["hotel_flow"]) --> CTR{"resolve_center<br/>P8"}
    CTR -->|có khách sạn đã chọn| C1["tâm = khách sạn đó"]
    CTR -->|user nêu địa danh| C2["geocode từ bảng attractions<br/><i>không nhận toạ độ do LLM cấp</i>"]
    CTR -->|không xác định| C3["interrupt: bán kính tính từ đâu?"]

    C1 --> RPC
    C2 --> RPC
    C3 -.-> CTR

    RPC["search RPC<br/><i>destination · dates · min/max price<br/>root_lat/lng + max_radius_km</i>"] --> OVERFETCH["over-fetch match_count × k"]

    OVERFETCH --> HARD["hard filter<br/><i>amenities AND · min_star_rating<br/>min_review_score</i><br/>P8"]

    HARD --> ZERO{"còn kết quả?"}
    ZERO -->|không| BIND["Báo ràng buộc nào chặn<br/><i>'không có KS vừa có gym vừa có hồ bơi;<br/>bỏ gym thì còn 6'</i>"]
    ZERO -->|có| RANK["rank_hotel_candidates"]

    RANK --> SAVE["pending_hotel_selection"]
    SAVE --> OUT(["→ budget_check"])
    BIND --> OUT

    class C3,BIND ask
    class HARD,RPC hard
    classDef ask fill:#4a3d10,stroke:#b8860b,stroke-width:2px,color:#fff
    classDef hard fill:#123d1f,stroke:#2e8b57,stroke-width:2px,color:#fff
```

Điểm chết người đã gỡ: **không còn nhánh nào âm thầm bỏ filter.** Hôm nay
`supabase_search.py:281` tự bỏ `min_star_rating` khi 0 kết quả và trả về semantic matches —
user xin 4 sao, nhận 3 sao, không có dấu hiệu gì.

## 3. itinerary_flow (node) + rebuild_day (SUBGRAPH) — P9 · P12 · P13

```mermaid
flowchart TD
    IN(["itinerary_flow · <b>node</b>"]) --> DAYS["Ngày bị ảnh hưởng trừ locked_days<br/><i>+ plan_trip_edit cho sửa cấp item</i><br/>P9"]

    DAYS --> LOOP{"còn ngày<br/>chưa dựng?"}

    LOOP -->|có| THEME["theme của ngày<br/><i>user_specified thì KHÔNG ghi đè<br/>bằng preference cả chuyến</i><br/>P1"]

    THEME --> SEARCH["search_places<br/><i>loại trừ chỉ các điểm CỦA NGÀY ĐÓ</i><br/>P13"]

    SEARCH --> CONS["ràng buộc theo ngày<br/><i>max_items_per_day<br/>max_item_distance_km</i><br/>P12"]

    CONS --> FEW{"đủ điểm?"}
    FEW -->|không| SAY["Báo lý do chặn<br/><i>'chỉ có 4 điểm trong bán kính 1km'</i>"]
    FEW -->|có| RANKP["rank"]

    RANKP --> SUGGEST{"user xin gợi ý?"}
    SUGGEST -->|có| SHORT["shortlist → select_place<br/><i>dùng chung resolver với hotel</i><br/>P13"]
    SUGGEST -->|không| ROUTE["calculate_route · OSRM"]

    SHORT --> ROUTE
    ROUTE --> SCHED["schedule + repair<br/><i>latest_outing · meal_preferences</i>"]
    SCHED --> SAVEDAY["Lưu RIÊNG ngày đó<br/><i>ngày khác không đụng tới</i><br/>P9"]

    SAVEDAY --> LOOP
    SAY --> OUT
    LOOP -->|hết| OUT(["→ budget_check"])

    class SAY,SHORT ask
    class SAVEDAY,CONS,THEME key
    classDef ask fill:#4a3d10,stroke:#b8860b,stroke-width:2px,color:#fff
    classDef key fill:#123d1f,stroke:#2e8b57,stroke-width:2px,color:#fff
```

Khối `THEME → SAVEDAY` là **subgraph `rebuild_day`**, gọi một lần cho mỗi ngày qua cạnh
lặp của graph cha — không phải `for` trong Python. Nhờ vậy interrupt ở ngày 2 khi chọn địa
điểm chỉ chạy lại ngày 2; ngày 1 đã checkpoint xong.

Hai thứ hôm nay chưa có: vòng lặp **chỉ chạy trên ngày bị ảnh hưởng** — hiện
`_apply_day_replan:1378` dựng lại cả chuyến rồi vứt hết trừ 1 ngày; và loại trừ điểm
tham quan **chỉ trong phạm vi ngày đó** — hiện loại trừ toàn bộ mọi ngày, làm ngày mới
có thể rỗng ở điểm đến ít dữ liệu.

## 4. Tầng state — P3

```mermaid
flowchart LR
    subgraph SRC["Nguồn ghi"]
        M["extract_patch<br/>P6"]
        U["Thao tác UI<br/>date picker · chọn KS"]
    end

    SRC --> PATCH["changes[]<br/><i>path · operation · value</i>"]

    PATCH --> GATE{"ALLOWED_PATHS<br/>+ validator theo path"}
    GATE -->|ngoài allow-list| REJ["từ chối RIÊNG change đó<br/><i>change hợp lệ cùng patch vẫn áp dụng</i>"]
    GATE -->|hợp lệ| SLOT

    subgraph SLOT["TravelState — tri-state"]
        S1["UNKNOWN<br/><i>chưa hỏi</i>"]
        S2["SET<br/><i>có giá trị · sửa được</i>"]
        S3["NOT_APPLICABLE<br/><i>user nói không quan tâm</i>"]
    end

    SLOT --> IM["IMPACT_MAP<br/>P3"]
    IM --> W1["hotel"]
    IM --> W2["itinerary"]
    IM --> W3["itinerary_day"]

    SLOT --> AUD["audit trail<br/><i>áp dụng VÀ bị từ chối</i><br/>P10"]
    REJ --> AUD

    class GATE,REJ gate
    class S1,S2,S3 tri
    classDef gate fill:#4a1418,stroke:#b8232c,stroke-width:2px,color:#fff
    classDef tri fill:#1a3a52,stroke:#4a90c2,stroke-width:2px,color:#fff
```

`UNKNOWN` ≠ `NOT_APPLICABLE` là thứ gỡ deadlock ngân sách: hôm nay `None` mang cả hai
nghĩa nên không phân biệt được "chưa trả lời" với "trả lời là không quan tâm".

## 5. Thứ tự thi công

```mermaid
flowchart LR
    subgraph W1["Đợt 1 — độc lập, ~1 ngày"]
        A1["P1 · theme + pill"]
        A2["P2 · scope guard"]
    end

    subgraph W2["Đợt 2 — nền"]
        B3["P3 · TravelState + IMPACT_MAP"]
        B4["P4 · Postgres checkpointer"]
        B5["P5 · graph skeleton<br/><i>sau đây 2 plane cùng tồn tại</i>"]
    end

    subgraph W3["Đợt 3 — điền node"]
        C6["P6 · extract_patch"]
        C7["P7 · slot + interrupt"]
        C8["P8 · hotel_flow"]
        C9["P9 · itinerary_flow"]
        C10["P10 · audit + eval"]
    end

    CUT["P11 · CUTOVER<br/><i>bật mặc định, XOÁ plane cũ</i><br/>~1.400 LOC"]

    subgraph W4["Đợt 4 — năng lực mới"]
        D12["P12 · ràng buộc/ngày"]
        D13["P13 · place search"]
        D14["P14 · tổng ngân sách"]
    end

    B3 --> B5
    B4 --> B5
    B5 --> C6 --> C7
    C7 --> C8
    C7 --> C9
    B3 --> C10

    C8 --> CUT
    C9 --> CUT
    C10 --> CUT

    CUT --> D12
    CUT --> D13
    CUT --> D14

    BLOCKED["🚫 CHẶN — plan riêng<br/>auth + ownership → booking"]

    class W1 first
    class CUT cutover
    class BLOCKED blocked
    classDef first fill:#123d1f,stroke:#2e8b57,stroke-width:2px
    classDef cutover fill:#4a1418,stroke:#b8232c,stroke-width:3px,color:#fff
    classDef blocked fill:#4a1418,stroke:#b8232c,stroke-width:2px,color:#fff
```

**P5 → P11 là cửa sổ duy nhất hai plane cùng tồn tại**, sau cờ `orchestrator=graph|legacy`.
Plane cũ bị đóng băng từ P5 (chỉ được revert, không được sửa). P11 đóng cửa sổ bằng cách
xoá hẳn — nếu không xoá thì plan chưa đạt mục tiêu đã tuyên bố.

Điểm dừng hợp lý: sau **Đợt 1** hết 2 bug + có từ chối · sau **P7** hết deadlock ·
sau **P11** còn đúng một control plane · sau **Đợt 4** mọi khả năng đã nêu đều chạy.
