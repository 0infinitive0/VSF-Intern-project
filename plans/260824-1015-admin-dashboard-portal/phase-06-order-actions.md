---
phase: 6
title: "Xác nhận / Huỷ đơn (D3)"
status: done
priority: P1
effort: "1d"
dependencies: [5]
---

# Phase 6: Xác nhận / Huỷ đơn — D3

## Overview

Hai hành động ghi duy nhất của nhánh Đơn hàng. Cả hai đi qua RPC có sẵn
(`confirm_booking_reservation`, `cancel_booking`) — **không** UPDATE thẳng bảng.

**Thiết kế bám theo:** artboard `D3 · HỘP THOẠI XÁC NHẬN / HUỶ ĐƠN` (vẽ cả hai).

## Bám sát thiết kế — checklist đối chiếu 1:1

### Hộp thoại Xác nhận

- Tiêu đề: `Xác nhận đơn DH-24080?`
- Nội dung: `Đơn sẽ chuyển sang **Đã xác nhận**. Khách nhận email xác nhận kèm mã đặt
  phòng, khách sạn nhận thông báo giữ phòng.` (xem L15)
- Ba ô tóm tắt: `Khách — Trần Quốc Bảo` · `Phòng — 2 phòng · Silk Path Hà Nội` ·
  `Tổng tiền đã thu — 1.850.000 ₫`
- Nút: `Để sau` (phụ) · `Xác nhận 2 phòng` (chính, nền `--btn`) — **nút chính nêu rõ
  hành động và số lượng**, không phải "OK".

### Hộp thoại Huỷ

- Biểu tượng `!` cảnh báo, tiêu đề `Huỷ đơn DH-24080?`
- Dòng đầu: `Hành động này **không thể hoàn tác**.`
- `Lý do huỷ (bắt buộc)` — select, mặc định `Khách yêu cầu huỷ`
- `Ghi chú thêm (tuỳ chọn)…` — textarea
- Khối `HẬU QUẢ` (nhãn mono nhỏ), 3 gạch đầu dòng:
  - `2 phòng tại Silk Path Hà Nội được trả lại kho phòng ngay lập tức`
  - `Khách nhận email huỷ đơn tại bao.tran@vsf.dev` ← **xem L16**
  - `Khoản đã thu 1.850.000 ₫ phải hoàn thủ công qua VNPay`
- Nút: `Giữ nguyên đơn` (phụ) · `Huỷ 2 phòng` (nguy hiểm)

### Banner kết quả (bộ Z)

Sau khi thành công, hiện banner `✓ Đã xác nhận đơn DH-24080 và gửi email cho khách.`
(`--ok-soft`). Lỗi → banner `!` `--err-soft`.

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L15 | Xác nhận → `Khách nhận email xác nhận kèm mã đặt phòng, khách sạn nhận thông báo giữ phòng` | `send_booking_confirmation_email` **có thật** (`email_service.py:143`). Nhưng **không có** luồng thông báo cho khách sạn | Giữ nửa đầu (gửi email khách — gọi hàm đã có). **Bỏ** vế "khách sạn nhận thông báo giữ phòng" khỏi copy |
| L16 | Huỷ → `Khách nhận email huỷ đơn tại ...` | **Quyết định #11: không gửi email huỷ.** `email_service` cũng chưa có template huỷ | **Bỏ dòng này** khỏi khối HẬU QUẢ. Banner kết quả của huỷ cũng không được nhắc email. Chỉ còn 2 gạch đầu dòng |
| L17 | Banner `✓ Đã xác nhận đơn DH-24080 và gửi email cho khách.` | Đúng với xác nhận | Giữ cho xác nhận. Banner huỷ: `✓ Đã huỷ 2 phòng của đơn DH-24080.` |
| L18 | `Lý do huỷ` là select | Không có bảng lý do | Danh sách cứng ở frontend, lưu vào `admin_audit_log.after.reason`: `Khách yêu cầu huỷ` · `Hết phòng` · `Thanh toán không hợp lệ` · `Đơn trùng` · `Lý do khác` |

## Backend — hợp đồng API

```
POST /api/v1/admin/orders/{payment_id}/confirm
  body: {}                                     (không có tham số)
→ 200 {
    "payment_id": "uuid",
    "confirmed": 2, "failed": 0,
    "booking_status": "CONFIRMED",
    "email_sent": true,
    "results": [{"booking_id": "uuid", "ok": true, "error": null}]
  }
→ 409 { "detail": "booking_not_confirmable" }   // toàn bộ đều thất bại
→ 404 payment không tồn tại
```

```
POST /api/v1/admin/orders/{payment_id}/cancel
  body: { "reason": "Khách yêu cầu huỷ", "note": "..." }   reason bắt buộc
→ 200 {
    "payment_id": "uuid",
    "cancelled": 2, "failed": 0,
    "booking_status": "CANCELLED",
    "results": [...]
  }
→ 422 thiếu reason
→ 409 không có booking nào huỷ được
```

### Quy tắc thực thi

Một payment gom nhiều booking. Gọi RPC **từng booking**:

```python
for booking_id in payment["booking_ids"]:
    try:
        confirm_booking(booking_id=booking_id,
                        temporary_user_ref=payment["temporary_user_ref"])
    except BookingError as exc:
        results.append({"booking_id": ..., "ok": False, "error": str(exc)})
```

- `temporary_user_ref` lấy từ **`payments`**, không nhận từ client — RPC dùng nó làm
  điều kiện sở hữu; để client truyền vào là lỗ hổng.
- **Thành công một phần là kết quả hợp lệ**, không phải lỗi: trả `200` kèm
  `confirmed`/`failed` và `results[]`. UI hiện banner cảnh báo liệt kê phòng lỗi.
  Chỉ `409` khi **không** booking nào thành công.
