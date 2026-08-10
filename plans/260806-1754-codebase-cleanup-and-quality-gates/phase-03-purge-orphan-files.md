---
phase: 3
title: "Xoá file mồ côi và rác đĩa"
status: pending
priority: P2
effort: "1-2h"
dependencies: []
---

# Phase 3: Xoá file mồ côi và rác đĩa

## Overview

Thu hồi ~5.7 GB đĩa và xoá các file/thư mục sót lại từ lần chuyển repo vào
`backend/`, gồm 1 file tạm 51 KB đang được git track. Không đụng code thực thi
nên phase này độc lập, làm song song với phase khác được.

## Requirements

**Functional**
- Không còn file mồ côi nào được git track
- Ollama trong Docker vẫn chạy đúng sau khi xoá thư mục model trùng lặp
- `.gitignore` phản ánh đúng thực tế

**Non-functional**
- Mọi thứ xoá phải hoặc tái tạo được, hoặc được xác nhận là rác
- Không xoá gì trong `data/` mà chưa xác minh bằng `docker compose config`

## Architecture

### Rác đĩa

| Đường dẫn | Dung lượng | Vì sao là rác |
|---|---|---|
| `data/ollama/` | 5.7 GB | **Trùng lặp.** `docker-compose.yml:53` chỉ mount `./backend/data/ollama` (1.5 GB). Cái ở root là layout cũ trước khi chuyển vào `backend/` |
| `.claude/worktrees/agent-a01ab8ce13897e166/` | 9.9 MB | Worktree cũ chứa bản sao repo trước khi tái cấu trúc (có `src/`, `requirements.txt` ở root) |
| `poc_trip_planner.log` | 12 KB | Log ở root; đã có trong `.gitignore` nhưng vẫn nằm trên đĩa |
| `__pycache__/` các cấp | vài MB | Gồm `.pyc` của file đã xoá: `test_hotel_search`, `test_qdrant_writer`, `test_planner_tools_hotel_flow` |

`data/qdrant/` (595 MB) và `eval/fixtures/` (18 MB) thuộc Phase 2.

**Bắt buộc xác minh trước khi xoá `data/ollama`:**

```bash
docker compose config | grep -A3 'ollama' | grep -i 'source\|device'
```

Phải thấy đường dẫn trỏ `backend/data/ollama`. Đọc YAML bằng mắt không đủ —
`docker-compose.override.yml` có thể ghi đè. Nếu output cho thấy `data/ollama`
thì đảo ngược: giữ cái root, xoá cái trong `backend/`.

### File mồ côi đang được git track

| Đường dẫn | Kích thước | Vì sao xoá |
|---|---|---|
| `tmp_old_trip_intake.py` | 51 KB | Tên tự khai là file tạm. Logic hiện tại nằm ở `backend/src/services/trip_intake.py`. Lịch sử git giữ nội dung nếu cần tra |
| `tests/` (root) | — | Chỉ còn `__pycache__` sau khi Phase 1 xoá `test_graph.py`; gồm `.pyc` của test đã biến mất từ lâu |
| `scripts/` (root) | — | Chỉ còn `__pycache__` |
| `src/airflow/` (root) | 0 B | Cây thư mục rỗng, sót sau khi move vào `backend/` |

### `.gitignore` nói dối

`.gitignore` liệt kê `CLAUDE.md` và `plans/` nhưng **cả hai đang được track** (đã
thêm vào index trước khi có dòng ignore). Git bỏ qua `.gitignore` với file đã
track, nên hai dòng này không có tác dụng gì ngoài gây hiểu nhầm cho người đọc.

Vì `plans/` là tài sản chung của repo (14 plan, các plan khác phụ thuộc vào nhau
qua `blockedBy`) và `CLAUDE.md` là hướng dẫn dự án đã commit, quyết định đúng là
**bỏ hai dòng khỏi `.gitignore`**, không phải `git rm --cached`.

