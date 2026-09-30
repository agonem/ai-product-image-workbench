-- ADR-20260930-F. Scene presets and selling-point styles are edited by admins as one catalogue.
-- Every save or rollback appends an immutable version and the newest version is in force;
-- without any row the bundled defaults (contracts/presets.json) apply. Tasks keep the copies
-- frozen into their snapshots, so history never changes.
CREATE TABLE preset_catalog_versions (
    version integer PRIMARY KEY CHECK (version > 0),
    config jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
    note text NOT NULL DEFAULT '' CHECK (length(note) <= 200),
    restored_from integer REFERENCES preset_catalog_versions(version),
    published_by opaque_id NOT NULL REFERENCES users(id),
    published_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER preset_catalog_immutable BEFORE UPDATE OR DELETE ON preset_catalog_versions
    FOR EACH ROW EXECUTE FUNCTION protect_record();

-- Personal templates: create-page settings without images, one name per owner and entry.
CREATE TABLE user_templates (
    id opaque_id PRIMARY KEY,
    owner_id opaque_id NOT NULL REFERENCES users(id),
    feature_type text NOT NULL CHECK (feature_type IN ('GIFT', 'SCENE', 'SELLING_POINT')),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 40),
    settings jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_templates_name_unique UNIQUE (owner_id, feature_type, name)
);
