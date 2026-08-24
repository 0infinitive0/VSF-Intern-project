---
phase: 16
title: "Chi tiết lần chạy + log (C3)"
status: pending
priority: P1
effort: "1.5d"
dependencies: [14]
---

# Phase 16: Chi tiết lần chạy + log — C3

## Overview

Đây là **đường duy nhất** để nhóm vận hành xem vì sao pipeline lỗi (quyết định #4 —
họ không có tài khoản Airflow). Vì vậy C3 là P0, không phải tiện ích.

**Thiết kế bám theo:** artboard `C3 · CHI TIẾT LẦN CHẠY + LOG`.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb `Quản trị · Dữ liệu bot · Pipeline · Lần chạy #4182` ·
tiêu đề `Embedding · lần chạy #4182` · chip `✕ Lỗi` ·
nút `↓ Tải log` · nút `Chạy lại task lỗi`

**Bốn ô tóm tắt:** `Bắt đầu 24/08/2026 10:38` · `Thời lượng 3 phút 58 giây` ·
`Bản ghi đã xử lý 1.248 / 1.310` · `Bản ghi lỗi 62`

**Cột trái — `Các bước trong lần chạy`** + đếm `3/6 xong`:

| Bước | Chi tiết | Thời lượng | Trạng thái |
|---|---|---|---|
| Tải danh sách khách sạn | 64 khách sạn | 0:42 | `✓` |
| Chuẩn hoá mô tả & tiện ích | 64 bản ghi | 0:18 | `✓` |
| Sinh embedding khách sạn | 64 / 64 bản ghi | 1:05 | `✓` |
| Sinh embedding phòng | 1.184 / 1.246 bản ghi · 62 lỗi | 3:36 | `✕` **đang chọn** |
| Sinh embedding địa điểm | Bỏ qua do task trước lỗi | — | `–` |
| Ghi vào vector store | Chưa chạy | — | `○` |

Biểu tượng trạng thái — vòng tròn 22px:
`✓` `--ok`/`--ok-soft` · `✕` `--err`/`--err-soft` · `–` (bỏ qua) `--t4`/`--fill` ·
`○` (chưa chạy) `--t4`/`--fill`

Dòng đang chọn: nền `--err-soft`, `inset 3px 0 0 var(--err)`, tên bước weight 700.

**Banner dưới danh sách bước:**
`62 phòng chưa nhúng — bot sẽ không gợi ý các phòng này cho tới khi chạy lại thành công.`

**Cột phải — khung log:**
- Ô lọc `⌕ Lọc trong log…`
- Chip lọc `Chỉ dòng lỗi · 3` · `Cảnh báo · 1`
- Toggle `Tự cuộn`
- Dòng log: `font-family: ui-monospace...; font-size: 12px; line-height: 1.5`,
  ba cột `{time}` `{lvl}` `{msg}`
  - Cột `lvl` rộng 52px, weight 700
  - `ERROR`: nền dòng `rgba(192,94,112,.10)`, chữ `--err`
  - `WARN`: nền dòng `rgba(200,128,47,.10)`, chữ `--warn-ink`
  - `OK`: chữ `--ok-ink` · `INFO`: chữ `--t2`