Bổ sung thêm vào `.gitignore`: `eval/` (thay cho `eval/fixtures/` cụ thể) và
`.claude/worktrees/`.

## Related Code Files

- Delete: `tmp_old_trip_intake.py` (`git rm`)
- Delete: `tests/`, `scripts/`, `src/` ở root repo
- Delete: `data/ollama/` (sau xác minh), `.claude/worktrees/agent-a01ab8ce13897e166/`
- Delete: `poc_trip_planner.log`, toàn bộ `__pycache__/`
- Modify: `.gitignore` — bỏ `CLAUDE.md` + `plans/`; thêm `.claude/worktrees/`, `eval/`
- Modify: `README.md` — nếu cây thư mục mô tả `src/`, `tests/`, `scripts/` ở root

## Implementation Steps

1. Xác minh mount Ollama bằng `docker compose config` (xem Architecture). **Không
   xoá gì trước bước này.**
2. Grep tham chiếu tới `tmp_old_trip_intake` trước khi xoá:
   ```bash
   grep -rn "tmp_old_trip_intake" --include='*.py' --include='*.md' --include='*.yml' . \
     | grep -v node_modules | grep -v plans/
   ```
3. `git rm tmp_old_trip_intake.py`
4. Xoá thư mục mồ côi ở root: `tests/`, `scripts/`, `src/`. Xác nhận không còn
   file được track trước khi `rm -rf`:
   ```bash
   git ls-files tests scripts src
   ```
   Lệnh này phải trả rỗng (sau Phase 1). Nếu không rỗng, dừng và xem xét lại.
5. Xoá `data/ollama/`, `.claude/worktrees/agent-a01ab8ce13897e166/`,
   `poc_trip_planner.log`.
6. Xoá `__pycache__` toàn repo:
   ```bash
   find . -name '__pycache__' -type d -not -path './frontend/node_modules/*' -exec rm -rf {} +
   ```
7. Sửa `.gitignore` theo mục Architecture.
8. Xác minh Ollama vẫn hoạt động sau khi xoá:
   ```bash
   docker compose --profile local-llm up -d ollama
   curl -s localhost:11434/api/tags | head
   ```
   Phải liệt kê `bge-m3`. Nếu rỗng, model đã bị xoá nhầm — kéo lại bằng service
   `ollama-pull`.
9. Cập nhật cây thư mục trong `README.md` nếu có mô tả sai.

## Success Criteria

- [ ] `git ls-files | grep -E 'tmp_old|^tests/|^scripts/|^src/'` → rỗng
- [ ] `du -sh data backend/data` giảm ≥ 5.7 GB so với trước
- [ ] `curl -s localhost:11434/api/tags` liệt kê `bge-m3` sau khi restart Ollama
- [ ] `find . -name '__pycache__' -not -path './frontend/node_modules/*'` → rỗng
- [ ] `.gitignore` không còn `CLAUDE.md` và `plans/`; có `.claude/worktrees/` và `eval/`
- [ ] `git status` sạch sau khi commit — không có file bất ngờ chuyển sang untracked

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Xoá nhầm `data/ollama` đang được mount → mất 5.7 GB model, phải tải lại | Bước 1 bắt buộc `docker compose config`. Bước 8 xác minh sau khi xoá. Model tải lại được qua `ollama-pull` (mất thời gian, không mất dữ liệu) |
| `tmp_old_trip_intake.py` còn chứa logic chưa port sang `trip_intake.py` | Bước 2 grep tham chiếu. Nội dung nằm trong lịch sử git; `git show HEAD:tmp_old_trip_intake.py` lấy lại được bất cứ lúc nào |
| Bỏ `plans/` khỏi `.gitignore` khiến plan riêng tư bị commit nhầm | `plans/` vốn đã được track và đang được chia sẻ. Ai cần plan riêng thì đặt ở global scope (`~/.claude/plans/`) |
| Xoá worktree khi có agent đang chạy trong đó | `git worktree list` kiểm tra trước; `git worktree remove` thay vì `rm -rf` nếu git còn đăng ký |
