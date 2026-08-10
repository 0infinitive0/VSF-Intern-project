---
phase: 2
title: "Gỡ Qdrant khỏi codebase"
status: pending
priority: P1
effort: "3-4h"
dependencies: [1]
---

# Phase 2: Gỡ Qdrant khỏi codebase

## Overview

Qdrant đã bị gỡ khỏi `docker-compose.yml` và không nằm trên bất kỳ đường phục vụ
nào, nhưng code, config, dependency và 613 MB dữ liệu vẫn còn. Phase này gỡ hết
trong một commit revert được, và đóng plan benchmark đang treo.

## Requirements

**Functional**
- 0 tham chiếu Qdrant trong code thực thi (comment lịch sử được phép nếu diễn giải lại)
- Test suite vẫn xanh sau khi gỡ
- `python -c "import src.main"` thành công trong venv sạch

**Non-functional**
- Toàn bộ thay đổi nằm trong 1 commit để revert được bằng 1 lệnh
- Không đụng `supabase_search.py` — đường phục vụ hiện tại

## Architecture

### Vì sao gỡ được an toàn

`vector_store.py` **không** được import từ bất kỳ đâu trong `backend/src/` hay
`backend/tests/`:

```bash
$ grep -rn "vector_store" --include='*.py' backend/src backend/tests
backend/src/services/vector_store.py:27:def get_vector_store(...)   ← chỉ định nghĩa
```

Toàn bộ consumer là 3 script legacy. Và **2 trong 3 script đó đã gãy sẵn** vì
import `src.services.qdrant_schema` — module đã bị xoá từ lần migrate trước:

| Script | Trạng thái |
|---|---|
| `scripts/sync_to_qdrant.py` | Gãy — `:11` import `qdrant_schema` |
| `scripts/sync_accommodations_to_qdrant.py` | Gãy — `:12` import `qdrant_schema` |
| `scripts/migrate_vectors_to_supabase.py` | Chạy được, nhưng là công cụ migrate một chiều **đã dùng xong** |

Nghĩa là: đường ghi Qdrant đã chết từ trước phase này. Ta chỉ đang dọn xác.

### Dấu chân đầy đủ

| Loại | Đường dẫn | Xử lý |
|---|---|---|
| Module | `backend/src/services/vector_store.py` | Xoá |
| Script | `backend/scripts/sync_to_qdrant.py` | Xoá (đã gãy) |
| Script | `backend/scripts/sync_accommodations_to_qdrant.py` | Xoá (đã gãy) |
| Script | `backend/scripts/migrate_vectors_to_supabase.py` | Xoá (đã dùng xong) |
| Config | `backend/src/config.py:46-47` — `qdrant_url`, `qdrant_api_key` | Xoá field |
| Dependency | `qdrant-client`, `langchain-qdrant` | Không thêm vào requirements (Phase 4) |
| Dữ liệu | `data/qdrant/` — 595 MB | Xoá (đã gitignore) |
| Dữ liệu | `eval/fixtures/vector_bench/` — 18 MB | Xoá (fixture của benchmark bị huỷ) |
| Env | `.env.example` — biến `QDRANT_*` nếu có | Xoá dòng |
| Plan | `plans/260729-0959-vector-search-supabase-vs-qdrant/` | `status: cancelled` + ghi lý do |

### Trường hợp KHÔNG xoá: comment trong Airflow

`src/airflow/dags/data_pipeline/hotel_pipeline.py` có 5 chỗ nhắc "Qdrant" nhưng
**đều là comment/docstring**, còn code thì vẫn đang chạy và vẫn cần:

```
:396  """Coarse price band for Qdrant filtering. ..."""
:409  """Ascii-folded ... filter tokens for Qdrant ..."""
:486  """Small, stable Qdrant filter payload — ids, destination, star, price ..."""
```

Payload builder ở `:486` vẫn sinh dữ liệu đi vào Supabase. **Chỉ sửa lời văn**
("Qdrant filter payload" → "search filter payload"), giữ nguyên logic. Tương tự
với `hotel_retrieval.py:10` và `src/airflow/tests/test_hotel_retrieval.py:80`.

Đây là chỗ dễ sai nhất của phase: grep ra chữ "qdrant" rồi xoá cả hàm sẽ làm
hỏng pipeline dữ liệu đang chạy.

### Đóng plan benchmark

`260729-0959-vector-search-supabase-vs-qdrant` (P1, `status: pending`) tồn tại để
quyết định giữ Qdrant hay Supabase. Quyết định đã được đưa ra ngoài plan đó, nên
để nó ở `pending` là nói dối trạng thái repo. Chuyển sang `cancelled` kèm một
đoạn ghi rõ: quyết định là gì, ai quyết, ngày nào, và benchmark đã **không** chạy
— để sau này không ai đọc plan rồi tưởng đã có số liệu.

