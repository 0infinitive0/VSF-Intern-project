---
phase: 5
title: "Chi tiết đơn hàng (D2)"
status: done
priority: P1
effort: "1.5d"
dependencies: [4]
---

# Phase 5: Chi tiết đơn hàng — D2

## Overview

Trang xem đầy đủ một đơn: khách, các phòng, dòng thời gian, thông tin VNPay, link
sang phiên chat gốc. Chỉ đọc — hai nút hành động ở header dẫn sang Phase 6.

**Thiết kế bám theo:** artboard `D2 · CHI TIẾT ĐƠN HÀNG`.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb `Quản trị · Đơn hàng · DH-24080` · tiêu đề `Đơn DH-24080` ·
chip `◔ Chờ xác nhận` + chip `✓ Đã thanh toán` · nút `Xác nhận đơn` (nền `--btn`) ·
nút `Huỷ đơn` (**viền đỏ, nền trong suốt**, không phải nền đỏ).

**Bố cục 2 cột.**

**Cột trái:**

1. Khối `Thông tin khách` — 4 ô: `Họ tên` · `Email` · `Điện thoại` ·
   `Số đơn đã đặt` (`3`).
2. Khối `Phòng trong đơn`, phụ đề `2 phòng · 3 đêm`. Mỗi dòng (`detailRooms`):
   - `{hotel}` — `Silk Path Hà Nội`
   - `{room}` — `Deluxe King · 2 người · Ăn sáng`
   - `{dates} · {nights} đêm · {unit}/đêm` — `25/08 → 28/08/2026 · 3 đêm · 350.000 ₫/đêm`
   - `{total}` canh phải — `1.050.000 ₫`
   - chip trạng thái phòng: `✓ Còn phòng` (`--ok-soft`/`--ok-ink`) hoặc
     `◑ Đang giữ` (`--acc-soft`/`--acc`)
3. Khối tổng tiền: `Tạm tính 1.700.000 ₫` · `Thuế & phí dịch vụ 150.000 ₫` ·
   `Tổng tiền 1.850.000 ₫` (xem L9).

**Cột phải:**

4. `Dòng thời gian` — chấm tròn 11px + đường nối 1px `--stroke`. Bốn mốc mẫu:

| Tiêu đề | Thời gian | Ghi chú | Chấm |
|---|---|---|---|
| Đơn được tạo từ phiên chat | 24/08/2026 08:31 | — | `--t4` đặc |
| Giữ chỗ 2 phòng | 24/08/2026 08:33 | `Hết hạn giữ chỗ sau 00:12:41` (nền `--warn-soft`, chữ `--warn-ink`, `tabular-nums`) | `--acc` đặc |
| Thanh toán VNPay thành công | 24/08/2026 08:49 | — | `--ok` đặc |
| Chờ admin xác nhận | `Đang chờ · 1 giờ 53 phút` | `Bước tiếp theo: Xác nhận đơn hoặc Huỷ đơn` (nền `--fill`) | `--warn` **rỗng** (viền trong 2px), đường nối trong suốt |

   Mốc cuối luôn là mốc "đang chờ" — chấm rỗng, không có đường nối tiếp.

5. Khối `Thanh toán VNPay` + chip `✓ Thành công`. Các ô: `Mã giao dịch VNP14829371` ·
   `Số tiền 1.850.000 ₫` · `Thời điểm 24/08/2026 08:49` · `Ngân hàng NCB · ****4412`
   (xem L10).
   Banner cảnh báo bên dưới khi `needs_attention`:
   `Tiền đã về nhưng đơn chưa được xác nhận — cần xử lý trước 12:00 hôm nay.`
