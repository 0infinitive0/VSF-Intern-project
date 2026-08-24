---
phase: 15
title: "Chạy pipeline embedding (C2)"
status: pending
priority: P1
effort: "1.5d"
dependencies: [14, 12]
---

# Phase 15: Chạy pipeline embedding — C2

## Overview

Hộp thoại duy nhất trong cả portal **tiêu tiền thật** (phí API embedding). Thiết kế
phải chống bấm nhầm, và phần backend phải truyền tham số **an toàn với chạy đồng thời**.

**Thiết kế bám theo:** artboard `C2 · HỘP THOẠI CHẠY PIPELINE EMBEDDING`, cả hai biến
thể: `① Chỉ dữ liệu mới — nút sẵn sàng` và `② Chạy lại toàn bộ — nút khoá tới khi
xác nhận chi phí`.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Tiêu đề:** `Chạy pipeline embedding`
**Phụ đề:** `Mỗi bản ghi nhúng lại đều tính phí API. Chọn phạm vi trước khi chạy.`

**Hai thẻ radio lớn:**

① `Chỉ dữ liệu mới` + huy hiệu `KHUYẾN NGHỊ`
`Chỉ nhúng các bản ghi chưa có embedding. Ước tính **86 bản ghi** · ≈ 40 giây.`

② `Chạy lại toàn bộ`
`Nhúng lại tất cả **1.310 bản ghi** (64 khách sạn · 1.246 phòng)`
· `Thời gian ước tính **9 phút** — bot trả kết quả cũ trong lúc chạy`
· `Tốn phí API cho toàn bộ bản ghi, kể cả bản ghi không đổi`

Khi chọn ②, mô tả **bung ra thành 3 gạch đầu dòng** như trên; khi chọn ① thì thu gọn
thành một dòng.

**`Bảng áp dụng`** — chip nhiều lựa chọn kèm số đếm:
`✓ Khách sạn · 64` · `✓ Phòng · 1.246` · `Địa điểm · 312`
(chip bật dùng style `--acc-soft`/`--acc` như tab Tiện ích ở B3)

**`Tuỳ chọn nâng cao ▾`** (thu gọn): `giới hạn bản ghi · kích thước lô`

**Khoá xác nhận cho lựa chọn ②** — hai bước, **cả hai** phải xong mới mở nút:
1. Tick `Tôi hiểu lần chạy này tốn phí API cho 1.310 bản ghi.`
2. Gõ đúng `CHẠY TOÀN BỘ` vào ô text
Ghi chú dưới ô: `Nút mở khoá khi đã tick và gõ đúng`

**Nút:**
- ①: `Huỷ` · `Nhúng 86 bản ghi mới`
- ②: `Huỷ` · `Nhúng lại 1.310 bản ghi`

Nút chính **luôn nêu số bản ghi thật**, không phải "Chạy".

**LƯU Ý (đã ghi trong prompt thiết kế):** chỉ 3 bảng có embedding. **Bảng giá phòng
KHÔNG có** — không được đưa vào `Bảng áp dụng`.

## Vấn đề then chốt: truyền tham số bằng `conf`, không phải Airflow Variables

`embed_supabase_dag.py` hiện đọc tham số từ **Airflow Variables** toàn cục:

```python
only_null   = Variable.get("embed_supabase_only_null",   default_var="true")   # dòng 210
force_tables= Variable.get("embed_supabase_force_tables", default_var="")      # dòng 216
batch_limit = int(Variable.get("embed_supabase_batch_limit", default_var="1000"))  # dòng 224
chunk_size  = max(1, int(Variable.get("embed_supabase_chunk_size", default_var="25")))  # dòng 257
```

Nếu portal set Variable rồi trigger, thì:
- Lần chạy `@daily` kế tiếp **kế thừa** tham số admin vừa đặt — chạy full re-embed
  hàng ngày mà không ai biết, đốt tiền API liên tục.
- Hai lần trigger gần nhau **giẫm lên nhau**: lần chạy đầu đọc Variable của lần thứ hai.

**Giải pháp:** đọc `dag_run.conf` trước, rơi về Variable nếu không có.

```python
def _param(context, key, default):
    conf = (context["dag_run"].conf or {}) if context.get("dag_run") else {}
    if key in conf:
        return conf[key]
    return Variable.get(f"embed_supabase_{key}", default_var=default)
```

Sửa 4 chỗ đọc Variable trong `fetch_pending_rows_task` thành `_param(...)`.
Task cần `**context` (hoặc `get_current_context()`).

