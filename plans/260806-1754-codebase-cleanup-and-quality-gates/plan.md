---
title: "Dọn dẹp codebase và dựng quality gate"
description: "Khôi phục test suite backend đang chết hoàn toàn, gỡ Qdrant khỏi codebase, xoá ~6.3 GB rác đĩa và file mồ côi, dựng CI gate để chặn tái phát, rồi mới dọn dead code."
status: pending
priority: P1
effort: "3-4 ngày (1 dev)"
tags: [cleanup, tech-debt, ci, testing, qdrant-removal, dead-code]
blockedBy: []
blocks: [260729-0959-vector-search-supabase-vs-qdrant]
created: 2026-08-06
updated: 2026-08-06
---

# Dọn dẹp codebase và dựng quality gate

## Tổng quan

Repo đã qua hai lần tái cấu trúc mà chưa lần nào dọn sạch: (1) chuyển toàn bộ mã
nguồn vào `backend/`, (2) migrate vector search từ Qdrant sang Supabase pgvector.
Cả hai để lại file mồ côi, import gãy, và ~6.3 GB dữ liệu chết trên đĩa.

Hậu quả đã vượt khỏi phạm vi "khó chịu về thẩm mỹ":

**Test suite backend hiện không chạy được.** `pytest` từ `backend/` dừng ở
collection với 2 lỗi, chặn cả 495 test đã collect thành công.

```
$ cd backend && python3 -m pytest --collect-only -q
E   ModuleNotFoundError: No module named 'src.services.qdrant_schema'
ERROR src/airflow/tests/test_hotel_pipeline.py
ERROR tests/test_qdrant_schema.py
495 tests collected, 2 errors
```

Vì `.github/workflows/deploy.yml` **không chạy test** (chỉ deploy + health check),
không ai phát hiện. Đó cũng là lý do 919 lỗi ruff tích tụ được trong `backend/src`.

Plan này ưu tiên theo rủi ro, không theo mức độ khó chịu: khôi phục khả năng
kiểm chứng trước, dựng hàng rào, rồi mới dọn.

### Bằng chứng đã xác minh

| Sự kiện | Nguồn |
|---|---|
| `tests/test_qdrant_schema.py` import module **không tồn tại** | `backend/tests/test_qdrant_schema.py:4` → `src.services.qdrant_schema`; `ls` xác nhận không có file |
| Trùng basename chặn collection | `backend/scripts/test_hotel_pipeline.py` vs `backend/src/airflow/tests/test_hotel_pipeline.py`; `src/airflow/tests/` không có `__init__.py` |
| `tests/test_agents/test_graph.py` (root) import symbol đã bị xoá | Import `build_chat_turn_graph`, `_CHAT_TURN_RECURSION_LIMIT`; `backend/src/agents/graph.py` chỉ còn `build_trip_agent` (:78) |
| CI không có gate chất lượng nào | `.github/workflows/deploy.yml` — chỉ 2 step: deploy EC2 + health check |
| Không có `pytest.ini` / `pyproject.toml` cho backend | `find` toàn repo: chỉ có `backend/ruff.toml` |
| Qdrant đã bị gỡ khỏi compose | `docker-compose.yml` chỉ còn 4 service: backend, frontend, ollama, ollama-pull |
| 3 script sync Qdrant **đã gãy sẵn** | `sync_to_qdrant.py:11`, `sync_accommodations_to_qdrant.py:12` import `qdrant_schema` không tồn tại |
| `vector_store.py` không nằm trên đường phục vụ | 0 import từ `backend/src/` hoặc `backend/tests/`; chỉ 3 script legacy dùng |
| `qdrant-client`, `langchain-qdrant`, `langsmith`, `requests`, `playwright` **thiếu** trong requirements | Import trong `src/` nhưng không khai báo ở `backend/requirements.txt` |
| `data/ollama` (5.7 GB) mồ côi | `docker-compose.yml:53` chỉ mount `./backend/data/ollama` (1.5 GB) |
| `to_hotel_options_payload` định nghĩa **2 lần** | `schemas.py:372` và `trip_formatter.py:359`; `routes.py` import cả hai (:39, :293) |
| `select_hotel.py` import đè lên chính nó | `:43-44` redefine `InjectedToolCallId`, `InjectedState` từ `:23-24` (ruff F811) |
| 919 lỗi ruff trong `backend/src` | `ruff check src --statistics` |
| 35/195 key i18n không được dùng | Quét `frontend/src/i18n/locales/en.json` đối chiếu toàn bộ `.ts`/`.tsx` |
| Lệch plural form giữa 2 ngôn ngữ | `en.json` có `generatingElapsed_one`/`_other`; `vi.json` chỉ có `generatingElapsed` |