6. Khối `Xem cuộc trò chuyện gốc` — dòng phụ
   `Phiên chat #ct-90218 · 24/08/2026 08:31 · 14 tin nhắn`, biểu tượng `↗`.

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L9 | `Tạm tính` / `Thuế & phí dịch vụ` / `Tổng tiền` | Schema **không có** trường thuế/phí. Chỉ có `payments.amount` và `bookings.total_amount` | Tính: `Tạm tính = sum(bookings.total_amount)`, `Tổng tiền = payments.amount`, `Thuế & phí dịch vụ = amount - tạm tính`. **Chỉ render dòng "Thuế & phí dịch vụ" khi hiệu ≠ 0** — nếu bằng 0 thì hiện đúng 2 dòng. Không bịa số |
| L10 | `Ngân hàng NCB · ****4412` | `payments` chỉ lưu `vnp_transaction_no`, `vnp_response_code`. **Không lưu** `vnp_BankCode`/`vnp_CardType` (xem `routes.py:383-385`) | **Bỏ ô "Ngân hàng"** ở phase này. Muốn có: thêm cột `vnp_bank_code`, `vnp_card_type` + ghi trong IPN handler — là thay đổi luồng thanh toán đang chạy, ngoài phạm vi plan này |
| L11 | `Số đơn đã đặt 3` | Tính được | Đếm `payments` cùng `temporary_user_ref` **hoặc** cùng `guest_email` (lấy `max` của hai cách, vì khách có thể đổi thiết bị). Chọn `guest_email` khi có, ngược lại `temporary_user_ref` |
| L12 | `Deluxe King · 2 người · Ăn sáng` | `rooms` không có trường "gói ăn sáng" | Hiện `{room.name} · {room.max_guests} người`. Bỏ phần gói ăn |
| L13 | `cần xử lý trước 12:00 hôm nay` | Không có SLA nào trong hệ thống | Đổi copy thành `Tiền đã về nhưng đơn chưa được xác nhận — đã chờ {n} giờ.` Không hứa deadline không tồn tại |
| L14 | `14 tin nhắn` | Đếm được từ `chat_messages` theo `session_id` | Giữ. Nếu `session_id` NULL (booking không từ chat) thì ẩn cả khối |

## Backend — hợp đồng API

```
GET /api/v1/admin/orders/{payment_id}
```

`200`:

```jsonc
{
  "payment_id": "uuid",
  "order_code": "DH-24080",
  "booking_status": "PENDING",
  "payment_status": "PAID",
  "needs_attention": true,
  "attention_hours": 2,                    // L13
  "guest": {
    "name": "Trần Quốc Bảo",
    "email": "bao.tran@vsf.dev",
    "phone": "0905218447",
    "order_count": 3                        // L11
  },
  "rooms": [{
    "booking_id": "uuid",
    "hotel_id": "uuid", "hotel_name": "Silk Path Hà Nội",
    "room_id": "uuid",  "room_name": "Deluxe King",
    "max_guests": 2,
    "check_in_date": "2026-08-25", "check_out_date": "2026-08-28",
    "nights": 3, "room_count": 1,
    "unit_price": "350000.00",              // total_amount / nights / room_count
    "total_amount": "1050000.00",
    "status": "CONFIRMED",
    "expires_at": null
  }],
  "totals": {
    "subtotal": "1700000.00",               // sum(bookings.total_amount)
    "fee": "150000.00",                     // amount - subtotal; null nếu = 0  (L9)
    "total": "1850000.00",                  // payments.amount
    "currency": "VND"
  },
  "timeline": [
    {"kind": "created",   "at": "2026-08-24T08:31:00Z"},
    {"kind": "reserved",  "at": "2026-08-24T08:33:00Z", "expires_at": "2026-08-24T09:03:00Z"},
    {"kind": "paid",      "at": "2026-08-24T08:49:00Z"},
    {"kind": "awaiting_admin", "since": "2026-08-24T08:49:00Z"}
  ],
  "vnpay": {
    "transaction_no": "VNP14829371",
    "response_code": "00",
    "paid_at": "2026-08-24T08:49:00Z",
    "amount": "1850000.00", "currency": "VND"
  },
  "chat_session": {                          // null nếu không có session_id
    "session_id": "ct-90218",
    "started_at": "2026-08-24T08:31:00Z",
    "message_count": 14
  }
}
```

`404` khi không có payment. `401`/`403` từ `require_admin`.

**Dòng thời gian** dựng từ dữ liệu có thật, không lưu bảng sự kiện riêng:

| `kind` | Nguồn | Tiêu đề hiển thị |
|---|---|---|
| `created` | `min(bookings.created_at)` | Đơn được tạo từ phiên chat |
| `reserved` | booking đầu tiên có `status='RESERVED'` / `expires_at` | Giữ chỗ {n} phòng |
| `paid` | `payments.paid_at` | Thanh toán VNPay thành công |
| `cancelled` | `bookings.cancelled_at` | Đã huỷ {n} phòng |
| `confirmed` | `bookings.updated_at` khi mọi booking CONFIRMED | Đã xác nhận đơn |
| `awaiting_admin` | suy ra: PAID nhưng chưa CONFIRMED | Chờ admin xác nhận |

