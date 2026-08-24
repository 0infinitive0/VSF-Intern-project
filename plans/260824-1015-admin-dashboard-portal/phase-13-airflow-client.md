---
phase: 13
title: "Airflow client + hạ tầng mạng/credential"
status: pending
priority: P1
effort: "1.5d"
dependencies: [2]
---

# Phase 13: Airflow client + hạ tầng mạng/credential

## Overview

Không có màn hình. Đây là phase gom **toàn bộ rủi ro hạ tầng** của nhánh Pipeline vào
một chỗ, để C1/C2/C3 (Phase 14–16) chỉ còn là việc dựng UI trên một client đã chạy.

Người dùng portal **không có tài khoản Airflow** (quyết định #4) → backend giữ
credential, frontend không bao giờ thấy.

## Sự thật đã kiểm chứng về môi trường

| Điều | Bằng chứng |
|---|---|
| Airflow **3.3.0** | `backend/src/airflow/Dockerfile:1` (`FROM apache/airflow:3.3.0`) |
| API là **`/api/v2`**, không phải `/api/v1` | `docker-compose.yaml:143` healthcheck gọi `/api/v2/monitor/health` |
| Auth = `POST /auth/token` lấy JWT, rồi `Authorization: Bearer <token>` | Tài liệu Airflow 3.x; Airflow 2 dùng basic auth — **không áp dụng ở đây** |
| Auth manager = **FabAuthManager** | `docker-compose.yaml:59` |
| api-server ở **`8088:8080`** | `docker-compose.yaml:141` |
| Airflow chạy ở **compose stack riêng** (`backend/src/airflow/docker-compose.yaml`), không cùng network với backend app (`docker-compose.yml` ở gốc) | Hai file compose độc lập |
| **4 DAG nghiệp vụ** thật, không phải 7 | Chỉ 5 file có `with DAG(...)`; `hotel_pipeline.py`/`ota_pipeline.py`/`osm_pipeline.py` là module thư viện |

**Danh sách DAG thật:**

| `dag_id` | Nhãn hiển thị | Lịch | Vai trò |
|---|---|---|---|
| `embed_supabase_tables_pipeline` | Embedding | `@daily` | Dạy bot học lại dữ liệu |
| `google_maps_poc_attractions_pipeline_supabase` | Google Maps | thủ công | Toạ độ, đánh giá, ảnh địa điểm |
| `hotel_nearby_attractions_pipeline_supabase` | Địa điểm lân cận | thủ công | Điểm đáng chú ý quanh khách sạn |
| `tour_pipeline` | Tour | thủ công | Tour và hoạt động |
| ~~`clear_airflow_history`~~ | — | — | **Housekeeping — KHÔNG đưa vào allowlist** |

## Requirements

- Functional
  - Service client gọi Airflow REST `/api/v2` với JWT tự làm mới.
  - **Allowlist `dag_id`** — chỉ 4 DAG trên được trigger.
  - Backend và Airflow nhìn thấy nhau qua mạng.
  - Endpoint `GET /admin/pipelines/health` để UI biết Airflow sống hay chết.
- Non-functional
  - Credential Airflow chỉ nằm ở server, không lộ qua API nào.
  - Airflow chết **không** làm sập route admin nào khác — timeout ngắn, lỗi có kiểu.

## Architecture

### Mạng giữa hai compose stack

Ba lựa chọn, chọn theo môi trường và ghi vào `docs/setup/`:

| Cách | Khi nào | Ghi chú |
|---|---|---|
| (a) `AIRFLOW_API_BASE=http://host.docker.internal:8088` | Dev trên macOS/Windows | Nhanh nhất, không sửa compose |
| (b) External network dùng chung | Staging/prod cùng máy | Thêm `networks: {airflow_net: {external: true}}` vào cả hai compose, backend gọi `http://airflow-apiserver:8080` |
| (c) `AIRFLOW_API_BASE=https://airflow.internal...` | Prod khác máy | Cần TLS + firewall |

**Quyết định mặc định: (a) cho dev, (b) cho staging.** Ghi cả hai vào
`backend/.env.example`.

### Cấu hình mới

```python
# src/config.py
airflow_api_base: str = ""              # rỗng = tắt hẳn nhánh pipeline
airflow_username: str = ""
airflow_password: str = ""
airflow_request_timeout: float = 10.0
```

`airflow_password` **không** được log, không xuất hiện trong `/status`, không trả
trong response nào. Thêm vào `.env.example` với giá trị rỗng.

### Client

`backend/src/services/airflow_client.py`:

```python
ALLOWED_DAG_IDS = {
    "embed_supabase_tables_pipeline",
    "google_maps_poc_attractions_pipeline_supabase",
    "hotel_nearby_attractions_pipeline_supabase",
    "tour_pipeline",
}

class AirflowError(RuntimeError): ...          # lỗi an toàn để trả ra HTTP
class AirflowUnavailable(AirflowError): ...    # không kết nối được → 503

def _token() -> str: ...                       # cache theo TTL, tự làm mới khi 401
def get_dag(dag_id) -> dict
def list_dag_runs(dag_id, limit=10) -> list[dict]
def get_dag_run(dag_id, run_id) -> dict
def trigger_dag_run(dag_id, conf: dict, note: str | None) -> dict
def list_task_instances(dag_id, run_id) -> list[dict]
def get_task_log(dag_id, run_id, task_id, try_number, map_index=None) -> str
def health() -> dict
```

Điểm bắt buộc:

- **Kiểm `dag_id in ALLOWED_DAG_IDS` ở TẦNG CLIENT**, không chỉ ở route. Route có thể
  quên; client là chốt cuối. `dag_id` lạ → `AirflowError("dag_not_allowed")`.
- Token cache trong process kèm TTL; `401` → làm mới **một lần** rồi thử lại, không lặp.
- Timeout `airflow_request_timeout` cho **mọi** lời gọi. Airflow treo không được kéo
  theo worker thread của backend.
- Không bao giờ nhét raw response của Airflow vào `detail` của HTTPException — nó có
  thể chứa đường dẫn nội bộ, tên host, stack trace.
- `airflow_api_base` rỗng → mọi hàm raise `AirflowUnavailable` ngay, không gọi mạng.

### Đường dẫn API (Airflow 3, `/api/v2`)

```
POST /auth/token                                       {"username","password"} → {"access_token"}
GET  /api/v2/monitor/health
GET  /api/v2/dags/{dag_id}
GET  /api/v2/dags/{dag_id}/dagRuns?limit=&order_by=-start_date
POST /api/v2/dags/{dag_id}/dagRuns                     {"logical_date","conf","note"}
GET  /api/v2/dags/{dag_id}/dagRuns/{dag_run_id}
GET  /api/v2/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances
GET  /api/v2/dags/{dag_id}/dagRuns/{dag_run_id}/taskInstances/{task_id}/logs/{try_number}
```

> ⚠️ Đường dẫn và tên trường của Airflow 3 khác Airflow 2 ở vài chỗ nhỏ
> (`execution_date` → `logical_date`, phân trang, hình dạng response log).
> **Bước 1 của Implementation là gọi thật bằng `curl` và ghi lại response thật**,
> không code theo trí nhớ. Task mapped (DAG embedding dùng `expand`) còn thêm
> `map_index` — kiểm bằng lần chạy thật.

### Endpoint

```
GET /api/v1/admin/pipelines/health
→ 200 { "connected": true,  "version": "3.3.0" }
→ 200 { "connected": false, "reason": "airflow_unavailable" }
```

Luôn `200` — đây là câu trả lời về trạng thái, không phải lỗi của request. UI dùng nó
để hiện banner `! Không kết nối được Airflow — pipeline không chạy được lúc này.`
(câu này có sẵn trong bộ Z của thiết kế).

## Related Code Files

- Create: `backend/src/services/airflow_client.py`
- Create: `backend/src/api/admin/pipelines.py` (chỉ `health` ở phase này)
- Create: `backend/tests/test_airflow_client.py`
- Modify: `backend/src/config.py`, `backend/.env.example`
- Modify: `backend/src/api/admin/__init__.py`
- Modify: `docs/setup/` (tài liệu đấu nối, chọn cách (a)/(b)/(c))
- Reference: `backend/src/airflow/docker-compose.yaml`, `backend/src/airflow/Dockerfile`

## Implementation Steps

1. **Dựng Airflow lên và gọi thật bằng `curl`.** Lấy token, gọi `monitor/health`,
   `dags/embed_supabase_tables_pipeline`, `dagRuns`, `taskInstances`, `logs`.
   Lưu response thật vào `plans/reports/` làm căn cứ cho fixture test.
   **Không viết client trước bước này.**
2. Xác nhận `POST /auth/token` hoạt động với FabAuthManager. Nếu không (một số cấu
   hình FAB dùng đường dẫn khác), ghi lại đường dẫn đúng và sửa mục "Đường dẫn API"
   ở trên trước khi đi tiếp.
3. Thêm 4 setting + `.env.example`.
4. Viết client theo response thật, có allowlist + timeout + cache token.
5. Test bằng fixture từ bước 1 (mock HTTP), **không** gọi Airflow thật trong CI.
6. Endpoint `health`.
7. Chọn cách đấu mạng, kiểm từ **trong container backend**:
   `docker compose exec backend curl -s $AIRFLOW_API_BASE/api/v2/monitor/health`
8. Ghi tài liệu đấu nối vào `docs/setup/`.

## Success Criteria

- [ ] Từ **trong container backend**, `GET /admin/pipelines/health` trả `connected:true`
- [ ] `airflow_api_base` rỗng → `connected:false`, không có lời gọi mạng nào, không exception rò ra
- [ ] Airflow tắt → `health` trả `connected:false` trong ≤ timeout, các route admin khác vẫn bình thường
- [ ] Gọi `trigger_dag_run("clear_airflow_history", ...)` → `AirflowError("dag_not_allowed")`, **không** có request nào ra ngoài
- [ ] Token hết hạn giữa chừng → tự làm mới **một lần** và thử lại thành công (test)
- [ ] `grep -ri "airflow_password" backend/src` không cho ra chỗ nào log hay trả về nó
- [ ] Response thật của 6 endpoint Airflow được lưu làm fixture
- [ ] `pytest backend/tests/test_airflow_client.py` xanh, không cần Airflow chạy

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Code theo tài liệu Airflow 2 (basic auth, `/api/v1`, `execution_date`) → sai hoàn toàn | **Cao** | Bước 1 bắt buộc gọi thật trước khi code |
| `POST /auth/token` không tồn tại với FabAuthManager ở cấu hình này | **Cao** | Bước 2 xác nhận riêng; có phương án ghi lại đường dẫn đúng |
| Hai compose stack không thấy nhau → nhánh Pipeline chết từ đầu | **Cao** | Kiểm từ **trong container**, không phải từ máy host |
| DAG lạ bị trigger (tốn tiền API, xoá lịch sử) | **Cao** | Allowlist ở tầng client, không chỉ ở route; test riêng cho `clear_airflow_history` |
| Airflow treo kéo theo worker thread backend | Cao | Timeout mọi lời gọi; handler là `def` chạy trong thread pool nên không chặn event loop |
| Credential Airflow lộ qua response lỗi | Cao | Không nhét raw response vào `detail`; có mục grep |
| Task mapped (`expand`) làm đường dẫn log khác dự đoán | Trung bình | Bước 1 gọi trên một lần chạy embedding thật, có mapped task |