### Những gì plan này KHÔNG làm

Ba thứ trông giống "lỗi" nhưng thuộc sở hữu của plan khác — đụng vào là làm hỏng
việc đang chạy:

| Không đụng | Vì sao | Chủ sở hữu |
|---|---|---|
| 4 endpoint frontend gọi mà backend chưa có (`GET /chat/sessions`, `/chat/{id}/restore`, `/hotels/{id}`, `/attractions/{id}`) | **Không phải drift.** Frontend cố ý dựng trước trên mock; backend là phase chưa làm | `260805-1022-claude-design-ui-integration` phase-03 (`status: pending`), phase-04 (`status: pending`) |
| Alias route trùng (`/chat` ≡ `/planner_chat`, `/hotels/select` ≡ `/chat/select_hotel`) | Là lớp tương thích cố ý trong hợp đồng API | `docs/chat_api_contract.md` |
| Mass-format `ruff --fix` (865 lỗi UP*/W*) | Diff chạm gần hết file, sẽ gây rebase đau cho 2 plan đang làm dở trên `routes.py` | Hoãn — xem "Quyết định đã chốt" |
| 4 symbol "0 usage" nhưng là đồ dựng sẵn: `RouteInfoPayload`, `get_route_to_next`, `TurnPhase`, `getAttractionDetail` | **"Chưa ai gọi" ≠ "chết"** khi plan treo mô tả đúng chỗ dùng | `260805-1022-...` phase-09 + phase-12; `260806-1602-...` phase-05 |

Hai plan đang có thay đổi chưa commit trên `backend/src/api/routes.py`:
`260806-1602-streaming-chat-messages` (phase 1) và `260805-1022-claude-design-ui-integration`.
Mọi phase ở đây phải coi `routes.py` là file nóng.

## Quyết định đã chốt

| Quyết định | Lựa chọn | Hệ quả |
|---|---|---|
| Qdrant | **Gỡ hẳn** | Xoá `vector_store.py`, 3 script sync, 2 config field, `data/qdrant/` (595 MB), `eval/fixtures/` (18 MB). `qdrant-client` + `langchain-qdrant` vốn chưa từng có trong requirements → không bổ sung ở Phase 4. Đánh dấu `260729-0959-vector-search-supabase-vs-qdrant` là `cancelled` |
| Phạm vi | **Đầy đủ, chia phase theo rủi ro** | 6 phase độc lập, mỗi phase revert được riêng |
| `ruff --fix` | **Chỉ F-rules** | Sửa 24 lỗi F401/F841/F811/F541 (diff nhỏ). Hoãn 865 lỗi UP*/W* tới sau khi streaming plan merge. CI chỉ fail trên `F` ở giai đoạn này |
| LLM provider | **Giữ cả 4** | Không đụng `llm.py`. Chỉ bổ sung dependency thiếu vào requirements |

## Mục tiêu

| # | Mục tiêu | Ưu tiên |
|---|---|---|
| 1 | `cd backend && pytest` chạy hết 495+ test, 0 lỗi collection | P1 |
| 2 | CI chặn được mọi hồi quy tương lai (test + lint + typecheck) | P1 |
| 3 | Qdrant biến mất hoàn toàn khỏi code, config, dependency, đĩa | P1 |
| 4 | `requirements.txt` khai báo đủ mọi dependency đang import | P1 |
| 5 | Thu hồi ~6.3 GB đĩa, xoá file mồ côi đang được git track | P2 |
| 6 | Dead code backend/frontend biến mất, không còn định nghĩa trùng | P2 |
| 7 | i18n hai ngôn ngữ khớp key, không còn key chết | P3 |