Đây là thay đổi **duy nhất** được phép trong `embed_supabase_dag.py` ở plan này.
**Không** đụng `_build_text`, `TABLE_COLUMNS`, hay logic embedding — chỉ nguồn đọc
tham số. Hành vi mặc định (không có `conf`) giữ nguyên byte-for-byte, nên lần chạy
`@daily` không đổi gì.

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L60 | `Địa điểm · 312` | Bảng thật là `attractions`, và nó **có** trong `TABLE_COLUMNS` | Giữ. Nhãn tiếng Việt `Địa điểm`, giá trị gửi đi là `attractions` |
| L61 | `Ước tính 86 bản ghi · ≈ 40 giây` | Số bản ghi lấy từ `GET /admin/embedding/summary` (Phase 12). **Thời gian** thì không có nguồn | Số bản ghi: thật. Thời gian: tính từ thời lượng trung bình các lần chạy thành công gần đây ÷ số bản ghi lần đó × số bản ghi lần này. Chưa có lịch sử → **ẩn phần thời gian** |
| L62 | `1.310 bản ghi (64 khách sạn · 1.246 phòng)` | `total` của các bảng đang chọn | Nội suy từ `Bảng áp dụng` đang tick — bỏ tick `Phòng` thì số phải giảm ngay |
| L63 | `Chạy lại toàn bộ` = `only_null=false` cho **mọi** bảng | DAG có `force_tables` cho phép full re-embed **từng bảng** | Ánh xạ: `Bảng áp dụng` = `force_tables` khi chọn ②; khi chọn ① thì `only_null=true` + `force_tables=""`. Xem bảng ánh xạ bên dưới |
| L64 | `bot trả kết quả cũ trong lúc chạy` | Đúng: full re-embed set lại vector từng dòng, dòng chưa tới lượt vẫn giữ vector cũ | Giữ nguyên câu — nó chính xác |
| L65 | `Tuỳ chọn nâng cao` chỉ ghi tên | `batch_limit` (mặc định 1000, `0` = không giới hạn) và `chunk_size` (mặc định 25, ảnh hưởng `max_map_length` của Airflow) | Hai ô số có mô tả tiếng Việt + giá trị mặc định. `chunk_size` ghi chú: `Giảm quá thấp có thể vượt giới hạn của Airflow.` |

**Ánh xạ lựa chọn UI → `conf` gửi cho Airflow:**

| UI | `only_null` | `force_tables` |
|---|---|---|
| ① Chỉ dữ liệu mới, chọn Khách sạn + Phòng | `true` | `""` |
| ② Chạy lại toàn bộ, chọn Khách sạn + Phòng | `true` | `"hotels,rooms"` |
| ② Chạy lại toàn bộ, chọn cả 3 | `true` | `"hotels,rooms,attractions"` |

Dùng `force_tables` thay vì `only_null=false` **có chủ đích**: `only_null=false` là
công tắc toàn cục ép mọi bảng chạy full, kể cả bảng admin không chọn.
`force_tables` diễn đạt đúng ý "chỉ những bảng này chạy full", và DAG đã hỗ trợ sẵn
(`embed_supabase_dag.py:212-218`).

> Ở chế độ ①, các bảng **không** được tick vẫn chạy backfill `only_null` — vì
> `fetch_pending_rows_task` map qua cả 3 bảng cố định. Muốn thật sự loại một bảng
> phải thêm tham số mới vào DAG. **Chấp nhận:** backfill NULL rất rẻ; đưa vào phần
> ghi chú của hộp thoại: `Bảng không chọn vẫn được nhúng bổ sung nếu có bản ghi mới.`

## Backend — hợp đồng API

```
GET /api/v1/admin/pipelines/embedding/estimate
→ 200 {
    "tables": [
      {"table":"hotels","label":"Khách sạn","total":64,"missing":0},
      {"table":"rooms","label":"Phòng","total":1246,"missing":62},
      {"table":"attractions","label":"Địa điểm","total":312,"missing":0}
    ],
    "seconds_per_record": 0.41,       // null nếu chưa đủ lịch sử  (L61)
    "defaults": {"batch_limit": 1000, "chunk_size": 25}
  }
```

Tái dùng `GET /admin/embedding/summary` (Phase 12) cho phần đếm — **không** viết
truy vấn đếm thứ hai. `seconds_per_record` tính từ `recent_runs` của DAG embedding.

```
POST /api/v1/admin/pipelines/embed_supabase_tables_pipeline/runs
  body: {
    "conf": {
      "only_null": true,
      "force_tables": "hotels,rooms",
      "batch_limit": 1000,
      "chunk_size": 25
    },
    "acknowledged_full_reembed": true     // bắt buộc khi force_tables khác rỗng
  }
→ 202 { "run_id": "manual__...", "state": "queued", "estimated_records": 1310 }
→ 400 { "detail": "full_reembed_not_acknowledged" }
→ 409 { "detail": "dag_already_running" }
```

- `acknowledged_full_reembed` là chốt **phía server** cho bước tick+gõ ở UI. Khoá chỉ
  ở frontend là khoá bằng giấy — `curl` đi vòng qua nó trong 3 giây.
- Validate `force_tables` chỉ chứa `hotels|rooms|attractions`; giá trị khác → `422`.
  Không bao giờ chuyển tiếp chuỗi tuỳ ý vào `conf`.
- `batch_limit ∈ [0, 100000]`, `chunk_size ∈ [1, 500]`.
- Audit: `action='pipeline.trigger'`, `after` chứa cả `conf` — để về sau truy được
  ai đã bấm full re-embed.

## Frontend — hộp thoại C2