- Chân khung: `11 dòng · lần chạy #4182` · bên phải `run_id 4182 · dag embedding_v3`

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L66 | `lần chạy #4182`, `run_id 4182` (số nguyên) | Airflow `dag_run_id` là chuỗi kiểu `manual__2026-08-24T10:38:00+00:00` | Hiển thị `#` + 4 ký tự cuối của hash `run_id`, giữ `run_id` đầy đủ ở chân khung và trong URL. Không bịa số nguyên |
| L67 | `dag embedding_v3` | `dag_id` thật là `embed_supabase_tables_pipeline` | Chân khung ghi `dag_id` thật. Đây là chỗ **duy nhất** trên UI được hiện tên kỹ thuật (nó là thông tin để báo lỗi cho kỹ thuật viên) |
| L68 | 6 bước có tên tiếng Việt đẹp | Task id thật trong DAG: `fetch_pending_rows_task`, `embed_chunk_task`, `summarize_task` — **3 task**, trong đó `embed_chunk_task` là **mapped task** (nhiều instance) | Cần **bảng ánh xạ task_id → nhãn tiếng Việt** trong `pipelines.py`. Task chưa có trong bảng → hiện `task_id` thô, không ẩn đi. Mapped task gộp thành **một dòng** kèm `{xong}/{tổng} · {lỗi} lỗi` |
| L69 | `Bản ghi đã xử lý 1.248 / 1.310` | Airflow không trả số bản ghi | Ước lượng từ mapped task: `(instance thành công) × chunk_size`. Ghi rõ `≈`. Không có `conf` để biết `chunk_size` → **ẩn hai ô này**, chỉ giữ `Bắt đầu` và `Thời lượng` |
| L70 | Nút `Chạy lại task lỗi` | Airflow 3 có `PATCH /api/v2/dags/{dag_id}/dagRuns/{run_id}/taskInstances/{task_id}` với `new_state: failed` để clear/retry | **Xác nhận đường dẫn thật ở Phase 13 bước 1.** Không xác nhận được → **ẩn nút**, thay bằng `Chạy lại pipeline` (trigger lần chạy mới) — vẫn giải quyết được vấn đề, chỉ tốn hơn |
| L71 | Nút `↓ Tải log` | Ghép log mọi task thành một file | Giữ. Trả `text/plain`, tên file `{dag_id}_{run_id}.log` |
| L72 | Log mẫu ghi `(1.536 chiều)` | Vector thật là **1024 chiều** (`EMBEDDING_DIMENSION = 1024`) | Chỉ là dữ liệu mẫu trong thiết kế, log thật do DAG in ra. Không phải việc phải sửa |
| L73 | Chip lọc `Chỉ dòng lỗi · 3` | Log Airflow là **text thô**, không có trường level | Parse level bằng regex từ đầu dòng (`INFO`/`WARNING`/`ERROR`/`CRITICAL` — định dạng logger mặc định của Airflow). Không parse được → xếp `INFO`. **Số đếm phải là số thật sau khi parse**, không phải số cứng |

## Backend — hợp đồng API

```
GET /api/v1/admin/pipelines/{dag_id}/runs?limit=25&page=1
→ 200 { "items": [{"run_id":"...","state":"failed","start_date":"...",
                   "end_date":"...","duration_seconds":238,"note":null}],
        "total": 120 }
```

Đây cũng là màn `Lịch sử lần chạy` (L58 của Phase 14).

```
GET /api/v1/admin/pipelines/{dag_id}/runs/{run_id}
→ 200 {
    "dag_id": "embed_supabase_tables_pipeline",
    "label": "Embedding",
    "run_id": "manual__2026-08-24T10:38:00+00:00",
    "short_id": "#4182",
    "state": "failed",
    "start_date": "...", "end_date": "...", "duration_seconds": 238,
    "conf": {"only_null": true, "force_tables": ""},
    "steps": [{
      "task_id": "embed_chunk_task",
      "label": "Sinh embedding phòng",
      "state": "failed",
      "duration_seconds": 216,
      "detail": "48 / 50 nhóm xong · 2 lỗi",
      "mapped": true, "total": 50, "succeeded": 48, "failed": 2,
      "try_number": 2
    }],
    "steps_done": 3, "steps_total": 6,
    "records": {"processed": 1248, "total": 1310, "failed": 62, "approximate": true}
  }
```

`records` là `null` khi không suy ra được (L69) — frontend ẩn hai ô tương ứng.

```
GET /api/v1/admin/pipelines/{dag_id}/runs/{run_id}/logs?task_id=&try_number=
→ 200 {
    "lines": [{"time":"10:41:26","level":"ERROR",
               "message":"rooms: lô 19 thất bại — HTTP 429..."}],
    "counts": {"ERROR": 3, "WARNING": 1, "INFO": 7, "OK": 0},
    "truncated": false
  }
```

- `task_id` rỗng → ghép log **mọi** task theo thứ tự thời gian.
- Parse level bằng regex, chuẩn hoá `WARNING` → hiển thị `WARN`.
- **Chặn cứng 5.000 dòng / 2 MB**, `truncated: true` khi vượt. Log Airflow có thể
  hàng trăm MB — kéo hết về là sập cả backend lẫn trình duyệt.
- **Che dữ liệu nhạy cảm** trước khi trả: log DAG có thể chứa `SUPABASE_SERVICE_KEY`,
  `EMBEDDING_API_KEY` trong thông báo lỗi HTTP. Thay bằng `***` theo regex cho các
  chuỗi dạng khoá (`eyJ...`, `Bearer ...`, `sk-...`, `apikey=...`). **Bắt buộc** —
  portal này mở cho nhân viên vận hành, không phải kỹ sư hạ tầng.