## Phases

| # | Phase | Ưu tiên | Phụ thuộc | Trạng thái |
|---|---|---|---|---|
| 1 | [Khôi phục test suite](phase-01-restore-test-suite.md) | P1 | — | pending |
| 2 | [Gỡ Qdrant](phase-02-remove-qdrant.md) | P1 | 1 | pending |
| 3 | [Xoá file mồ côi và rác đĩa](phase-03-purge-orphan-files.md) | P2 | — | pending |
| 4 | [Dựng quality gate](phase-04-quality-gates.md) | P1 | 1 | pending |
| 5 | [Dead code backend](phase-05-backend-dead-code.md) | P2 | 1, 4 | pending |
| 6 | [Dead code frontend + i18n](phase-06-frontend-dead-code-and-i18n.md) | P3 | — | pending |

Phase 1 là điều kiện tiên quyết thật: không có test chạy được thì mọi phase sau
đều là thay đổi mù. Phase 3 và 6 không phụ thuộc gì, làm song song được.

## Rủi ro tổng thể

| Rủi ro | Xác suất | Giảm thiểu |
|---|---|---|
| Xoá nhầm code còn dùng qua đường động (getattr, entrypoint chuỗi, Airflow DAG discovery) | Trung bình | Mỗi lần xoá symbol phải kèm grep toàn repo cho cả tên dạng chuỗi, không chỉ tên định danh. Phase 5 liệt kê rõ lệnh grep |
| Conflict với 2 plan đang làm dở trên `routes.py` | Cao | Hoãn mass-format. Thay đổi ở `routes.py` chỉ giới hạn trong 4 dòng import/biến thừa, làm ở phase 5 (cuối) |
| Xoá `data/ollama` 5.7 GB nhầm cái đang dùng | Thấp | Xác minh bằng `docker compose config` trước khi xoá, không tin vào đọc file YAML bằng mắt |
| CI gate mới làm đỏ toàn bộ PR đang mở | Trung bình | Gate lint chỉ bật `F` rules ở phase 4; `UP*`/`W*` để chế độ cảnh báo |
| Gỡ Qdrant rồi sau này cần lại | Thấp | Toàn bộ nằm trong 1 commit revert được. Dữ liệu Qdrant tái tạo được từ Supabase qua pipeline hiện có |

## Tiêu chí nghiệm thu

- [ ] `cd backend && python3 -m pytest -q` → 0 lỗi collection, toàn bộ test pass
- [ ] `cd backend && python3 -m ruff check src --select F` → 0 lỗi
- [ ] `cd frontend && npm run lint && npm run typecheck && npm run test` → pass
- [ ] `grep -riI qdrant backend/ frontend/ docker-compose*.yml .env.example` → 0 kết quả code (comment lịch sử được phép nếu diễn giải lại)
- [ ] `pip install -r backend/requirements.txt` trong venv sạch → `python -c "import src.main"` thành công
- [ ] CI chạy test + lint + typecheck trên PR và chặn merge khi đỏ
- [ ] `du -sh data backend/data` giảm ~6.3 GB
- [ ] `git ls-files | grep -E 'tmp_old|^tests/'` → rỗng
- [ ] `en.json` và `vi.json` cùng tập key
- [ ] `260729-0959-vector-search-supabase-vs-qdrant/plan.md` có `status: cancelled` kèm lý do

## Câu hỏi chưa có lời giải

- `backend/scripts/` chứa 23 script, nhiều cái có vẻ dùng một lần (`revert_hotels.py`,
  `inject_cache.py`, `fix_pipeline.py`, `rewrite_index.py`, `generate_sql.py`).
  Plan này chỉ đổi tên 5 file `test_*.py` để hết va chạm pytest, không đánh giá
  script nào còn cần. Cần chủ sở hữu pipeline xác nhận trước khi dọn tiếp.
- `docs/archive/sprint1_weekly_plan.md` là tài liệu archive duy nhất — giữ hay xoá?
- `data/design/` (536 KB, export từ Stitch) còn cần cho `260803-1200-stitch-ui-redesign-frontend`
  (`status: completed`) không?
