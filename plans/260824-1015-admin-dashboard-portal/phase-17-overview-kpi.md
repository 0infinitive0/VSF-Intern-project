---
phase: 17
title: "Tổng quan KPI (A3)"
status: done
priority: P2
effort: "1d"
dependencies: [4, 12, 14]
---

# Phase 17: Tổng quan vận hành — A3

## Overview

Trang gốc `/admin`. Làm **cuối cùng** vì mọi con số trên đây đã có endpoint từ ba
nhánh trước — phase này chỉ ghép lại, không thêm truy vấn mới.

**Thiết kế bám theo:** artboard `A2 · KHUNG LAYOUT + TRANG MẪU (TỔNG QUAN)` —
trang mẫu trong artboard đó **chính là** màn A3.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb `Quản trị · Tổng quan` · tiêu đề `Tổng quan vận hành` ·
dòng phụ `Hôm nay · 24/08/2026` · nút chính `Chạy pipeline`.

**4 ô số liệu** (`overviewStats`):

| Nhãn | Giá trị | Dòng phụ | Màu số |
|---|---|---|---|
| Đơn hôm nay | 18 | 12 đã xác nhận · 6 chờ | mặc định |
| Doanh thu hôm nay | 62.400.000 ₫ | Đã về tài khoản VNPay | mặc định |
| Chờ xử lý | 7 | Cần xác nhận trong hôm nay | `--warn-ink` |
| Giữ chỗ sắp hết hạn | 3 | Hết hạn trong 30 phút tới | `--err` |

Số lớn: `font-size:26px; font-weight:700; letter-spacing:-.02em; tabular-nums`.

**Khối `Đơn cần xử lý ngay`** + link `Xem tất cả đơn`:
- Cột: `MÃ ĐƠN` · `KHÁCH` (tên + email) · `TỔNG TIỀN` · `VẤN ĐỀ`
- Chip `VẤN ĐỀ` (`font-size:11.5px`), 3 mức màu:

| Chip | Màu |
|---|---|
| `Hết hạn giữ sau 4 phút` | `--err-soft` / `--err` |
| `Trả tiền, chưa xác nhận` | `--warn-soft` / `--warn-ink` |
| `Chờ xác nhận 2 giờ` | `--warn-soft` / `--warn-ink` |
| `Thanh toán thất bại` | `--fill` / `--t3` |

- Dòng có dải màu trái như D1 (`attention` cam / `expiring` đỏ).
- Tối đa 5 dòng, sắp xếp: sắp hết hạn trước, rồi đã trả tiền chưa xác nhận, rồi
  chờ lâu nhất.

**Khối `Pipeline embedding`** + chip `✓ Thành công`:
- `Lần chạy gần nhất — 24/08/2026 06:00`
- `Thời gian chạy — 4 phút 12 giây`
- `Bản ghi đã nhúng — 1.284 / 1.310`
- Banner: `26 phòng chưa có embedding — bot sẽ không gợi ý được các phòng này.`

