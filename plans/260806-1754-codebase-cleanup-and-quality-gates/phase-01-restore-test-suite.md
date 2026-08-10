---
phase: 1
title: "Khôi phục test suite backend"
status: pending
priority: P1
effort: "2-3h"
dependencies: []
---

# Phase 1: Khôi phục test suite backend

## Overview

`pytest` từ `backend/` đang dừng ở collection với 2 lỗi, chặn cả 495 test. Phase
này gỡ đúng 2 chốt chặn đó và pin lại bằng cấu hình để không tái phát. Không sửa
logic, không sửa test đang pass.

## Requirements

**Functional**
- `cd backend && python3 -m pytest --collect-only -q` → 0 lỗi
- `cd backend && python3 -m pytest -q` → toàn bộ test pass
- Chạy `pytest` từ **repo root** cũng không collect nhầm file ngoài `backend/`

**Non-functional**
- Không thay đổi hành vi runtime của bất kỳ module `src/` nào
- Không sửa nội dung test đang pass

## Architecture

Ba nguyên nhân độc lập, ba cách xử lý khác nhau:

### 1. `tests/test_qdrant_schema.py` — module đích không tồn tại

```
backend/tests/test_qdrant_schema.py:4
  from src.services.qdrant_schema import ATTRACTIONS_VECTOR, CollectionSpec, ensure_collection, point_id
→ ModuleNotFoundError: No module named 'src.services.qdrant_schema'
```

`src/services/qdrant_schema.py` đã bị xoá trong lần migrate sang Supabase nhưng
test ở lại. Vì Qdrant bị gỡ hẳn (Phase 2), test này không có gì để khôi phục —
**xoá**, không phải sửa.

Một test trong đó pin namespace UUID (`test_point_id_pinned_literal`). Namespace
này chỉ có ý nghĩa với Qdrant point id; không còn Qdrant thì không còn bất biến
nào để bảo vệ.

### 2. Trùng basename chặn collection

```
backend/scripts/test_hotel_pipeline.py            ← script chạy tay
backend/src/airflow/tests/test_hotel_pipeline.py  ← test thật
```

`src/airflow/tests/` không có `__init__.py`, nên pytest dựng module name từ
basename → hai file tranh nhau tên `test_hotel_pipeline`. pytest báo thẳng:

```
HINT: remove __pycache__ / .pyc files and/or use a unique basename
```

`backend/scripts/` có **5** file mang tiền tố `test_` nhưng đều là script chạy
tay gọi API/DB thật, không phải pytest. Chúng bị collect là tai nạn — nếu ai đó
chạy `pytest` ở root, chúng sẽ gọi service thật. Đổi tiền tố `test_` → `check_`
cho cả 5, vừa hết va chạm vừa hết nguy cơ.

Chọn đổi tên script thay vì thêm `__init__.py` vào `src/airflow/tests/`: script
mới là thứ đặt sai tên, còn thư mục test thì đúng chỗ. Sửa đúng nguyên nhân.

### 3. `tests/test_agents/test_graph.py` (root) — orphan gãy

File ở **root repo**, không phải `backend/`, sót lại từ lần chuyển repo vào
`backend/`. Nó import symbol đã không còn tồn tại:

```
tests/test_agents/test_graph.py:15
  from src.agents.graph import _CHAT_TURN_RECURSION_LIMIT, build_chat_turn_graph
→ ImportError: cannot import name '_CHAT_TURN_RECURSION_LIMIT'
```

`backend/src/agents/graph.py` giờ chỉ export `build_trip_agent` (:78). Graph
chat-turn đã được thay bằng đường khác. File đang được **git track** — xoá qua
`git rm`, không phải xoá tay.

### Pin bằng cấu hình

Thêm `backend/pytest.ini` để cố định rootdir và testpaths. Không có nó, kết quả
`pytest` phụ thuộc vào thư mục đang đứng — chính là cách 3 lỗi trên sống sót lâu
đến vậy.

```ini
[pytest]
testpaths = tests src/airflow/tests
norecursedirs = scripts data logs locales .venv __pycache__
asyncio_mode = auto
```

