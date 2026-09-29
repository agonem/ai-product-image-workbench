-- ADR-20260929-B / D-08: owners delete their own originals and generated results.
-- Rows stay (tasks, artifacts and audit keep their references); the stored bytes are removed and
-- every read path treats a deleted target as absent. A deletion is final and never edited.
CREATE TABLE deletions (
    target_id text CONSTRAINT deletions_pkey PRIMARY KEY,
    target_kind text NOT NULL CONSTRAINT deletions_kind_check CHECK (
        target_kind IN ('ASSET', 'ARTIFACT')),
    deleted_by text NOT NULL REFERENCES users(id),
    deleted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX deletions_actor_idx ON deletions(deleted_by);
CREATE TRIGGER deletion_immutable BEFORE UPDATE OR DELETE ON deletions
    FOR EACH ROW EXECUTE FUNCTION protect_record();