## Related Code Files

- Delete: `backend/src/services/vector_store.py`
- Delete: `backend/scripts/sync_to_qdrant.py`
- Delete: `backend/scripts/sync_accommodations_to_qdrant.py`
- Delete: `backend/scripts/migrate_vectors_to_supabase.py`
- Delete: `data/qdrant/`, `eval/fixtures/vector_bench/`
- Modify: `backend/src/config.py` — bỏ 2 field
- Modify: `.env.example` — bỏ biến `QDRANT_*`
- Modify: `backend/src/airflow/dags/data_pipeline/hotel_pipeline.py` — chỉ comment
- Modify: `backend/src/airflow/dags/data_pipeline/hotel_retrieval.py` — chỉ comment
- Modify: `backend/src/airflow/tests/test_hotel_retrieval.py` — chỉ comment
- Modify: `plans/260729-0959-vector-search-supabase-vs-qdrant/plan.md` — `status: cancelled`
- Modify: `docs/` — bất kỳ trang nào mô tả Qdrant là thành phần đang chạy

## Implementation Steps

1. Chụp dấu chân trước khi sửa, để đối chiếu sau:
   ```bash
   grep -rniI qdrant --include='*.py' --include='*.ts' --include='*.yml' \
     --include='*.md' --include='*.example' backend frontend docs .env.example \
     | grep -v node_modules > /tmp/qdrant-before.txt
   ```
2. Xoá 1 module + 3 script bằng `git rm`.
3. Bỏ `qdrant_url`, `qdrant_api_key` khỏi `backend/src/config.py`. Grep xác nhận
   không còn ai đọc: `grep -rn "qdrant_url\|qdrant_api_key" backend/`.
4. Bỏ biến `QDRANT_*` khỏi `.env.example` nếu có.
5. Sửa **chỉ lời văn** ở 3 file Airflow. Xác minh bằng `git diff --stat` — số
   dòng thay đổi phải nhỏ, và `git diff` không được chứa thay đổi ngoài comment.
6. Chạy `cd backend && python3 -m pytest -q` → phải xanh như sau Phase 1.
7. Xác minh app khởi động được:
   ```bash
   cd backend && python3 -c "import src.main; print('ok')"
   ```
8. Xoá dữ liệu đĩa:
   ```bash
   rm -rf data/qdrant eval/fixtures/vector_bench
   ```
9. Cập nhật plan benchmark sang `cancelled` + ghi lý do và ngày.
10. Rà `docs/` và `ARCHITECTURE.md` cho mô tả Qdrant còn sót; cập nhật theo
    trạng thái thật.
11. Đối chiếu dấu chân cuối với `/tmp/qdrant-before.txt` — mọi dòng còn lại phải
    giải thích được (comment lịch sử đã diễn giải lại, hoặc file trong `plans/`).

## Success Criteria

- [ ] `grep -riI qdrant backend/src backend/scripts backend/tests frontend/src docker-compose*.yml .env.example` → 0 kết quả
- [ ] `cd backend && python3 -m pytest -q` → xanh, số test không giảm ngoài file đã xoá ở Phase 1
- [ ] `cd backend && python3 -c "import src.main"` → thành công
- [ ] `du -sh data/` giảm ≥ 595 MB; `eval/` biến mất
- [ ] `git diff` trên 3 file Airflow chỉ chứa thay đổi comment/docstring
- [ ] `260729-0959-.../plan.md` có `status: cancelled` + đoạn ghi quyết định
- [ ] Toàn bộ nằm trong 1 commit — `git revert <sha>` khôi phục được

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Xoá nhầm logic Airflow vì grep trúng chữ "Qdrant" trong comment | Bước 5 bắt buộc kiểm `git diff` chỉ có comment. Payload builder `hotel_pipeline.py:486` **vẫn cần** cho Supabase |
| Sau này cần lại Qdrant | Toàn bộ trong 1 commit revert được. Dữ liệu tái tạo từ Supabase qua pipeline hiện có |
| `data/qdrant` chứa dữ liệu chưa migrate | `migrate_vectors_to_supabase.py` đã chạy xong (Supabase là nguồn phục vụ hiện tại). Nếu chưa chắc: dump collection ra JSON trước khi `rm -rf` |
| Đóng plan benchmark bị coi là mất thông tin | `cancelled` giữ nguyên file và toàn bộ phân tích; chỉ đổi trạng thái + ghi lý do. Không xoá |
| `.env` thật trên staging còn `QDRANT_*` gây lỗi khởi động | pydantic-settings bỏ qua biến thừa theo mặc định. Xác minh ở bước 7 và trên staging sau deploy |
