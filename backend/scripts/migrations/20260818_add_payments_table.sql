-- Payment records for the VNPay integration (plan
-- 260818-vnpay-payment-and-email-confirmation). One row per checkout
-- attempt, covering ALL booking ids in that attempt's hold group — VNPay's
-- vnp_TxnRef is one-per-transaction, but a guest can hold several distinct
-- room types at once (see use-room-hold.ts), so `booking_ids` groups them.
-- Guest contact info is captured here (at "create payment" time, which is
-- when the checkout UI's guest-details step hands off to payment) because
-- bookings itself never collects it — see booking_service.py.
CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    temporary_user_ref TEXT NOT NULL,
    booking_ids UUID[] NOT NULL CHECK (array_length(booking_ids, 1) > 0),
    amount NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    currency VARCHAR(10) NOT NULL DEFAULT 'VND',
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PAID', 'FAILED', 'CANCELLED')),
    guest_name TEXT,
    guest_email TEXT,
    guest_phone TEXT,
    -- Populated only once VNPay's IPN confirms the transaction — see
    -- payment_service.py's mark_payment_paid/mark_payment_failed, whose
    -- conditional "WHERE status = 'PENDING'" update is this table's
    -- concurrency guard (a retried IPN call is a no-op, not a double-charge).
    vnp_transaction_no TEXT,
    vnp_response_code TEXT,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX payments_temporary_user_ref_idx ON payments (temporary_user_ref);

ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE payments FROM anon, authenticated, PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE payments TO service_role;
