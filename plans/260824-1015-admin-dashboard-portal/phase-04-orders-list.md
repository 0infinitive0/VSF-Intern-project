---
phase: 4
title: "Danh sách đơn hàng (D1)"
status: done
priority: P1
effort: "2d"
dependencies: [3]
---

# Phase 4: Danh sách đơn hàng — D1

## Overview

Màn có giá trị vận hành cao nhất và rủi ro thấp nhất: chỉ đọc. Đơn vị "đơn hàng" là
**một lần thanh toán** (`payments`), `bookings` là dòng chi tiết (quyết định #2).

**Thiết kế bám theo:** artboard `D1 · DANH SÁCH ĐƠN HÀNG` trong
`plans/reports/VSF Trip Planner Admin Dashboard/VSF Admin Portal.dc.html`,
gồm 3 biến thể: mặc định, `Tab 2 · Đặt phòng chưa thanh toán`,
`D1 · trạng thái rỗng (bộ lọc không khớp)`.

## Bám sát thiết kế — checklist đối chiếu 1:1

Lấy từ artboard D1 và khối `renderVals()` cuối file thiết kế.

**Header:** breadcrumb `Quản trị · Đơn hàng` · tiêu đề `Danh sách đơn` ·
nút phụ `↓ Xuất CSV` · nút chính `Tạo đơn thủ công`.

**4 ô số liệu** (`orderStats`, nền `--g3`, viền `--stroke`, bo 16px, số
`font-size:26px; font-weight:700; tabular-nums`):

| Nhãn | Giá trị mẫu | Dòng phụ | Màu số | Dải trái |
|---|---|---|---|---|
| Đơn hôm nay | 18 | +4 so với hôm qua | mặc định | — |
| Doanh thu hôm nay | 62.400.000 ₫ | Trung bình 3.466.667 ₫/đơn | mặc định | — |
| Chờ xử lý | 7 | 2 quá 2 giờ | `--warn-ink` | `inset 3px 0 0 var(--warn)` |
| Giữ chỗ sắp hết hạn | 3 | Hết hạn trong 30 phút tới | `--err` | `inset 3px 0 0 var(--err)` |

**Hai tab kèm số đếm:** `Đơn hàng · 128` · `Đặt phòng chưa thanh toán · 14`.

**Thanh công cụ:** ô tìm `⌕ Email hoặc số điện thoại khách…` · 3 filter pill
(`Trạng thái đơn: Tất cả`, `Thanh toán: Tất cả`, `Khách sạn: Tất cả`, cao 36px,
bo 10px, nền `--g3`) · ô khoảng ngày `18/08/2026 – 24/08/2026` · nhãn
`Hiển thị 8 / 128 đơn`.

**Cột tab 1:** `MÃ ĐƠN` · `KHÁCH` (tên + email dòng nhỏ) · `KHÁCH SẠN` ·
`NGÀY NHẬN – TRẢ` · `PHÒNG` · `TỔNG TIỀN` · `ĐẶT PHÒNG` · `THANH TOÁN` ·
`TẠO LÚC` · `⋯`. Chiều cao dòng 48px.

**Chip trạng thái — copy và style lấy nguyên từ `BK`/`PAY` trong thiết kế:**

| Khoá | Nhãn | Style |
|---|---|---|
| `BK.PENDING` | `◔ Chờ xác nhận` | `--warn-soft` / `--warn-ink` |
| `BK.RESERVED` | `◑ Đang giữ chỗ` | `--acc-soft` / `--acc` |
| `BK.CONFIRMED` | `✓ Đã xác nhận` | `--ok-soft` / `--ok-ink` |
| `BK.CANCELLED` | `✕ Đã huỷ` | `--fill` / `--t3` + `line-through` |
| `BK.EXPIRED` | `⏱ Hết hạn giữ` | `--fill` / `--t3` |
| `PAY.PAID` | `✓ Đã thanh toán` | `--ok-soft` / `--ok-ink` |
| `PAY.PENDING` | `◔ Chờ thanh toán` | `--warn-soft` / `--warn-ink` |
| `PAY.FAILED` | `✕ Thất bại` | `--fill` / `--t3` + viền trong `rgba(192,94,112,.35)` |
| `PAY.NONE` | `— Chưa có` | `--fill` / `--t3` |

Chip dùng chung: `height:24px; padding:0 10px; border-radius:999px; font-size:12px;
font-weight:600`. **Chuyển nguyên hai object `BK`/`PAY` này thành hằng số trong
`order-status-chip.tsx`** — không tự đặt lại nhãn.

**Dải màu trái (`rail`):**
- `attention` (đã thanh toán, chưa xác nhận): nền `rgba(200,128,47,.06)`,
  `box-shadow: inset 3px 0 0 var(--warn)`
- `expiring` (sắp hết hạn giữ chỗ): nền `rgba(192,94,112,.05)`,
  `box-shadow: inset 3px 0 0 var(--err)`

Chú thích dưới bảng: `Dòng có dải màu bên trái: đã thanh toán, chưa xác nhận · sắp hết hạn giữ chỗ`.

**Tab 2 — Đặt phòng chưa thanh toán:**
- Dòng tóm tắt: `14 lượt giữ chỗ chưa gắn thanh toán` · `4 sắp hết hạn` ·
  nút `Giải phóng phòng hết hạn`.
- Cột: `MÃ GIỮ CHỖ` · `KHÁCH` · `KHÁCH SẠN · PHÒNG` · `HẾT HẠN SAU` · `NGUỒN`.
- Chip `HẾT HẠN SAU`: `⏱ 4 phút` — `--err-soft`/`--err` khi ≤ 30 phút,
  `--warn-soft`/`--warn-ink` khi > 30 phút, `⏱ Đã hết hạn` với `--fill`/`--t3`.
- Cột `NGUỒN`: link `Phiên chat` → mở phiên chat gốc theo `session_id`.

**Trạng thái rỗng (bộ lọc không khớp):** chip filter đang áp dụng có nút `✕`
(`Khách sạn: Amanoi Ninh Thuận ✕`, `Thanh toán: Thất bại ✕`), biểu tượng `▢`,
tiêu đề `Không có đơn nào khớp`, câu mô tả **có nội suy bộ lọc thật**
(`Trong 18/08 – 24/08/2026 không có đơn nào của Amanoi Ninh Thuận với thanh toán
thất bại.`), nút `Xoá 2 bộ lọc`.

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L1 | Chip `PAY.REFUNDED` = `↩ Đã hoàn tiền` | `payments.status` CHECK chỉ có `PENDING/PAID/FAILED/CANCELLED` — **không có REFUNDED** | Không render REFUNDED ở phase này. `CANCELLED` → dùng chip `--fill`/`--t3` nhãn `✕ Đã huỷ`. Muốn có REFUNDED thật thì phải nới CHECK constraint + luồng hoàn tiền — ngoài phạm vi |
| L2 | Nút `Tạo đơn thủ công` | Không có yêu cầu nào, không có endpoint, `create_booking_reservation` cần `temporary_user_ref` của khách | **Bỏ nút này.** Không render nút dẫn tới ngõ cụt |
| L3 | Nút `↓ Xuất CSV` | D6 vốn là P2, nhưng thiết kế có | **Giữ**, làm thật (endpoint `?format=csv`). Rẻ và đúng thiết kế |
| L4 | Nút `Giải phóng phòng hết hạn` (tab 2) | Có RPC `cancel_booking`; chưa có thao tác hàng loạt | **Giữ**, gọi `cancel_booking` lần lượt cho booking đã `expires_at < now()`, trả về số đã giải phóng. Chỉ tác động lên booking **đã hết hạn**, không phải "sắp hết hạn" |
| L5 | `Doanh thu hôm nay` dòng phụ `Trung bình 3.466.667 ₫/đơn` | Tính được | Giữ — tính `revenue_today / max(orders_today,1)` |
| L6 | `Chờ xử lý` dòng phụ `2 quá 2 giờ` | Tính được từ `created_at` | Giữ |
| L7 | `Đơn hôm nay` dòng phụ `+4 so với hôm qua` | Cần đếm hôm qua | Giữ — thêm một trường vào `stats` |

## Architecture — tầng dữ liệu

`payments.booking_ids` là `UUID[]` — PostgREST không join qua mảng được. Dựng hai
**view** để backend chỉ việc lọc/phân trang bằng PostgREST như bảng thường.

```sql
CREATE VIEW admin_orders AS
SELECT
  p.id              AS payment_id,
  p.status          AS payment_status,
  p.amount, p.currency,
  p.guest_name, p.guest_email, p.guest_phone,
  p.vnp_transaction_no, p.created_at, p.paid_at,
  p.temporary_user_ref,
  count(b.id)                              AS booking_count,
  coalesce(sum(b.room_count), 0)           AS room_count,
  min(b.check_in_date)                     AS check_in_date,
  max(b.check_out_date)                    AS check_out_date,
  array_agg(DISTINCT h.id)   FILTER (WHERE h.id IS NOT NULL)   AS hotel_ids,
  array_agg(DISTINCT h.name) FILTER (WHERE h.name IS NOT NULL) AS hotel_names,
  min(b.expires_at) FILTER (WHERE b.status = 'RESERVED')       AS earliest_expires_at,
  -- Trạng thái đặt phòng gộp cho cả đơn, quy tắc dứt khoát:
  CASE
    WHEN count(b.id) = 0                                              THEN 'UNKNOWN'
    WHEN count(*) FILTER (WHERE b.status = 'CONFIRMED') = count(b.id) THEN 'CONFIRMED'
    WHEN count(*) FILTER (WHERE b.status = 'CANCELLED') = count(b.id) THEN 'CANCELLED'
    WHEN count(*) FILTER (WHERE b.status = 'EXPIRED')   = count(b.id) THEN 'EXPIRED'
    WHEN count(*) FILTER (WHERE b.status = 'RESERVED')  > 0           THEN 'RESERVED'
    WHEN count(*) FILTER (WHERE b.status = 'PENDING')   > 0           THEN 'PENDING'
    ELSE 'MIXED'
  END AS booking_status,
  -- Cờ bất thường: đã thu tiền nhưng phòng chưa xác nhận (IPN lỗi)
  (p.status = 'PAID'
     AND count(*) FILTER (WHERE b.status = 'CONFIRMED') < count(b.id)) AS needs_attention
FROM payments p
LEFT JOIN bookings b ON b.id = ANY (p.booking_ids)
LEFT JOIN rooms    r ON r.id = b.room_id
LEFT JOIN hotels   h ON h.id = r.hotel_id
GROUP BY p.id;

CREATE VIEW admin_unpaid_bookings AS
SELECT b.id AS booking_id, b.status, b.check_in_date, b.check_out_date,
       b.room_count, b.total_amount, b.currency, b.expires_at,
       b.created_at, b.session_id, b.temporary_user_ref,
       r.id AS room_id, r.name AS room_name,
       h.id AS hotel_id, h.name AS hotel_name
FROM bookings b
LEFT JOIN rooms  r ON r.id = b.room_id
LEFT JOIN hotels h ON h.id = r.hotel_id
WHERE NOT EXISTS (SELECT 1 FROM payments p WHERE b.id = ANY (p.booking_ids));

REVOKE ALL ON admin_orders,    admin_unpaid_bookings FROM anon, authenticated, PUBLIC;
GRANT  SELECT ON admin_orders, admin_unpaid_bookings TO service_role;
```

> **Bắt buộc kiểm:** view trong Postgres mặc định chạy quyền của **owner**, nên có thể
> xuyên qua `REVOKE` trên `bookings`/`payments`. `REVOKE` trên chính view ở trên là lớp
> chặn. Xác nhận bằng cách gọi view với `anon` key → phải lỗi permission denied.
> Postgres ≥ 15: cân nhắc `WITH (security_invoker = true)`.

`MIXED` là trạng thái thật (đơn nhiều phòng huỷ một phần), không phải lỗi. Thiết kế
chưa có chip cho nó → thêm chip `⚠ Một phần` với `--warn-soft`/`--warn-ink`, cùng hệ
với các chip khác.

## Backend — hợp đồng API

```
GET /api/v1/admin/orders
  ?tab=paid|unpaid                (mặc định paid)
  &booking_status=PENDING|RESERVED|CONFIRMED|CANCELLED|EXPIRED|MIXED
  &payment_status=PENDING|PAID|FAILED|CANCELLED
  &from=2026-08-18&to=2026-08-24  (lọc theo created_at, inclusive)
  &hotel_id=<uuid>
  &q=<email hoặc số điện thoại>
  &needs_attention=true
  &page=1&page_size=25
  &format=json|csv                (csv → text/csv, bỏ qua phân trang, chặn 5000 dòng)
```

`200` (tab=paid):

```jsonc
{
  "items": [{
    "payment_id": "uuid",
    "order_code": "DH-24080",          // xem quy tắc mã đơn bên dưới
    "guest_name": "Trần Quốc Bảo",
    "guest_email": "bao.tran@vsf.dev",
    "guest_phone": "0905218447",
    "hotel_names": ["Silk Path Hà Nội"],
    "hotel_ids": ["uuid"],
    "check_in_date": "2026-08-25",
    "check_out_date": "2026-08-28",
    "room_count": 2,
    "booking_count": 2,
    "amount": "1850000.00",
    "currency": "VND",
    "booking_status": "PENDING",
    "payment_status": "PAID",
    "needs_attention": true,
    "earliest_expires_at": null,
    "created_at": "2026-08-24T08:47:00Z"
  }],
  "total": 128, "page": 1, "page_size": 25
}
```

`200` (tab=unpaid):

```jsonc
{
  "items": [{
    "booking_id": "uuid",
    "hold_code": "GC-9182",
    "guest_label": null,               // bookings không có tên khách — xem L8
    "hotel_name": "Vinpearl Resort Nha Trang",
    "room_name": "Ocean Suite",
    "check_in_date": "2026-08-30", "check_out_date": "2026-09-02",
    "room_count": 3, "total_amount": "12900000.00", "currency": "VND",
    "status": "RESERVED",
    "expires_at": "2026-08-24T10:46:00Z",
    "created_at": "2026-08-24T10:16:00Z",
    "session_id": "ct-90218"
  }],
  "total": 14, "page": 1, "page_size": 25,
  "expiring_count": 4                  // expires_at trong 30 phút tới
}
```

> **L8 — `KHÁCH` ở tab 2:** thiết kế hiện tên khách (`Lê Thu Hà`), nhưng `bookings`
> **không lưu tên khách** (V5 — tên chỉ có ở `payments`, mà tab 2 theo định nghĩa là
> booking chưa có payment). Hiển thị `temporary_user_ref` rút gọn + link `Phiên chat`.
> Cột giữ nguyên nhãn `KHÁCH`, giá trị là `Khách ẩn danh · <ref 8 ký tự>`.

```
POST /api/v1/admin/orders/holds/release-expired
→ 200 { "released": 3, "skipped": 1 }
```

Chỉ giải phóng booking `status IN ('RESERVED','PENDING')` **và** `expires_at < now()`,
qua RPC `cancel_booking` từng cái. Ghi 1 dòng audit tổng.

```
GET /api/v1/admin/orders/stats
→ 200 {
    "orders_today": 18, "orders_yesterday": 14,
    "revenue_today": "62400000.00", "currency": "VND",
    "avg_order_value": "3466667.00",
    "pending_count": 7, "pending_over_2h": 2,
    "expiring_holds_30m": 3
  }
```

Lỗi: `401`/`403` từ `require_admin`; `422` nếu `from > to` hoặc `page_size > 100`.

**Mã đơn `DH-24080`:** thiết kế dùng dạng `DH-` + 5 chữ số. `payments.id` là UUID,
không có số tăng dần. Quy tắc chốt: `DH-` + 5 ký tự hex **cuối** của UUID viết hoa
(`DH-3F2A1`). Hiển thị tooltip UUID đầy đủ khi di chuột. Không sinh cột mới, không
thêm sequence — mã chỉ để người đọc nhận diện, tra cứu vẫn bằng UUID.
Tương tự `GC-` cho mã giữ chỗ (`bookings.id`).

Ghi chú triển khai:
- `q` khớp `guest_email ILIKE %q%` OR `guest_phone ILIKE %q%` — PostgREST
  `or=(guest_email.ilike.*q*,guest_phone.ilike.*q*)`. Chuẩn hoá số điện thoại
  (bỏ khoảng trắng, `+84` → `0`) trước khi so.
- `hotel_id` lọc bằng toán tử chứa mảng: `hotel_ids=cs.{<uuid>}`.
- `total` lấy từ header `Content-Range` khi gọi với `count="exact"`.
- `page_size` chặn cứng ≤ 100.

## Frontend — màn hình D1

```
src/admin/pages/orders/
  orders-page.tsx          khung + tab + gọi API
  orders-toolbar.tsx       tìm, 3 filter pill, khoảng ngày, "Hiển thị n / N đơn"
  order-stat-cards.tsx     4 ô số liệu
  orders-table.tsx         tab 1
  unpaid-holds-table.tsx   tab 2
  order-status-chip.tsx    hằng số BK/PAY copy từ thiết kế
  orders-empty.tsx         rỗng-lọc-không-khớp (có chip filter + nút xoá)
src/admin/api/orders-client.ts
```

- Nhiều khách sạn trong một đơn: hiện tên đầu + `+N` (thiết kế chỉ vẽ 1 tên).
- Click dòng tab 1 → `/admin/orders/:payment_id` (Phase 5).
- Tab 2 không có trang chi tiết; `NGUỒN` → link phiên chat.
- Đếm ngược `HẾT HẠN SAU` cập nhật client-side mỗi 30s, không gọi lại API.
- Poll `stats` mỗi 60s; bảng chỉ tải lại khi admin đổi filter hoặc bấm làm mới.
- Trạng thái rỗng phải phân biệt "chưa có đơn nào" và "bộ lọc không khớp" — thiết
  kế chỉ vẽ cái thứ hai; cái thứ nhất dùng `EmptyState` chung của Phase 3.

## Related Code Files

- Create: `backend/scripts/migrations/20260824_add_admin_order_views.sql`
- Create: `backend/src/api/admin/orders.py`
- Create: `backend/tests/test_api/test_admin_orders.py`
- Create: `frontend/src/admin/api/orders-client.ts`
- Create: `frontend/src/admin/pages/orders/**` (danh sách ở trên)
- Modify: `backend/src/api/admin/__init__.py` (include router con)
- Modify: `frontend/src/admin/router.tsx` (gắn route `/admin/orders`)
- Modify: `frontend/src/types/wire.generated.ts` (sinh lại)
- Reference: `backend/src/services/booking_service.py` (`cancel_booking`)

## Sở hữu file

Nhánh Đơn hàng sở hữu `backend/src/api/admin/orders.py`,
`frontend/src/admin/pages/orders/**`, `frontend/src/admin/api/orders-client.ts`.
Không đụng file của nhánh Khách sạn / Pipeline.

## Implementation Steps

1. Viết migration view, chạy trên dev, kiểm quyền bằng `anon` key.
2. Đối chiếu số: `count(*) FROM payments` = `count(*) FROM admin_orders`.
3. `orders.py`: 3 endpoint trên + CSV.
4. Test backend.
5. Copy hằng số `BK`/`PAY` từ thiết kế vào `order-status-chip.tsx`.
6. Dựng màn theo checklist "Bám sát thiết kế", đối chiếu từng mục.
7. `npm run openapi:check`.

## Success Criteria

- [x] `count(*) FROM admin_orders` = `count(*) FROM payments`
- [x] Gọi `admin_orders` bằng `anon` key → permission denied
- [x] Đơn 2 phòng huỷ 1 phòng → `booking_status = 'MIXED'`, UI hiện chip `⚠ Một phần`
- [x] Đơn PAID mà booking còn RESERVED → `needs_attention`, dòng có dải `--warn` bên trái
- [x] Booking RESERVED sắp hết hạn → dải `--err` bên trái
- [x] Tab 2 chỉ hiện booking **không** thuộc payment nào (kiểm chéo bằng SQL)
- [x] `Giải phóng phòng hết hạn` chỉ đụng booking `expires_at < now()`; booking còn hạn không bị huỷ
- [x] 4 ô số liệu khớp SQL viết tay (`orders_today` = `count(*) FROM payments WHERE created_at::date = current_date`)
- [x] `?format=csv` tải về file mở được bằng Excel, tiếng Việt không lỗi font (BOM UTF-8)
- [x] Nhãn + màu 9 chip khớp đúng bảng trong "Bám sát thiết kế"
- [x] Trạng thái rỗng nội suy đúng tên bộ lọc đang áp dụng
- [x] Không có nút `Tạo đơn thủ công` (L2)

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| View bỏ qua `REVOKE` của bảng gốc → rò dữ liệu khách qua anon key | **Cao** | `REVOKE` trên chính view; có bước kiểm bằng anon key |
| `Giải phóng phòng hết hạn` huỷ nhầm booking còn hạn | **Cao** | Điều kiện `expires_at < now()` ở **backend**, không tin tham số từ client; test riêng |
| `LEFT JOIN b.id = ANY(p.booking_ids)` không dùng index | Trung bình | `EXPLAIN ANALYZE` khi > 10k payments; nếu chậm thêm GIN index trên `payments.booking_ids` |
| Quy tắc gộp `booking_status` không phủ hết tổ hợp | Trung bình | Nhánh `MIXED` là mặc định; test với đơn huỷ một phần |
| Mã `DH-` sinh từ hex UUID bị trùng khi nhiều đơn | Thấp | Mã chỉ để đọc, không dùng tra cứu; tooltip có UUID đầy đủ |
