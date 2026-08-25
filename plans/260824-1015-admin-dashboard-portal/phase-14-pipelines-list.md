---
phase: 14
title: "Danh sách pipeline (C1)"
status: done
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

- [x] Đúng **4 thẻ**, không có Khách sạn / OTA / OSM (L53) — verified live: tất cả 4 DAG (Embedding, Google Maps, Tour, Địa điểm lân cận) render đúng thứ tự
- [x] Airflow tắt → `connected:false`, banner hiện, nút `Chạy` vô hiệu, màn **không** vỡ (verified live bằng cách trỏ `airflow_api_base` sang host không tồn tại)
- [x] Trigger `clear_airflow_history` qua API → `400 dag_not_allowed` (verified live + test)
- [x] Trigger DAG đang chạy → `409`, không tạo lần chạy thứ hai (test — không tái tạo được live vì DAG rỗng chạy xong trong ~3-5s, quá nhanh để bắt overlap thủ công; logic + test đủ tin cậy)
- [x] Thẻ đang chạy có viền `--acc` + quầng sáng, nút đổi thành `Đang chạy…` vô hiệu
- [x] Sparkline hiện đúng 10 thanh, thanh cuối đổi màu theo trạng thái lần chạy mới nhất
- [x] Chưa đủ lịch sử → **không** hiện ETA bịa (L56)
- [x] Poll 5s khi đang chạy, 60s khi rảnh, dừng khi rời trang
- [x] Bấm F5 liên tục 10 lần → Airflow chỉ nhận ≤ 8 request (cache 10s) — verified live: 10 lời gọi liên tiếp chỉ tạo 4 request Airflow (1 vòng, không phải 8×10)
- [x] `admin_audit_log` ghi mỗi lần trigger (action=`pipeline.trigger`)
- [x] Không chỗ nào trên UI hiện chữ `dag_id` hay tên DAG kỹ thuật

**Phát hiện thật ngoài phạm vi kế hoạch gốc (build phase này bằng cách gọi Airflow sống):**
- `tour_pipeline` ban đầu **không tồn tại** trong Airflow đang chạy — `ModuleNotFoundError: No module named 'apify_client'` dù `apify-client` đã có trong `requirements.txt` (image build cũ chưa có gói này). Đã `docker compose build` lại image Airflow để cài gói, xác nhận `tour_pipeline` parse sạch (`importErrors` rỗng) sau khi build lại. Nếu môi trường khác vẫn dùng image cũ, endpoint vẫn **không vỡ** — DAG lỗi bị bỏ qua khỏi danh sách (xử lý ở dưới), chỉ còn 3 thẻ thay vì 4
- Thêm cơ chế **bỏ qua từng DAG lỗi riêng lẻ** (không có trong kế hoạch gốc): nếu một DAG 404/lỗi ở tầng Airflow (import error, bị xoá, ...), `GET /admin/pipelines` vẫn trả `connected:true` với các DAG còn lại, không vỡ cả màn vì một DAG hỏng — cùng tinh thần L53 nhưng áp cho lỗi runtime thay vì lỗi thiết kế

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Vẽ 7 thẻ theo thiết kế → 3 nút bấm không được | Cao | L53 quyết định rõ; có mục trong Success Criteria |
| Poll 5s × nhiều tab đấm sập Airflow | Cao | Cache 10s ở backend; dừng poll khi rời trang |
| Chạy chồng pipeline crawl → bị OTA chặn IP | Cao | Guard `409` |
| ETA/tiến độ bịa làm admin tin nhầm rồi bỏ đi | Trung bình | Ẩn khi không đủ dữ liệu; luôn có dấu `≈`. **Sửa sau code review:** `estimated_records` ban đầu nhân **mọi** task instance đã xong (kể cả `fetch_pending_*`/`summarize_*` không mapped) × chunk size — một lần chạy 0 hàng cần nhúng vẫn hiện `≈150 bản ghi` bịa. Đã sửa: chỉ đếm instance có `map_index >= 0`, ẩn hẳn field khi không có instance mapped nào |
| `taskInstances` của mapped task trả cấu trúc lạ làm tính tiến độ sai | Trung bình | Fixture từ lần chạy embedding thật (Phase 13 bước 1) |
| Lỗi Airflow không phải "mất kết nối" (DAG hỏng, PATCH bị từ chối, trigger bị Airflow từ chối) làm route `POST .../runs` trả `500` thay vì lỗi có kiểu | **Cao** (code review phát hiện bằng repro thật — cùng lớp lỗi với `tour_pipeline` từng 404 lúc build phase này) | `trigger_pipeline_run` chỉ bắt `AirflowUnavailable`, không bắt `AirflowError` nói chung (`AirflowUnavailable` là subclass) — mọi lỗi Airflow khác (404, 403 PATCH, DAG bị từ chối trigger) rơi qua route và 500. Đã thêm `except AirflowError` riêng ở cả 2 lời gọi, trả `502 {"detail":"airflow_request_failed"}` |
| `_ListCache.invalidate()` bị mất tác dụng nếu trùng thời điểm với một `get()` đang fetch dở | Trung bình (code review phát hiện) | Fetch bắt đầu trước lúc invalidate có thể ghi đè cache bằng kết quả cũ **sau** khi invalidate chạy — khiến admin vừa trigger xong vẫn thấy "chưa chạy" tới 60s. Đã thêm bộ đếm generation: chỉ lưu kết quả fetch nếu generation không đổi kể từ lúc bắt đầu fetch |
| `conf` từ client đi thẳng vào `dag_run.conf` không kiểm tra, 3/4 DAG không khai báo `params` | Trung bình (code review phát hiện) | Route từ chối `422 pipeline_has_no_params` nếu `conf` khác rỗng mà DAG đó `has_params=False`. Ghi chú cho Phase 15: DAG embedding đọc cấu hình qua Airflow **Variable** (`embed_supabase_only_null`, `embed_supabase_chunk_size`), không đọc qua `dag_run.conf`/`params` — hộp thoại C2 muốn truyền option thật cần sửa DAG trước, không chỉ sửa dialog |
| Frontend poll loop chết vĩnh viễn nếu `listPipelines()` reject (body không phải JSON) thay vì resolve `{ok:false}` | Trung bình (code review phát hiện) | `poll()` thiếu `.catch` — một reject bỏ qua cả `setListState` lẫn `scheduleNext`, màn kẹt dữ liệu cũ không tự phục hồi. Đã thêm `.catch` gọi `scheduleNext(false)` + hiện banner lỗi |