Mốc `awaiting_admin` chỉ xuất hiện khi đúng điều kiện, và luôn là mốc cuối
(chấm rỗng). `expired` suy ra từ `status='EXPIRED'`.

> `bookings` không có bảng lịch sử trạng thái — `updated_at` chỉ giữ lần đổi **cuối**.
> Nên timeline là **suy diễn**, không phải nhật ký. Không hiển thị mốc nào mà dữ liệu
> không chứng minh được. Nếu sau này cần timeline chính xác thì phải thêm bảng sự kiện,
> ngoài phạm vi plan này.

## Frontend — màn hình D2

```
src/admin/pages/orders/
  order-detail-page.tsx
  order-guest-card.tsx
  order-rooms-card.tsx      + khối tổng tiền
  order-timeline.tsx
  order-vnpay-card.tsx
  order-chat-link.tsx
```

- Đếm ngược `Hết hạn giữ chỗ sau 00:12:41` chạy client-side, cập nhật mỗi giây,
  `tabular-nums`. Về 0 → đổi thành `Đã hết hạn` màu `--t3`, không tự gọi API.
- Nút `Huỷ đơn`: `background: transparent; color: var(--err); border: 1px solid var(--err)`.
- Hai nút header mở hộp thoại của Phase 6; ở phase này render nút **disabled** kèm
  tooltip `Sắp có` là **không** chấp nhận được — làm Phase 5 và 6 liền nhau, hoặc
  Phase 5 ẩn hẳn hai nút cho tới khi Phase 6 xong.
- Link phiên chat mở tab mới tới app chat (`/?session=<session_id>`) — kiểm app chat
  có nhận query param này không; nếu không thì chỉ hiện `session_id` để tra thủ công,
  **không** làm link chết.

## Related Code Files

- Modify: `backend/src/api/admin/orders.py` (thêm endpoint chi tiết)
- Modify: `backend/tests/test_api/test_admin_orders.py`
- Create: `frontend/src/admin/pages/orders/order-detail-page.tsx` + 5 file con
- Modify: `frontend/src/admin/api/orders-client.ts`
- Modify: `frontend/src/admin/router.tsx` (route `/admin/orders/:id`)
- Reference: `backend/src/services/payment_service.py` (`booking_summary_for_email`, `get_payment` — đã gom sẵn hotel/room cho booking_ids, dùng lại thay vì viết lại truy vấn)

## Implementation Steps

1. Đọc `payment_service.booking_summary_for_email` — nó đã join booking → room →
   hotel sẵn. Tái dùng, đừng viết truy vấn thứ hai làm cùng việc.
2. Viết endpoint chi tiết + hàm dựng timeline.
3. Test: đơn đầy đủ, đơn không có `session_id`, đơn `fee = 0`, đơn đã huỷ.
4. Dựng màn theo checklist.
5. `npm run openapi:check`.

## Success Criteria

- [x] `subtotal + fee = total` với mọi đơn; `fee = null` thì UI chỉ hiện 2 dòng
- [x] Đơn không có `session_id` → khối "Xem cuộc trò chuyện gốc" **không** render
- [x] Đơn PAID chưa CONFIRMED → timeline có mốc cuối `Chờ admin xác nhận` chấm rỗng
- [x] Đơn đã huỷ → timeline có mốc `Đã huỷ`, **không** có `awaiting_admin`
- [x] Đếm ngược hết hạn giữ chỗ chạy đúng và dừng ở `Đã hết hạn`
- [x] Không có ô "Ngân hàng" (L10), không có "Ăn sáng" (L12)
- [x] `order_count` khớp `SELECT count(*) FROM payments WHERE guest_email = ...`
- [x] `payment_id` không tồn tại → 404, UI hiện trạng thái lỗi của Phase 3

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Timeline suy diễn sai vì `updated_at` chỉ giữ lần đổi cuối | Trung bình | Chỉ dựng mốc từ trường có bằng chứng (`paid_at`, `cancelled_at`, `expires_at`); ghi rõ giới hạn trong code comment |
| `unit_price` chia ra số lẻ khó chịu (216.667 ₫ trong thiết kế) | Thấp | Làm tròn tới đồng, ghi nhãn `≈` khi có phần dư. VND không có đơn vị nhỏ hơn |
| Tái dùng `booking_summary_for_email` kéo theo phụ thuộc email vào tầng admin | Thấp | Chỉ import hàm truy vấn, không import `email_service` |
| Link phiên chat dẫn tới trang không tồn tại | Trung bình | Kiểm app chat có nhận `?session=` không **trước** khi render link |
