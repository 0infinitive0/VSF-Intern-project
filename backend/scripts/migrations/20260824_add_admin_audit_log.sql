-- Audit trail for admin-side writes (hotel edits, price overrides, order
-- cancellations, pipeline actions) against live, paying-guest data. No admin
-- screen reads this table yet -- it exists so that "who changed the price to
-- X and when" is answerable at all, which a missing audit trail on real-money
-- data would otherwise make an unrecoverable gap. Read it ad hoc via SQL /
-- Supabase Studio until a UI is built. If this is cut later, drop this file's
-- table and the write_audit() helper it pairs with; other call sites just
-- drop the call.
CREATE TABLE admin_audit_log (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor_id     UUID NOT NULL,          -- Supabase auth user id
    actor_email  TEXT,
    action       TEXT NOT NULL,          -- 'hotel.update' | 'price.set' | 'order.cancel' | ...
    entity_type  TEXT NOT NULL,          -- 'hotel' | 'room' | 'room_price' | 'payment' | 'pipeline'
    entity_id    TEXT NOT NULL,
    before       JSONB,
    after        JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX admin_audit_log_created_idx ON admin_audit_log (created_at DESC);
CREATE INDEX admin_audit_log_entity_idx  ON admin_audit_log (entity_type, entity_id);

ALTER TABLE admin_audit_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE admin_audit_log FROM anon, authenticated, PUBLIC;
GRANT SELECT, INSERT ON TABLE admin_audit_log TO service_role;