```
GET  .../runs/{run_id}/logs/download   → text/plain, cùng quy tắc che
POST .../runs/{run_id}/retry-failed    → 202 { "cleared_tasks": 1 }   (L70)
                                       → 501 { "detail": "retry_not_supported" }
```

## Frontend — màn hình C3

```
src/admin/pages/pipelines/
  run-detail-page.tsx
  run-steps-list.tsx
  run-log-viewer.tsx
  run-summary-cards.tsx
  runs-history-page.tsx     L58 — danh sách lần chạy
```

- Lần chạy đang `running` → poll `run detail` + log mỗi 5 giây; `Tự cuộn` bật mặc
  định khi đang chạy, tắt mặc định khi đã xong.
- `Tự cuộn` tự tắt khi người dùng cuộn ngược lên (hành vi chuẩn của log viewer).
- Ô lọc text lọc **phía client** trên `lines` đã tải.
- Click một bước bên trái → tải log của riêng task đó.
- Khung log cuộn dọc trong container riêng, **không** để trang cuộn ngang.
- Route `/admin/pipelines/runs/:runId` — `run_id` phải `encodeURIComponent` (nó chứa
  `:` và `+`).

## Related Code Files

- Modify: `backend/src/api/admin/pipelines.py`
- Create: `backend/src/api/admin/log_redaction.py` (regex che khoá)
- Modify: `backend/src/services/airflow_client.py`
- Modify: `backend/tests/test_api/test_admin_pipelines.py`
- Create: `backend/tests/test_log_redaction.py`
- Create: `frontend/src/admin/pages/pipelines/run-detail-page.tsx` + 4 file con
- Modify: `frontend/src/admin/router.tsx`

## Implementation Steps

1. Dùng fixture log thật từ Phase 13 bước 1 → viết parser level + bảng ánh xạ
   `task_id` → nhãn.
2. `log_redaction.py` + test với chuỗi khoá thật (giả) trong log.
3. Ba endpoint + giới hạn dòng/dung lượng.
4. Xác nhận đường dẫn retry (L70); không có thì trả `501` và ẩn nút.
5. Dựng màn theo checklist.

## Success Criteria

- [ ] Mở một lần chạy lỗi thật → thấy đúng các bước, bước lỗi được đánh dấu và tự chọn
- [ ] Mapped task gộp thành **một** dòng kèm `{xong}/{tổng} · {lỗi} lỗi`
- [ ] Chip `Chỉ dòng lỗi · N` — `N` là số thật sau khi parse, khớp số dòng ERROR
- [ ] Log chứa `SUPABASE_SERVICE_KEY=eyJhbGci...` → trả về `***`, **không** lộ khoá (test bắt buộc)
- [ ] Log 50.000 dòng → trả tối đa 5.000, `truncated:true`, UI báo `Log đã bị cắt bớt`
- [ ] `Tự cuộn` tự tắt khi cuộn ngược lên
- [ ] `↓ Tải log` tải được file, nội dung cũng đã che khoá
- [ ] `run_id` chứa `:` và `+` vẫn điều hướng và tải đúng (encodeURIComponent)
- [ ] Không xác nhận được retry → nút ẩn, không render nút chết
- [ ] Airflow tắt → trang hiện trạng thái lỗi của Phase 3, không vỡ
- [ ] Chân khung hiện `dag_id` thật, không phải `embedding_v3` (L67)

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Log lộ `SUPABASE_SERVICE_KEY` / `EMBEDDING_API_KEY` cho nhân viên vận hành | **Cao nhất** | `log_redaction.py` + test bắt buộc; áp cho cả API và file tải về |
| Kéo log hàng trăm MB → sập backend hoặc treo trình duyệt | **Cao** | Chặn 5.000 dòng / 2 MB ở backend |
| Mapped task làm danh sách bước thành hàng trăm dòng | Cao | Gộp theo `task_id`; test với lần chạy embedding thật |
| Bảng ánh xạ `task_id` sót → bước biến mất khỏi UI | Trung bình | Task lạ hiện `task_id` thô, không ẩn |
| `run_id` không encode → 404 hoặc route hỏng | Trung bình | `encodeURIComponent`; có mục kiểm |
| Poll log 5s trên lần chạy dài kéo băng thông | Trung bình | Dùng `continuation_token`/offset nếu Airflow hỗ trợ; nếu không thì giãn poll lên 10s khi log > 1.000 dòng |
