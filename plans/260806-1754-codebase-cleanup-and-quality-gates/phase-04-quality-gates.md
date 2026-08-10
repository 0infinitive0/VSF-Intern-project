---
phase: 4
title: "Dựng quality gate trong CI"
status: pending
priority: P1
effort: "4-5h"
dependencies: [1]
---

# Phase 4: Dựng quality gate trong CI

## Overview

CI hiện chỉ deploy, không kiểm tra gì. Đó là nguyên nhân gốc khiến test suite
chết mà không ai biết và 919 lỗi ruff tích tụ được. Phase này dựng hàng rào
trước khi dọn dead code — dọn mà không có hàng rào thì rác sẽ quay lại.

## Requirements

**Functional**
- PR vào `main` chạy: pytest backend, ruff (F-rules), oxlint, tsc, vitest
- Gate đỏ chặn merge
- Cài `backend/requirements.txt` trong venv sạch → `import src.main` thành công

**Non-functional**
- CI chạy < 10 phút
- Gate lint chỉ bật `F` rules ở giai đoạn này (`UP*`/`W*` để cảnh báo, không fail)
- Không đụng workflow deploy đang chạy

## Architecture

### Trạng thái hiện tại

`.github/workflows/deploy.yml` có đúng 2 step: SSH deploy lên EC2, rồi health
check. Không có `pytest`, `ruff`, `oxlint`, `tsc`. Deploy chạy trên push vào
`main` — nghĩa là code chưa từng được kiểm tra tự động lần nào trước khi lên
staging.

Tạo workflow **mới** `.github/workflows/ci.yml` chạy trên `pull_request` +
`push: main`. Không sửa `deploy.yml` — nó đang hoạt động, và trộn hai mối quan
tâm vào một file sẽ khiến lỗi test chặn cả deploy khẩn cấp.

### Vì sao gate lint chỉ bật F-rules

`ruff check src` cho 919 lỗi, phân bố:

| Rule | Số lỗi | Bản chất |
|---|---|---|
| `UP006` | 477 | `Dict` → `dict` (phong cách) |
| `W293` | 198 | Whitespace dòng trống (phong cách) |
| `UP045` | 109 | `Optional[X]` → `X \| None` (phong cách) |
| `UP035` | 41 | Import deprecated (phong cách) |
| `I001` | 38 | Thứ tự import (phong cách) |
| **`F401`/`F841`/`F811`/`F541`** | **24** | **Lỗi thật: import chết, biến chết, định nghĩa đè** |
| `E402`, `E713`, `F-khác` | ~32 | Hỗn hợp |

865 lỗi tự sửa được, nhưng diff chạm gần hết file trong `src/`. Hiện có **2 plan
đang thay đổi `backend/src/api/routes.py`** (`260806-1602-streaming-chat-messages`
phase 1 chưa commit, và `260805-1022-claude-design-ui-integration`). Mass-format
lúc này biến mọi rebase thành conflict thủ công.

Nên: gate `--select F` (fail), phần còn lại chạy `--exit-zero` để hiện số trong
log mà không chặn. Khi streaming plan merge xong, nâng gate lên full rule trong
một commit format-only riêng.

### Dependency thiếu

`backend/requirements.txt` **không khai báo** 5 package đang được import:

| Package | Import ở |
|---|---|
| `langsmith` | `src/` (tracing) |
| `requests` | `src/services/supabase_search.py`, Airflow pipeline |
| `playwright` | Airflow OTA pipeline |
| `qdrant-client` | Chỉ Qdrant → **không thêm** (Phase 2 xoá) |
| `langchain-qdrant` | Chỉ Qdrant → **không thêm** |

Docker image hiện chạy được vì các package này đến gián tiếp qua dependency
khác — một sự may mắn sẽ vỡ ở lần nâng version bất kỳ. CI phải cài từ venv sạch
để bắt được lớp lỗi này.

### Tách dev dependency

`requirements.txt` đang trộn `ruff`, `pytest`, `pytest-asyncio`, `httpx`, `Babel`
vào production. Tách sang `requirements-dev.txt` (kèm `-r requirements.txt`).
Dockerfile production chỉ cài file gốc; CI cài cả hai.

`Babel` thuộc dev: 0 import trong code, chỉ dùng qua CLI `pybabel` để build
catalog gettext.

### Cấu hình pytest

`backend/pytest.ini` được tạo ở Phase 1. Phase này chỉ dùng, không sửa.

## Related Code Files

