# Worklog — Team VSF Trip Planner Agent

> Ghi lại tất cả công việc đã làm theo ngày. Ai làm gì, kết quả gì.

---

## 2026-07-29

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Team Lead | Phân tích luồng Agent & Lập kế hoạch 3 ngày cho 3 người | ✅ Done | Sơ đồ luồng & Phân chia công việc 3-Day Sprint | 2h |
| Eng 1 | Xây dựng & Lưu trữ Golden Trip 3 ngày TP HCM (Solo) | ✅ Done | [golden_trip_plan_hcm_3d.json](file:///d:/Git%20repo/vsf-project/golden_trip_plan_hcm_3d.json) & Persistence trong Supabase | 3h |
| Eng 2 | Kiểm thử luồng tạo mới 5 ngày TP HCM chủ đề Lịch Sử (Solo) | ✅ Done | [test_trip_plan_hcm_5d_historical.json](file:///d:/Git%20repo/vsf-project/test_trip_plan_hcm_5d_historical.json) (37 hoạt động) | 2.5h |
| Eng 3 | Bổ sung Fallback Resilience cho `ItineraryStore` | ✅ Done | Auto direct table upsert khi RPC trên DB gặp sự cố | 1.5h |
| Team | Chuẩn hóa toàn bộ tài liệu dự án (`ARCHITECTURE.md`, `README.md`) | ✅ Done | [ARCHITECTURE.md](file:///d:/Git%20repo/vsf-project/ARCHITECTURE.md) chuẩn hóa Mermaid & 3-Tier details | 2h |

**Tổng kết ngày:** Đã hoàn thành 100% mục tiêu tạo & lưu Golden Trip 3 ngày TP.HCM, thử nghiệm thành công luồng 5 ngày lịch sử cho TP.HCM, đồng thời nâng cấp độ ổn định cho `ItineraryStore` và chuẩn hóa tài liệu kiến trúc.

---

## 2026-07-28

| Member | Task | Status | Output | Time |
|--------|------|--------|--------|------|
| Eng 1 | Cấu hình Supabase & Qdrant Schema | ✅ Done | `qdrant_schema.py` & `supabase_search.py` | 4h |
| Eng 2 | Phát triển thuật toán Lập lịch Deterministic | ✅ Done | `trip_scheduler.py` | 5h |
| Eng 3 | Xây dựng module Thu thập thông tin Intake & Reuse Cache | ✅ Done | `trip_intake.py` & `itinerary_reuse.py` | 4h |

**Tổng kết ngày:** Đã xây dựng nền tảng các dịch vụ xử lý dữ liệu du lịch cốt lõi (Intake, Retrieval, Scheduler, Reuse).
