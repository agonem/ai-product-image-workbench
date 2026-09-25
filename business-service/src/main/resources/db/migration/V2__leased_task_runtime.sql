-- T05: keep V1 immutable; transport metadata is separate from the v1 event payload.
CREATE TABLE output_presets (
    id opaque_id PRIMARY KEY,
    config_json jsonb NOT NULL CHECK (jsonb_typeof(config_json) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE generation_tasks ADD COLUMN worker_snapshot_json jsonb
    CHECK (worker_snapshot_json IS NULL OR jsonb_typeof(worker_snapshot_json) = 'object');
CREATE TRIGGER worker_snapshot_immutable BEFORE UPDATE ON generation_tasks
    FOR EACH ROW EXECUTE FUNCTION protect_columns('worker_snapshot_json');

ALTER TABLE outbox_events
    ADD COLUMN lease_token text,
    ADD COLUMN lease_until timestamptz,
    ADD COLUMN available_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN completed_at timestamptz,
    ADD CONSTRAINT lease_pair CHECK ((lease_token IS NULL) = (lease_until IS NULL));
CREATE INDEX outbox_available_idx ON outbox_events(available_at, created_at)
    WHERE completed_at IS NULL;
ALTER TABLE worker_receipts ADD COLUMN lease_token text;
CREATE TRIGGER receipt_lease_immutable BEFORE UPDATE ON worker_receipts
    FOR EACH ROW EXECUTE FUNCTION protect_columns('lease_token');