`testpaths` khai báo tường minh nên `scripts/` không bao giờ bị quét, kể cả sau
này ai đó lại đặt tên `test_*`.

## Related Code Files

- Delete: `backend/tests/test_qdrant_schema.py`
- Delete: `tests/test_agents/test_graph.py` (root, đang được track → `git rm`)
- Rename: `backend/scripts/test_hotel_pipeline.py` → `check_hotel_pipeline.py`
- Rename: `backend/scripts/test_batch_routing.py` → `check_batch_routing.py`
- Rename: `backend/scripts/test_user_flow_extended.py` → `check_user_flow_extended.py`
- Rename: `backend/scripts/test_trip_cloning_and_recommendations.py` → `check_trip_cloning_and_recommendations.py`
- Create: `backend/pytest.ini`

Lưu ý: `backend/tests/test_trip_cloning_and_recommendations.py` (test thật) và
`backend/scripts/test_trip_cloning_and_recommendations.py` (script) cũng trùng
basename — cùng một lớp lỗi, đổi tên script sẽ gỡ luôn.

## Implementation Steps

1. Ghi lại baseline để so sánh về sau:
   ```bash
   cd backend && python3 -m pytest --collect-only -q 2>&1 | tail -5
   ```
2. `git rm backend/tests/test_qdrant_schema.py`
3. `git rm tests/test_agents/test_graph.py` — sau đó xoá thư mục rỗng còn lại
   (`tests/test_agents/`, `tests/`) nếu chỉ còn `__pycache__`
4. `git mv` 4 script `test_*.py` sang tiền tố `check_`. Grep tham chiếu tên cũ
   trước khi đổi:
   ```bash
   grep -rn "test_hotel_pipeline\|test_batch_routing\|test_user_flow_extended\|test_trip_cloning" \
     --include='*.md' --include='*.yml' --include='*.sh' . | grep -v node_modules | grep -v plans/
   ```
   Cập nhật `README.md` / docs nếu có nhắc tên cũ.
5. Tạo `backend/pytest.ini` theo nội dung ở mục Architecture. Xác nhận
   `asyncio_mode = auto` khớp cách `pytest-asyncio` đang được dùng — kiểm bằng
   `grep -rn "asyncio" backend/tests/conftest.py`; nếu test đang dùng decorator
   tường minh thì bỏ dòng đó đi.
6. Xoá `__pycache__` cũ để không bị pyc mồ côi đánh lừa:
   ```bash
   find . -name '__pycache__' -type d -not -path './frontend/node_modules/*' -exec rm -rf {} +
   ```
7. Chạy lại toàn bộ suite, ghi số test và thời gian vào PR description.

## Success Criteria

- [ ] `cd backend && python3 -m pytest --collect-only -q` → 0 error
- [ ] `cd backend && python3 -m pytest -q` → toàn bộ pass, số test ≥ 495
- [ ] `python3 -m pytest -q` từ repo root → không collect file nào ngoài `backend/`
- [ ] `git ls-files tests/` → rỗng
- [ ] `ls backend/scripts/test_*.py` → không có kết quả
- [ ] `backend/pytest.ini` tồn tại và được commit

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Sau khi gỡ 2 lỗi collection, lộ ra test đang fail sẵn mà lâu nay bị che | Đây là kết quả mong muốn, không phải hồi quy. Nếu có, ghi rõ trong PR và xử lý ở phase riêng — **không** sửa test cho pass |
| `asyncio_mode = auto` đổi hành vi của test async đang chạy đúng | Bước 5 kiểm `conftest.py` trước. Nếu không chắc thì bỏ dòng đó — nó không cần cho mục tiêu phase này |
| Script đổi tên bị gọi từ cron/docs/CI | Bước 4 grep trước khi đổi. `git mv` giữ lịch sử nên `git log --follow` vẫn truy được |
| Xoá `test_qdrant_schema.py` mất bất biến namespace UUID | Chỉ có ý nghĩa với Qdrant point id. Phase 2 gỡ Qdrant hẳn nên không còn gì để bảo vệ |