- Booking đã ở đúng trạng thái đích → tính là thành công (idempotent), không tính lỗi.
- **Không** bọc trong transaction: mỗi RPC có advisory lock riêng, gộp lại sẽ giữ
  khoá lâu và dễ deadlock. Bù lại phải chấp nhận thành công một phần — đã xử lý ở trên.
- Email xác nhận: gọi `send_booking_confirmation_email` **sau khi** mọi booking
  CONFIRMED, chỉ một lần cho cả đơn, và **nuốt lỗi** — email hỏng không được làm hỏng
  thao tác đã ghi vào DB. `email_sent` phản ánh kết quả thật.
- Huỷ: **không** gửi email (quyết định #11).
- Audit: một dòng cho cả đơn, `entity_type='payment'`, `entity_id=payment_id`,
  `before={booking_status cũ}`, `after={booking_status mới, reason, note, results}`.

## Frontend — hộp thoại D3

```
src/admin/pages/orders/
  confirm-order-dialog.tsx
  cancel-order-dialog.tsx
```

- Nút chính nêu rõ số lượng: `Xác nhận {n} phòng` / `Huỷ {n} phòng` — `n` là
  `sum(room_count)` của các booking còn xử lý được, không phải `booking_count`.
- Nút huỷ disabled tới khi chọn `Lý do huỷ`.
- Trong lúc gọi API: nút chuyển spinner, khoá cả hai nút, **khoá cả nút đóng** —
  bấm hai lần là gọi RPC hai lần.
- Sau khi xong: đóng hộp thoại, hiện banner, tải lại D2. Nếu `failed > 0` thì banner
  cảnh báo liệt kê phòng lỗi kèm mã lỗi đã dịch:

| Mã lỗi RPC | Câu tiếng Việt |
|---|---|
| `booking_not_confirmable` | Phòng này không ở trạng thái xác nhận được (có thể đã huỷ hoặc hết hạn giữ chỗ). |
| `booking_reservation_expired` | Lượt giữ chỗ đã hết hạn, phòng đã được trả về kho. |
| `booking_not_found` | Không tìm thấy lượt đặt phòng này. |
| `insufficient_room_availability` | Không còn đủ phòng trống cho khoảng ngày này. |
| `booking_operation_failed` | Thao tác không thực hiện được. Thử lại hoặc kiểm tra log máy chủ. |

Bảng này để ở `src/admin/lib/booking-error-vi.ts`. Frontend đã có
`src/lib/booking-error.ts` cho app chat — **đọc file đó trước**, tái dùng nếu nội dung
khớp, tránh hai bản dịch lệch nhau.

## Related Code Files

- Modify: `backend/src/api/admin/orders.py`
- Modify: `backend/tests/test_api/test_admin_orders.py`
- Create: `frontend/src/admin/pages/orders/confirm-order-dialog.tsx`, `cancel-order-dialog.tsx`
- Create: `frontend/src/admin/lib/booking-error-vi.ts` (hoặc tái dùng bản có sẵn)
- Modify: `frontend/src/admin/pages/orders/order-detail-page.tsx` (nối 2 nút)
- Reference: `backend/src/services/booking_service.py`, `backend/src/services/email_service.py`, `frontend/src/lib/booking-error.ts`

## Implementation Steps

1. Đọc `booking_service.py` (đã có `confirm_booking`/`cancel_booking` + bảng mã lỗi
   trong `_call`) và `frontend/src/lib/booking-error.ts`.
2. Viết 2 endpoint, ghi audit.
3. Test: xác nhận đủ · huỷ đủ · thành công một phần · toàn bộ thất bại (409) ·
   gọi hai lần liên tiếp (idempotent) · thiếu `reason` (422).
4. Hai hộp thoại theo checklist, bỏ L15/L16.
5. `npm run openapi:check`.

## Success Criteria

- [x] Xác nhận đơn 2 phòng → cả 2 `bookings.status = 'CONFIRMED'`, kiểm bằng SQL
- [x] Huỷ đơn → `status = 'CANCELLED'` và `cancelled_at` được set
- [x] Một phòng đã huỷ trước đó → `200` với `confirmed:1, failed:1`, UI liệt kê phòng lỗi
- [x] Gọi confirm hai lần → lần hai vẫn `200`, không tạo thêm thay đổi, không gửi email lần hai
- [x] `admin_audit_log` có đúng **một** dòng cho mỗi thao tác, `after.reason` đúng
- [x] Email xác nhận gửi được; tắt Resend key → thao tác vẫn `200`, `email_sent:false`
- [x] Hộp thoại huỷ **không** nhắc gì tới email (L16)
- [x] Hộp thoại xác nhận **không** nhắc "khách sạn nhận thông báo" (L15)
- [x] Bấm nhanh hai lần vào nút xác nhận chỉ gửi một request
- [x] Không có chỗ nào UPDATE thẳng `bookings.status` (grep xác nhận)

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Nhận `temporary_user_ref` từ client → bỏ qua kiểm tra sở hữu của RPC | **Cao** | Luôn lấy từ `payments` phía server; code review bắt buộc |
| Bấm đúp gửi hai request → gọi RPC hai lần | Cao | Khoá nút + khoá nút đóng khi đang gửi; RPC vốn idempotent theo state machine |
| Thành công một phần bị coi là lỗi → admin tưởng chưa làm gì, bấm lại | Cao | Trả `200` + `results[]`; UI liệt kê rõ phòng nào lỗi |
| Email lỗi làm rollback thao tác đã ghi DB | Trung bình | Gửi email **sau** khi DB xong, bọc try/except, `email_sent` phản ánh thật |
| Gộp nhiều RPC trong một transaction gây deadlock | Trung bình | Đã quyết định không gộp; ghi lý do trong code comment |
