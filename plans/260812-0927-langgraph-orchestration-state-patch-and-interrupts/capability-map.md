# LangGraph capability map — hiện trạng

Sơ đồ luồng thật của một chat turn, kèm đánh dấu khả năng.
Nguồn: `session.py`, `routing_decision.py`, `supervisor.py`, `graph.py`, `trip_edit_planner.py`.

Legend: 🟩 chạy đúng · 🟨 chạy nhưng sai/không đầy đủ · 🟥 không tồn tại

## Luồng turn

```mermaid
flowchart TD
    IN["POST /planner_chat"] --> JB{"detect_jailbreak<br/>guardrails/jailbreak.py"}
    JB -->|blocked| REF["Từ chối prompt-injection"]
    JB -->|pass| SCOPE{"Từ chối ngoài phạm vi<br/>toán / code / vé máy bay"}
    SCOPE --> PRE["_process_chat_turn"]

    PRE --> SD{"stay_dates từ UI?"}
    SD -->|có| WSD["with_stay_dates"]
    SD -->|không| DPU{"direct_preference_update?<br/>cần pending_hotel_selection<br/>HOẶC budget đã xong"}

    DPU -->|có| TPU["TripPreferenceUpdate<br/>5 field"]
    DPU -->|không| ROUTE

    subgraph ROUTING["Định tuyến"]
        ROUTE["_decide_route"] --> LLMR["decide_route_by_llm<br/>supervisor.py"]
        LLMR --> VAL{"validate_route<br/>chỉ chặn finalize + edit_draft"}
        VAL -->|hợp lệ| R
        VAL -->|không| RULES["decide_route_by_rules<br/>regex tiếng Việt"]
        RULES --> R{"route"}
    end

    R -->|finalize| FIN["finalize_trip_plan"]
    R -->|edit_draft| ED["_run_edit_draft"]
    R -->|intake| INT["_run_intake<br/>thang if 5 bước"]
    R -->|chat / new_trip| AG["_run_chat_agent"]

    subgraph INTAKE["_run_intake — thang cứng"]
        I1["1 điểm đến + số người"] --> I2["2 NGÂN SÁCH<br/>cổng chặn cứng"]
        I2 --> I3["3 ngày<br/>date picker khoá sau budget"]
        I3 --> I4["4 recommend_hotels"]
        I4 --> I5["5 giao cho chat agent"]
    end
    INT --> I1

    subgraph EDIT["_run_edit_draft"]
        E1["plan_trip_edit — LLM"] --> E2{"decision"}
        E2 -->|apply| E3["apply_trip_edit_plan<br/>9 operation"]
        E2 -->|clarify| E4["hỏi lại"]
        E2 -->|not_edit| AG
    end
    ED --> E1

    subgraph TOOLS["ReAct agent — 6 tool"]
        T1["recommend_hotels"]
        T2["select_hotel"]
        T3["query_hotel"]
        T4["query_hotel_rooms"]
        T5["modify_trip_plan"]
        T6["finalize_trip_plan"]
    end
    AG --> TOOLS

    MISSING["🟥 KHÔNG TỒN TẠI<br/>interrupt · search_places · select_place<br/>booking · auth / ownership"]

    class SCOPE,MISSING gap
    class I2,I3,VAL,RULES,E1,DPU broken
    class JB,FIN,T2,T3,T4,T6,E3 ok
    class T1,T5 partial

    classDef gap fill:#4a1418,stroke:#b8232c,stroke-width:2px,color:#fff
    classDef broken fill:#5c3a10,stroke:#d08b2a,stroke-width:2px,color:#fff
    classDef ok fill:#123d1f,stroke:#2e8b57,stroke-width:1px,color:#fff
    classDef partial fill:#4a3d10,stroke:#b8860b,stroke-width:1px,color:#fff
```

## Bảng khả năng

### 🟩 Làm được

