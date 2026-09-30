-- ADR-20260930-E. A generated result can be reused as a new original (copied, with the source
-- recorded), and admins can delete accounts. A deleted account keeps its row for history, loses its
-- credentials (so its login name can be reused) and has its images removed.
ALTER TABLE assets ADD COLUMN source_artifact_id opaque_id REFERENCES artifacts(id);
DROP TRIGGER asset_source_immutable ON assets;
CREATE TRIGGER asset_source_immutable BEFORE UPDATE ON assets
    FOR EACH ROW EXECUTE FUNCTION protect_columns(
        'id', 'project_id', 'kind', 'source_asset_id', 'object_key', 'sha256', 'width', 'height',
        'created_at', 'source_artifact_id');
CREATE INDEX assets_source_artifact_idx ON assets(source_artifact_id)
    WHERE source_artifact_id IS NOT NULL;

ALTER TABLE users DROP CONSTRAINT users_status_check;
ALTER TABLE users ADD CONSTRAINT users_status_check
    CHECK (status IN ('ACTIVE', 'DISABLED', 'DELETED'));
ALTER TABLE users ADD COLUMN deleted_username text;
ALTER TABLE users ADD CONSTRAINT users_deleted_username_check
    CHECK ((status = 'DELETED') = (deleted_username IS NOT NULL));