**Khối `Giữ chỗ sắp hết hạn`** + số đếm `3`:
- Mỗi dòng: `{mã} · {khách}` / `{khách sạn}` / chip đếm ngược `⏱ 4 phút`
- Chip: `--err-soft`/`--err` khi khẩn (≤ 30 phút), `--warn-soft`/`--warn-ink` khi
  còn xa, `--fill`/`--t3` khi `⏱ Đã hết hạn`

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L74 | Khối `miniLog` (nhật ký thao tác rút gọn) có trong dữ liệu thiết kế | Màn E1 đã bị bỏ (quyết định #10) | **Không render.** Dữ liệu `miniLog` trong file thiết kế thuộc về E1, bỏ luôn |
| L75 | `Đã về tài khoản VNPay` | Đúng nếu chỉ đếm `payments.status='PAID'` | Giữ. Doanh thu = `sum(amount)` của payment `PAID` có `paid_at` hôm nay — **`paid_at`, không phải `created_at`** |
| L76 | `Cần xác nhận trong hôm nay` | Không có SLA (như L13) | Đổi thành `Đang chờ admin xác nhận` |
| L77 | `Bản ghi đã nhúng 1.284 / 1.310` | Có từ `GET /admin/embedding/summary` (Phase 12) | Giữ, tổng 3 bảng |
| L78 | Chip trạng thái pipeline embedding | Có từ `GET /admin/pipelines` (Phase 14) | Giữ. Airflow tắt → khối hiện `Không kết nối được Airflow`, **các khối khác vẫn chạy** |

## Backend — hợp đồng API

```
GET /api/v1/admin/overview
→ 200 {
    "date": "2026-08-24",
    "orders": {                        // = GET /admin/orders/stats  (Phase 4)
      "today": 18, "confirmed_today": 12, "pending_today": 6,
      "revenue_today": "62400000.00", "currency": "VND",
      "pending_count": 7,
      "expiring_holds_30m": 3
    },
    "attention_orders": [{             // ≤ 5, cùng hình dạng dòng của D1
      "payment_id": "uuid", "order_code": "DH-24080",
      "guest_name": "...", "guest_email": "...",
      "amount": "1850000.00",
      "issue": "paid_not_confirmed",   // expiring_hold | paid_not_confirmed
                                       // | awaiting_long | payment_failed
      "issue_label": "Trả tiền, chưa xác nhận",
      "severity": "warn"               // err | warn | mute
    }],
    "expiring_holds": [{               // ≤ 5
      "booking_id": "uuid", "hold_code": "GC-9182",
      "guest_label": "Khách ẩn danh · a1b2c3d4",
      "hotel_name": "...", "room_name": "...",
      "expires_at": "2026-08-24T10:46:00Z"
    }],
    "embedding": {                     // = GET /admin/embedding/summary (Phase 12)
      "embedded": 1284, "total": 1310, "missing": 26,
      "missing_label": "26 phòng chưa có embedding"
    },
    "pipeline": {                      // từ GET /admin/pipelines (Phase 14)
      "connected": true,
      "state": "success",
      "last_run_at": "2026-08-24T06:00:00Z",
      "duration_seconds": 252,
      "run_id": "scheduled__..."
    }
  }
```

**Endpoint này gọi lại các hàm service đã có của Phase 4, 12, 14 — không viết truy vấn
mới.** Nếu phải viết truy vấn mới thì có nghĩa phase trước thiếu, sửa ở đó.

`pipeline.connected = false` → phần còn lại của response vẫn đầy đủ. Một khối hỏng
không được kéo sập cả trang.

`missing_label` do backend sinh (`"26 phòng"` / `"3 khách sạn và 26 phòng"`) để câu
tiếng Việt luôn đúng số nhiều/loại — frontend chỉ nội suy vào câu mẫu.

## Frontend — màn hình A3

```
src/admin/pages/overview/
  overview-page.tsx
  overview-stat-cards.tsx        4 ô
  attention-orders-card.tsx
  embedding-status-card.tsx
  expiring-holds-card.tsx
```

- Tái dùng `order-status-chip.tsx` (Phase 4) và `EmptyState` (Phase 3).
- Poll toàn trang mỗi 60 giây. Đếm ngược giữ chỗ chạy client-side mỗi 30 giây.
- Mỗi khối tự xử lý trạng thái tải/rỗng/lỗi **riêng** — Airflow chết không được làm
  trắng cả trang.
- Trạng thái rỗng tích cực: `✓ Không có đơn nào cần xử lý ngay.` — không dùng khung
  `Chưa có dữ liệu` mặc định.
- Nút `Chạy pipeline` → hộp thoại C2 (Phase 15).
- `Xem tất cả đơn` → `/admin/orders`; click dòng → `/admin/orders/:id`.

## Related Code Files

- Create: `backend/src/api/admin/overview.py`
- Create: `backend/tests/test_api/test_admin_overview.py`
- Create: `frontend/src/admin/pages/overview/**`
- Modify: `backend/src/api/admin/__init__.py`, `frontend/src/admin/router.tsx`
- Reference: `backend/src/api/admin/orders.py`, `embedding.py`, `pipelines.py`

## Implementation Steps

1. Rà ba module Phase 4/12/14, tách hàm service tái dùng được (nếu logic đang nằm
   thẳng trong handler thì tách ra trước).
2. `overview.py` gọi ba hàm đó, gói mỗi cái trong try/except riêng.
3. Xếp hạng `attention_orders` theo mức độ khẩn.
4. Test, đặc biệt trường hợp Airflow tắt.
5. Dựng màn theo checklist, bỏ L74.

## Success Criteria

- [x] 4 ô số liệu khớp `GET /admin/orders/stats`
- [x] `revenue_today` tính theo `paid_at`, không phải `created_at` (L75)
- [x] Airflow tắt → khối pipeline hiện `Không kết nối được Airflow`, ba khối kia vẫn đúng
- [x] `attention_orders` sắp xếp: sắp hết hạn → đã trả tiền chưa xác nhận → chờ lâu nhất
- [x] Không có đơn cần xử lý → trạng thái rỗng tích cực, không phải `Chưa có dữ liệu`
- [x] Đếm ngược giữ chỗ chạy đúng và đổi màu khi ≤ 30 phút
- [x] **Không** có khối nhật ký thao tác (L74)
- [x] `overview.py` **không** chứa truy vấn SQL/PostgREST nào của riêng nó (code review xác nhận)
- [x] Trang tải xong dưới 2 giây với dữ liệu thật

## Code review fixes (round 1)

Findings from the mandatory `code-reviewer` pass, all fixed and verified via
unit tests + live checks against the real Docker backend/Supabase/Airflow
stack before this phase was marked done:

- **C1 (blocking):** `revenue_today` was filtering `payments.created_at`
  instead of `paid_at`, contradicting this file's own success criterion.
  Fixed in `orders.py`'s `get_order_stats()`.
- **H1 (blocking):** `_fetch_expiring_holds()` had no lower bound on
  `expires_at`, so it showed the *most already-expired* holds instead of
  soon-to-expire ones. Confirmed live against real data: all 31 RESERVED
  holds in the dev DB are stale (never auto-released, oldest from
  2026-08-18) — the card was silently showing 5 of those as "expiring."
  Fixed by adding `expires_after`/`expires_before` window params to
  `_apply_unpaid_filters` and passing `expires_after=now()`.
- **H2 (blocking):** `_classify_attention`'s `expiring_hold` branch had no
  lower bound on `minutes_left`, so the same stale holds permanently
  occupied rank-0 in `attention_orders`, shadowing real
  `paid_not_confirmed` issues. Fixed with `0 < minutes_left <= threshold`.
- **M1:** within-bucket sort had no secondary key, so ties fell back to
  `created_at DESC` (newest-first) — the opposite of the intended "chờ lâu
  nhất." Added ascending `created_at` as the tiebreak.
- **M2/M3:** `embedding-status-card.tsx` conflated "still loading" with
  "Airflow confirmed down" (`pipeline === null` vs `.connected === false`),
  and nested the independently-healthy embedding count inside the
  Airflow-connected conditional. Split the two states; embedding count now
  renders whenever embedding data exists, regardless of Airflow status.
- **M4:** unused `date` field now rendered as a header subline (added an
  optional `subtitle` slot to the shared `PageHeader`).
- **M5:** `fetch_orders`/`fetch_unpaid_bookings` gained a `with_count`
  param so overview.py's 60s poll skips the unused `count="exact"`.
- **M6:** `_fetch_attention_orders`' lookback window now uses the existing
  server-side `from_` filter instead of an unbounded fetch + client-side
  string comparison on `created_at`.
- **L1:** promoted `_short_code`, `_money_str`, `_fetch_orders`,
  `_fetch_unpaid_bookings` in `orders.py` to public names (`short_code`,
  `money_str`, `fetch_orders`, `fetch_unpaid_bookings`) since `overview.py`
  is now a legitimate cross-module caller.

M7 (no timeout on the `ThreadPoolExecutor` futures / Supabase client) was
noted by the reviewer as pre-existing and out of scope for this phase.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Viết lại truy vấn thay vì tái dùng → hai nguồn số liệu lệch nhau | Cao | Có mục code review trong Success Criteria; bước 1 tách hàm service trước |
| Một khối lỗi làm trắng cả trang | Cao | try/except riêng mỗi khối ở backend, error boundary riêng mỗi khối ở frontend |
| `revenue_today` tính theo `created_at` → sai khi khách trả tiền qua ngày | Trung bình | Dùng `paid_at`; có mục kiểm |
| Poll 60s × nhiều tab đấm vào Airflow | Trung bình | `GET /admin/pipelines` đã cache 10s ở Phase 14 |
