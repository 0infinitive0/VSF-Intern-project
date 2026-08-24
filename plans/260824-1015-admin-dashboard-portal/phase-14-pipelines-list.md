---
phase: 14
title: "Danh sách pipeline (C1)"
status: pending
priority: P1
effort: "1.5d"
dependencies: [13]
---

# Phase 14: Danh sách pipeline — C1

## Overview

Màn thay thế hoàn toàn Airflow UI cho nhóm vận hành (quyết định #4). Người dùng
**không biết khái niệm DAG** — mọi chữ trên màn phải là tiếng Việt thường.

**Thiết kế bám theo:** artboard `C1 · DANH SÁCH PIPELINE`.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb `Quản trị · Dữ liệu bot` · tiêu đề `Pipeline` ·
nút phụ `Lịch sử lần chạy` · nút chính `Chạy embedding`.

**Banner lỗi trên cùng** (khi có pipeline lỗi gần đây, biểu tượng `!`,
nền `--err-soft`):
`Pipeline OTA lỗi lúc 06:12 hôm nay. Giá phòng của 2 khách sạn có thể đã cũ.` ·
nút `Xem log`

**Thẻ pipeline** — mỗi thẻ:
- Tên + mô tả một dòng tiếng Việt thường
- Chip trạng thái lần chạy cuối:
  `✓ Thành công` (`--ok-soft`/`--ok-ink`) · `✕ Lỗi` (`--err-soft`/`--err`) ·
  `◐ Đang chạy` (`--acc-soft`/`--acc`)
- Thời điểm (`24/08/2026 06:00`) và thời lượng (`3 phút 20 giây`)
- **Biểu đồ thanh 10 lần chạy gần nhất**: thanh rộng 8px, bo 3px; thành công
  `rgba(42,145,135,.55)`, lỗi `--err`, đang chạy `--acc`. Chiều cao tỉ lệ thời lượng.
- Nút `Chạy` (nền `--btn`) và `Xem log`

**Viền thẻ theo trạng thái:**
- Lỗi: viền `rgba(192,94,112,.35)`
- Đang chạy: viền `--acc` + `box-shadow: 0 0 0 3px var(--acc-soft)`
- Bình thường: viền `--stroke`

**Thẻ đang chạy** thêm: thanh tiến trình, `812 / 1.310 bản ghi`,
`còn ≈ 1 phút 20 giây`, nút đổi thành `Đang chạy…` nền `--fill` chữ `--t4` (vô hiệu).

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L53 | **7 thẻ**: Embedding · Khách sạn · OTA · Google Maps · OSM · Tour · Địa điểm lân cận | Chỉ **4 DAG** thật (Phase 13). `hotel_pipeline.py`, `ota_pipeline.py`, `osm_pipeline.py` là **module thư viện**, không có `with DAG(...)` — không trigger được, không có lần chạy nào để hiển thị | **Render 4 thẻ**: Embedding · Google Maps · Tour · Địa điểm lân cận. Bỏ Khách sạn/OTA/OSM. Vẽ thẻ cho pipeline không tồn tại là hứa một nút không bấm được |
| L54 | Banner `Pipeline OTA lỗi lúc 06:12` | OTA không phải DAG (L53) | Banner vẫn giữ **cơ chế** — hiện khi bất kỳ DAG nào trong 4 cái có lần chạy cuối `failed`. Nội dung nội suy từ DAG thật |
| L55 | `Giá phòng của 2 khách sạn có thể đã cũ.` | Không suy ra được số này từ Airflow | Bỏ vế thứ hai. Banner chỉ nêu: `Pipeline {tên} lỗi lúc {giờ}.` + nút `Xem log` |
| L56 | `còn ≈ 1 phút 20 giây` | Airflow **không** trả thời gian còn lại | Ước tính = thời lượng trung bình các lần chạy thành công gần đây − thời gian đã chạy. Chưa đủ lịch sử → **ẩn dòng này**, chỉ hiện `Đã chạy 2 phút 14 giây` |
| L57 | `812 / 1.310 bản ghi` cho thẻ đang chạy | Airflow không trả tiến độ theo bản ghi; DAG dùng mapped task | Tiến độ = `mapped task đã xong / tổng mapped task` từ `taskInstances`. Đổi nhãn thành `{n}/{m} bước đã xong`. Riêng embedding: nhân số chunk × `chunk_size` để ra ước lượng bản ghi, và ghi rõ `≈` |
| L58 | Nút `Lịch sử lần chạy` | Không có màn riêng | Dẫn tới `/admin/pipelines/runs` — danh sách phẳng mọi lần chạy của 4 DAG (biến thể của C3, Phase 16). Chưa có Phase 16 thì **ẩn nút** |
| L59 | Nút `Chạy` trên thẻ **không phải** embedding | 3 DAG kia không có tham số | Trigger trực tiếp, chỉ có hộp thoại xác nhận đơn giản. Chỉ embedding mới mở hộp thoại C2 (Phase 15) |

**Nhãn và mô tả 4 pipeline** (tiếng Việt thường, không nhắc `dag_id`):

| dag_id | Nhãn | Mô tả |
|---|---|---|
| `embed_supabase_tables_pipeline` | Embedding | Dạy bot học lại dữ liệu khách sạn, phòng và địa điểm |
| `google_maps_poc_attractions_pipeline_supabase` | Google Maps | Cập nhật toạ độ, đánh giá và ảnh từ Google Maps |
| `tour_pipeline` | Tour | Đồng bộ tour và hoạt động quanh khách sạn |
| `hotel_nearby_attractions_pipeline_supabase` | Địa điểm lân cận | Tính các điểm đáng chú ý gần mỗi khách sạn |

Bảng này để ở **backend** (`pipelines.py`), không ở frontend — nó là một phần của
allowlist, và để một chỗ duy nhất định nghĩa "pipeline nào tồn tại".

## Backend — hợp đồng API

```
GET /api/v1/admin/pipelines
→ 200 {
    "connected": true,
    "items": [{
      "dag_id": "embed_supabase_tables_pipeline",
      "label": "Embedding",
      "description": "Dạy bot học lại dữ liệu khách sạn, phòng và địa điểm",
      "is_paused": false,
      "schedule": "@daily",
      "has_params": true,                  // chỉ embedding → mở hộp thoại C2
      "last_run": {
        "run_id": "manual__2026-08-24T10:38:00+00:00",
        "state": "running",                // success | failed | running | queued | null
        "start_date": "2026-08-24T10:38:00Z",
        "end_date": null,
        "duration_seconds": 134,
        "progress": {"done": 12, "total": 21, "eta_seconds": 80}   // null nếu không running
      },
      "recent_runs": [
        {"run_id":"...","state":"success","duration_seconds":200},
        ...                                 // tối đa 10, mới nhất cuối
      ]
    }]
  }
→ 200 { "connected": false, "items": [], "reason": "airflow_unavailable" }
```

```
POST /api/v1/admin/pipelines/{dag_id}/runs
  body: { "conf": {} }                     // embedding: xem Phase 15
→ 202 { "dag_id": "...", "run_id": "manual__...", "state": "queued" }
→ 400 { "detail": "dag_not_allowed" }
→ 409 { "detail": "dag_already_running" }
→ 503 { "detail": "airflow_unavailable" }
```

- `dag_id` kiểm allowlist ở **cả** route và client (Phase 13).
- `409` khi DAG đó đang có lần chạy `running`/`queued` — chạy chồng pipeline crawl là
  cách nhanh nhất để bị OTA chặn IP và tốn tiền API gấp đôi.
- Audit: `action='pipeline.trigger'`, `after={dag_id, conf, run_id}`.

Gọi Airflow: `GET /api/v2/dags/{dag_id}` + `GET .../dagRuns?limit=10&order_by=-start_date`
cho mỗi DAG → **4 DAG × 2 request = 8 request**. Gọi song song (thread pool), cache
kết quả 10 giây để việc admin bấm F5 liên tục không đấm vào Airflow.

## Frontend — màn hình C1

```
src/admin/pages/pipelines/
  pipelines-page.tsx
  pipeline-card.tsx
  pipeline-sparkline.tsx      biểu đồ 10 thanh
  pipeline-run-progress.tsx   thanh tiến trình + ETA
  pipeline-error-banner.tsx   L54, L55
```

- Có thẻ `running` → poll `GET /admin/pipelines` mỗi 5 giây. Không có thì mỗi 60 giây.
  Rời trang thì dừng poll.
- `connected: false` → hiện banner `! Không kết nối được Airflow — pipeline không
  chạy được lúc này.` (câu có sẵn trong bộ Z), thẻ hiện dạng skeleton nhạt, nút `Chạy`
  vô hiệu.
- Sparkline: chiều cao thanh chuẩn hoá theo thời lượng lớn nhất trong 10 lần, tối
  thiểu 6px để lần chạy rất nhanh vẫn thấy được.
- Nút `Chạy` ở thẻ Embedding → hộp thoại C2 (Phase 15). Ba thẻ kia → xác nhận đơn giản
  `Chạy pipeline {tên}?` + hậu quả một dòng.

## Related Code Files

- Modify: `backend/src/api/admin/pipelines.py`
- Create: `backend/tests/test_api/test_admin_pipelines.py`
- Create: `frontend/src/admin/pages/pipelines/**`, `frontend/src/admin/api/pipelines-client.ts`
- Modify: `frontend/src/admin/router.tsx`
- Reference: `backend/src/services/airflow_client.py` (Phase 13)

## Implementation Steps

1. Bảng nhãn/mô tả 4 DAG trong `pipelines.py`, dùng chung với allowlist.
2. `GET /admin/pipelines` — gọi song song, cache 10s, dựng `progress` từ `taskInstances`.
3. `POST .../runs` + guard `409`.
4. Test bằng fixture của Phase 13.
5. Dựng thẻ theo checklist; sparkline và viền thẻ theo đúng style thiết kế.

## Success Criteria

- [ ] Đúng **4 thẻ**, không có Khách sạn / OTA / OSM (L53)
- [ ] Airflow tắt → `connected:false`, banner hiện, nút `Chạy` vô hiệu, màn **không** vỡ
- [ ] Trigger `clear_airflow_history` qua API → `400 dag_not_allowed`
- [ ] Trigger DAG đang chạy → `409`, không tạo lần chạy thứ hai
- [ ] Thẻ đang chạy có viền `--acc` + quầng sáng, nút đổi thành `Đang chạy…` vô hiệu
- [ ] Sparkline hiện đúng 10 thanh, thanh cuối đổi màu theo trạng thái lần chạy mới nhất
- [ ] Chưa đủ lịch sử → **không** hiện ETA bịa (L56)
- [ ] Poll 5s khi đang chạy, 60s khi rảnh, dừng khi rời trang (kiểm bằng tab Network)
- [ ] Bấm F5 liên tục 10 lần → Airflow chỉ nhận ≤ 8 request (cache 10s)
- [ ] `admin_audit_log` ghi mỗi lần trigger
- [ ] Không chỗ nào trên UI hiện chữ `dag_id` hay tên DAG kỹ thuật

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Vẽ 7 thẻ theo thiết kế → 3 nút bấm không được | Cao | L53 quyết định rõ; có mục trong Success Criteria |
| Poll 5s × nhiều tab đấm sập Airflow | Cao | Cache 10s ở backend; dừng poll khi rời trang |
| Chạy chồng pipeline crawl → bị OTA chặn IP | Cao | Guard `409` |
| ETA/tiến độ bịa làm admin tin nhầm rồi bỏ đi | Trung bình | Ẩn khi không đủ dữ liệu; luôn có dấu `≈` |
| `taskInstances` của mapped task trả cấu trúc lạ làm tính tiến độ sai | Trung bình | Fixture từ lần chạy embedding thật (Phase 13 bước 1) |