```
src/admin/pages/pipelines/
  embedding-run-dialog.tsx
  embedding-scope-cards.tsx     2 thẻ radio
  embedding-table-chips.tsx     Bảng áp dụng
  embedding-advanced.tsx        L65
```

- Nút chính vô hiệu cho tới khi: (chế độ ①) đã chọn ≥ 1 bảng; (chế độ ②) đã chọn
  ≥ 1 bảng **và** đã tick **và** đã gõ đúng `CHẠY TOÀN BỘ`.
- So chuỗi gõ vào: cắt khoảng trắng đầu/cuối, **phân biệt hoa thường** (đúng thiết kế
  — đó là điểm ma sát có chủ đích).
- Số trên nút cập nhật ngay khi đổi lựa chọn bảng (L62).
- Đóng hộp thoại giữa chừng → reset toàn bộ, không nhớ trạng thái tick/gõ.
- Sau `202`: đóng hộp thoại, banner `✓ Đã bắt đầu chạy pipeline embedding.`,
  C1 chuyển thẻ đó sang `Đang chạy` và bật poll 5s.
- Mở được từ 3 chỗ: nút `Chạy embedding` ở header C1, nút `Chạy` trên thẻ Embedding,
  và nút ở C4 (Phase 12). **Cùng một component.**

## Related Code Files

- Modify: `backend/src/airflow/dags/data_pipeline/embed_supabase_dag.py` (**chỉ** 4 chỗ đọc tham số + hàm `_param`)
- Modify: `backend/src/api/admin/pipelines.py`
- Modify: `backend/tests/test_api/test_admin_pipelines.py`
- Create: `backend/src/airflow/tests/test_embed_dag_params.py` (kiểm `_param` ưu tiên `conf`)
- Create: `frontend/src/admin/pages/pipelines/embedding-run-dialog.tsx` + 3 file con
- Modify: `frontend/src/admin/pages/pipelines/pipelines-page.tsx`, `frontend/src/admin/pages/embedding/embedding-coverage-page.tsx`
- Reference: `backend/src/airflow/dags/data_pipeline/embed_supabase_dag.py` (docstring đầu file mô tả đủ 4 Variable)

## Implementation Steps

1. Sửa DAG: thêm `_param`, đổi 4 chỗ. Test rằng **không có `conf`** thì hành vi y hệt
   trước (đây là điều kiện để không phá lần chạy `@daily`).
2. Trigger thật một lần với `conf` qua `curl`, xác nhận DAG đọc đúng.
3. `GET .../embedding/estimate` (tái dùng summary của Phase 12).
4. `POST .../runs` + validate + guard `acknowledged_full_reembed`.
5. Test backend, đặc biệt: gọi thẳng bằng `curl` với `force_tables` mà không có
   `acknowledged_full_reembed` → phải `400`.
6. Hộp thoại theo checklist.

## Success Criteria

- [ ] DAG không nhận `conf` → hành vi giống hệt trước khi sửa (test)
- [ ] Trigger với `conf={"force_tables":"hotels"}` → log DAG in `only_null=False` cho `hotels`, `True` cho `rooms`/`attractions`
- [ ] Airflow **Variables không bị portal ghi vào** (`grep Variable.set` trong backend không ra gì)
- [ ] `curl` gọi thẳng với `force_tables` mà thiếu `acknowledged_full_reembed` → `400`
- [ ] `force_tables="room_prices"` → `422`
- [ ] Nút chính vô hiệu cho tới khi tick + gõ đúng `CHẠY TOÀN BỘ` (phân biệt hoa thường)
- [ ] Bỏ tick `Phòng` → số trên nút giảm đúng
- [ ] Chưa có lịch sử chạy → **không** hiện ước tính thời gian (L61)
- [ ] `Bảng áp dụng` **không** có `room_prices` / `Giá phòng`
- [ ] Hộp thoại mở được từ cả 3 chỗ, dùng chung một component
- [ ] `admin_audit_log` lưu đủ `conf` của lần trigger

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Dùng Airflow Variables → lần chạy `@daily` kế thừa full re-embed, đốt tiền API mỗi ngày | **Cao nhất** | Chuyển sang `dag_run.conf`; có mục grep `Variable.set` trong Success Criteria |
| Khoá xác nhận chỉ ở frontend | **Cao** | `acknowledged_full_reembed` kiểm ở server; có test `curl` |
| Sửa DAG làm hỏng lần chạy theo lịch đang chạy tốt | **Cao** | `_param` rơi về Variable khi không có `conf`; test hành vi mặc định không đổi |
| Chuyển tiếp `conf` tuỳ ý vào Airflow | Cao | Allowlist khoá + validate giá trị; không nhận key lạ |
| `chunk_size` quá nhỏ → vượt `max_map_length` (1024) của Airflow, cả lần chạy hỏng | Trung bình | Chặn `chunk_size ≥ 1`; ghi chú cảnh báo trên UI; cân nhắc chặn theo `tổng bản ghi / chunk_size ≤ 1000` |
| Admin bấm full re-embed rồi bot trả kết quả cũ mà không hiểu vì sao | Trung bình | Câu `bot trả kết quả cũ trong lúc chạy` là bắt buộc, không được cắt (L64) |