| Khả năng | Đường đi |
|---|---|
| Chọn khách sạn "cái thứ 2" | `resolve_hotel_selection` — rank/id/tên, xác định, không bịa ID |
| Hỏi thông tin khách sạn / phòng | `query_hotel`, `query_hotel_rooms` |
| Chốt lịch trình | `finalize_trip_plan` |
| Đổi 1 hoặc nhiều địa điểm | `replace_item` × N — multi-op hợp lệ |
| Đi cùng người yêu / gia đình | `_COMPANION_LABELS` |
| Khách sạn sang trọng / bình dân | `_QUALITATIVE_BUDGET_PHRASES` |
| Chặn prompt-injection | `detect_jailbreak` — 4 họ pattern |
| Giá phòng/đêm, khoảng giá | tier + `_parse_free_text_price` |

### 🟨 Làm được nhưng sai

| Khả năng | Sai ở đâu |
|---|---|
| Đổi theme ngày N | `normalize_day_themes:534` ghi đè bằng preference cũ; title đúng, nội dung sai |
| Search theo tiện ích | Chỉ là bonus xếp hạng `+0.03`, không phải filter |
| Đánh giá trên 4 sao | `supabase_search.py:281` âm thầm bỏ filter khi 0 kết quả |
| Nhập ngày | Không check năm thiếu, quá khứ, thứ tự ngày/tháng; `:296` khoá cứng không sửa được |
| Sửa khi budget đang chờ | `_run_intake` bước 2 chặn cứng; `direct_preference_update` không với tới được |
| Định tuyến | `validate_route` chỉ chặn 2/5 route; `intake`/`chat` sai vẫn lọt |
| Phân loại edit | Prompt `:442` vs `:445` xung đột cho "ngày 1 thiên nhiên" |

### 🟥 Không tồn tại

| Khả năng | Bằng chứng |
|---|---|
| Bán kính 3km | Có ở tầng dưới, `recommend_hotels` không truyền xuống |
| Tổng ngân sách chuyến | `_calculate_trip_budget` chỉ tính để hiển thị |
| Giới hạn địa điểm/ngày | `planning_constraints` chỉ có `latest_outing_*` + `meal_preferences` |
| Khoảng cách giữa địa điểm | Không có ràng buộc nào |
| Tìm nhà hàng xung quanh | Nhà hàng chỉ là query cố định trong slot bữa ăn |
| Gợi ý địa điểm rồi mới chọn | Chỉ khách sạn có luồng chọn |
| Hỏi lại khi mơ hồ | `interrupt` = 0 lần dùng; `MemorySaver` không resume được |
| Từ chối ngoài phạm vi | `guardrails/` chỉ có jailbreak |
| Booking / giữ chỗ / sold out | 0 hit chức năng trên toàn `src/` |
| Auth / quyền sở hữu | Session ẩn danh; `itineraries` không có `user_id` |

## Ánh xạ sang phase

```mermaid
flowchart LR
    P1["P1 · theme + pill"] --> OK1["🟨→🟩 theme ngày N"]
    P9["P9 · scope guard"] --> OK2["🟥→🟩 từ chối toán/code/vé"]
    P2["P2 · TravelState"] --> P3["P3 · extract_patch"] --> P4["P4 · slot registry"] --> P5["P5 · interrupt"]
    P4 --> OK3["🟨→🟩 hết deadlock"]
    P5 --> OK4["🟥→🟩 hỏi khi mơ hồ"]
    P2 --> P6["P6 · impact map"]
    P5 --> P7["P7 · hard filter"] --> OK5["🟨→🟩 tiện ích + sao + bán kính"]
    P6 --> P10["P10 · ràng buộc/ngày"] --> OK6["🟥→🟩 số điểm + khoảng cách"]
    P7 --> P11["P11 · place search"] --> OK7["🟥→🟩 nhà hàng + gợi ý"]
    P6 --> P12["P12 · tổng ngân sách"] --> OK8["🟥→🟩 dưới 3tr"]
    P2 --> P8["P8 · audit + eval"]

    BLOCK["🟥 CHẶN — plan riêng<br/>auth/ownership → booking"]

    class BLOCK gap
    classDef gap fill:#4a1418,stroke:#b8232c,stroke-width:2px,color:#fff
```
