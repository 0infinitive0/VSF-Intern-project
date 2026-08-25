-- Admin D1 (Danh sách đơn hàng) read model — phase-04-orders-list.md.
--
-- `payments.booking_ids` is a UUID[] — PostgREST can't join through an array
-- column, so both views below pre-join it and expose plain rows the admin
-- API can filter/paginate like any other table.
--
-- `admin_orders`: one row per payment ("đơn hàng" = one payment, decision
-- #2), with booking aggregates and a single `booking_status` rollup so the
-- list screen never has to reconcile N booking rows itself.
--
-- `admin_unpaid_bookings`: bookings not attached to ANY payment yet — the
-- "Đặt phòng chưa thanh toán" tab. A booking only ever leaves this view once
-- a payment row references it, regardless of that payment's own status.
--
-- Both are service_role-only, same posture as admin_hotel_rows
-- (20260824_add_admin_hotel_view.sql): views run at owner privilege by
-- default and would otherwise read straight through the REVOKE already on
-- `bookings`/`payments`, so the REVOKE has to be repeated here as the actual
-- blocking layer. Verify by calling either view with an `anon` key — must
-- come back permission denied.
CREATE OR REPLACE VIEW public.admin_orders AS
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
  -- Cờ bất thường: đã thu tiền nhưng phòng chưa xác nhận hết (IPN lỗi)
  (p.status = 'PAID'
     AND count(*) FILTER (WHERE b.status = 'CONFIRMED') < count(b.id)) AS needs_attention
FROM public.payments p
-- `p.booking_ids @> ARRAY[b.id]` (containment), not `b.id = ANY (p.booking_ids)`:
-- semantically identical, but only the containment form is indexable by a
-- GIN index on `booking_ids` -- `= ANY(array)` never uses one. The plan's
-- risk-table mitigation ("thêm GIN index trên booking_ids" if this gets
-- slow) only actually works against this form.
LEFT JOIN public.bookings b ON p.booking_ids @> ARRAY[b.id]
LEFT JOIN public.rooms    r ON r.id = b.room_id
LEFT JOIN public.hotels   h ON h.id = r.hotel_id
GROUP BY p.id;

CREATE OR REPLACE VIEW public.admin_unpaid_bookings AS
SELECT b.id AS booking_id, b.status, b.check_in_date, b.check_out_date,
       b.room_count, b.total_amount, b.currency, b.expires_at,
       b.created_at, b.session_id, b.temporary_user_ref,
       r.id AS room_id, r.name AS room_name,
       h.id AS hotel_id, h.name AS hotel_name
FROM public.bookings b
LEFT JOIN public.rooms  r ON r.id = b.room_id
LEFT JOIN public.hotels h ON h.id = r.hotel_id
-- Same containment form -- this NOT EXISTS is a correlated anti-join run
-- per booking, on every tab-2 page load, so it's the more index-sensitive
-- of the two.
WHERE NOT EXISTS (SELECT 1 FROM public.payments p WHERE p.booking_ids @> ARRAY[b.id]);

REVOKE ALL ON public.admin_orders,    public.admin_unpaid_bookings FROM anon, authenticated, PUBLIC;
GRANT  SELECT ON public.admin_orders, public.admin_unpaid_bookings TO service_role;