- Create: `.github/workflows/ci.yml`
- Create: `backend/requirements-dev.txt`
- Modify: `backend/requirements.txt` — thêm `langsmith`, `requests`, `playwright`; bỏ dev tool
- Modify: `backend/Dockerfile` — nếu đang cài dev tool
- Modify: `README.md` — hướng dẫn cài đặt cho 2 file requirements

## Implementation Steps

1. Dựng venv sạch, cài `requirements.txt` hiện tại, chạy `python -c "import src.main"`.
   Ghi lại **chính xác** package nào thiếu — danh sách ở Architecture là từ phân
   tích tĩnh, cần xác nhận bằng thực nghiệm.
2. Cập nhật `backend/requirements.txt`: thêm package thiếu (pin version tương
   thích), bỏ `ruff`/`pytest`/`pytest-asyncio`/`httpx`/`Babel`.
3. Tạo `backend/requirements-dev.txt`:
   ```
   -r requirements.txt
   ruff>=0.8.0
   pytest>=8.0.0
   pytest-asyncio>=0.24.0
   httpx>=0.28.0
   Babel>=2.15.0
   ```
4. Lặp lại bước 1 với requirements mới cho tới khi import sạch.
5. Tạo `.github/workflows/ci.yml` với 2 job song song:

   **`backend`** (ubuntu, python 3.11):
   ```yaml
   - pip install -r backend/requirements-dev.txt
   - cd backend && python -c "import src.main"
   - cd backend && ruff check src --select F        # fail khi đỏ
   - cd backend && ruff check src --exit-zero --statistics   # chỉ báo cáo
   - cd backend && pytest -q
   ```

   **`frontend`** (ubuntu, node 20):
   ```yaml
   - cd frontend && npm ci
   - npm run lint
   - npm run typecheck
   - npm run test
   ```

   Trigger: `pull_request` + `push: [main]`. Không đụng `deploy.yml`.
6. Kiểm tra job frontend chạy được cục bộ trước khi đẩy:
   `cd frontend && npm run lint && npm run typecheck && npm run test`.
   `oxlint` hiện báo 1 cảnh báo ở `stay-date-form.jsx` — file này bị xoá ở
   Phase 6. Nếu Phase 6 chưa xong khi CI bật, hoặc xoá file đó trước, hoặc để
   `lint` ở mức cảnh báo cho tới khi Phase 6 hoàn tất.
7. Mở PR thử để xác nhận gate chạy và chặn được khi cố tình làm đỏ.
8. Bật branch protection cho `main`: yêu cầu 2 job CI xanh mới merge được.
9. Cập nhật `README.md`: `pip install -r backend/requirements-dev.txt` cho dev,
   `requirements.txt` cho production.

## Success Criteria

- [ ] `.github/workflows/ci.yml` chạy trên PR, có 2 job `backend` + `frontend`
- [ ] Venv sạch + `pip install -r backend/requirements.txt` → `import src.main` thành công
- [ ] `ruff check src --select F` là bước fail-được trong CI
- [ ] PR cố tình thêm import chết → CI đỏ
- [ ] PR cố tình làm fail test → CI đỏ
- [ ] `deploy.yml` không bị sửa và vẫn chạy
- [ ] Branch protection yêu cầu 2 job xanh
- [ ] CI hoàn tất < 10 phút

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Gate mới làm đỏ ngay các PR đang mở | Bước 5 chỉ bật `--select F` (24 lỗi, sửa nhanh ở Phase 5). Toàn bộ phong cách để `--exit-zero` |
| Tách requirements làm vỡ Docker build | Bước 4 xác minh venv sạch trước. Kiểm `docker compose build backend` trước khi merge |
| `playwright` cần cài browser binary → CI chậm/vỡ | `playwright` chỉ dùng ở Airflow OTA pipeline, không thuộc đường API. Nếu làm CI chậm, chuyển sang `requirements-airflow.txt` riêng và bỏ khỏi job backend |
| Job frontend đỏ vì cảnh báo oxlint có sẵn | Bước 6 nêu rõ hai lối xử lý. Ưu tiên xoá `stay-date-form.jsx` sớm |
| Branch protection chặn hotfix khẩn cấp | Giữ quyền admin bypass. `deploy.yml` tách riêng nên deploy khẩn cấp không phụ thuộc CI |
| Pin version dependency mới gây xung đột với `langchain` | Bước 1-4 lặp trong venv sạch cho tới khi resolve sạch. Không pin chặt hơn mức cần |
