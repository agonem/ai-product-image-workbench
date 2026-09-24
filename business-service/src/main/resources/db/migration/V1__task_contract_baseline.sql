-- T03 / PRD-G03,G06 / ACC-T03. No users, templates or business defaults are seeded.
CREATE DOMAIN opaque_id AS text CHECK (VALUE ~ '^[A-Za-z0-9][A-Za-z0-9_-]*$');
CREATE DOMAIN sha256_hash AS text CHECK (VALUE ~ '^[0-9a-f]{64}$');
CREATE DOMAIN storage_key AS text CHECK (
    VALUE ~ '^[A-Za-z0-9][A-Za-z0-9/_.-]*$'
    AND VALUE !~ '(^|/)\.{1,2}(/|$)'
);

CREATE TABLE users (
    id opaque_id PRIMARY KEY,
    role text,
    status text NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE projects (
    id opaque_id PRIMARY KEY,
    owner_id opaque_id NOT NULL REFERENCES users(id),
    name text NOT NULL CHECK (length(btrim(name)) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX projects_owner_idx ON projects(owner_id);

CREATE TABLE assets (
    id opaque_id PRIMARY KEY,
    project_id opaque_id NOT NULL REFERENCES projects(id),
    kind text NOT NULL CHECK (kind IN ('PRODUCT', 'GIFT', 'ALPHA')),
    source_asset_id opaque_id,
    object_key storage_key NOT NULL UNIQUE,
    sha256 sha256_hash NOT NULL,
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    review_status text NOT NULL DEFAULT 'PENDING'
        CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(id, project_id),
    FOREIGN KEY(source_asset_id, project_id) REFERENCES assets(id, project_id),
    CHECK ((kind = 'ALPHA') = (source_asset_id IS NOT NULL)),
    CHECK (source_asset_id IS DISTINCT FROM id)
);
CREATE INDEX assets_project_idx ON assets(project_id);
CREATE INDEX assets_source_idx ON assets(source_asset_id, project_id);

CREATE TABLE templates (
    id opaque_id PRIMARY KEY,
    type text NOT NULL CHECK (type IN ('scene', 'layout', 'style')),
    name text NOT NULL CHECK (length(btrim(name)) > 0),
    published_version_id opaque_id,
    state text NOT NULL DEFAULT 'DRAFT' CHECK (state IN ('DRAFT', 'PUBLISHED', 'DISABLED'))
);
CREATE TABLE template_versions (
    id opaque_id PRIMARY KEY,
    template_id opaque_id NOT NULL REFERENCES templates(id),
    version integer NOT NULL CHECK (version > 0),
    config_json jsonb NOT NULL CHECK (jsonb_typeof(config_json) = 'object'),
    created_by opaque_id NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_by opaque_id REFERENCES users(id),
    published_at timestamptz,
    UNIQUE(template_id, version),
    UNIQUE(id, template_id),
    CHECK ((published_by IS NULL) = (published_at IS NULL))
);
ALTER TABLE templates ADD CONSTRAINT template_published_version_fk
    FOREIGN KEY(published_version_id, id) REFERENCES template_versions(id, template_id);
CREATE INDEX templates_published_idx ON templates(published_version_id, id);
CREATE INDEX template_versions_creator_idx ON template_versions(created_by);
CREATE INDEX template_versions_publisher_idx ON template_versions(published_by);

CREATE TABLE generation_tasks (
    id opaque_id PRIMARY KEY,
    project_id opaque_id NOT NULL REFERENCES projects(id),
    product_asset_id opaque_id NOT NULL,
    gift_asset_id opaque_id,
    feature_type text NOT NULL CHECK (feature_type IN ('GIFT', 'SCENE', 'SELLING_POINT')),
    status text NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')),
    created_by opaque_id NOT NULL REFERENCES users(id),
    idempotency_key text NOT NULL CHECK (
        length(idempotency_key) BETWEEN 1 AND 128 AND idempotency_key ~ '^[A-Za-z0-9._:-]+$'
    ),
    request_sha256 sha256_hash NOT NULL,
    request_snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(request_snapshot_json) = 'object'),
    template_snapshot_json jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(template_snapshot_json) = 'object'),
    current_attempt_id opaque_id,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(created_by, feature_type, idempotency_key),
    FOREIGN KEY(product_asset_id, project_id) REFERENCES assets(id, project_id),
    FOREIGN KEY(gift_asset_id, project_id) REFERENCES assets(id, project_id),
    CHECK ((feature_type = 'GIFT') = (gift_asset_id IS NOT NULL))
);
CREATE INDEX generation_tasks_project_idx ON generation_tasks(project_id, created_at DESC);
CREATE INDEX generation_tasks_product_idx ON generation_tasks(product_asset_id, project_id);
CREATE INDEX generation_tasks_gift_idx ON generation_tasks(gift_asset_id, project_id);

CREATE TABLE task_attempts (
    id opaque_id PRIMARY KEY,
    task_id opaque_id NOT NULL REFERENCES generation_tasks(id),
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    status text NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')),
    started_at timestamptz,
    ended_at timestamptz,
    error_code text,
    safe_message text,
    retryable boolean,
    provider_info jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(task_id, attempt_no),
    UNIQUE(id, task_id),
    CHECK (ended_at IS NULL OR (started_at IS NOT NULL AND ended_at >= started_at)),
    CHECK (provider_info IS NULL OR jsonb_typeof(provider_info) = 'object')
);
ALTER TABLE generation_tasks ADD CONSTRAINT task_current_attempt_fk
    FOREIGN KEY(current_attempt_id, id) REFERENCES task_attempts(id, task_id)
    DEFERRABLE INITIALLY IMMEDIATE;
CREATE INDEX generation_tasks_current_attempt_idx ON generation_tasks(current_attempt_id, id);

CREATE TABLE artifacts (
    id opaque_id PRIMARY KEY,
    task_id opaque_id NOT NULL,
    attempt_id opaque_id NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    kind text NOT NULL CHECK (kind IN ('COMPOSITE', 'BACKGROUND', 'ALPHA')),
    object_key storage_key NOT NULL UNIQUE,
    sha256 sha256_hash NOT NULL,
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(attempt_id, task_id) REFERENCES task_attempts(id, task_id),
    UNIQUE(attempt_id, ordinal)
);
CREATE INDEX artifacts_task_idx ON artifacts(task_id);
CREATE INDEX artifacts_attempt_task_idx ON artifacts(attempt_id, task_id);

CREATE TABLE outbox_events (
    id opaque_id PRIMARY KEY,
    task_id opaque_id NOT NULL,
    attempt_id opaque_id NOT NULL,
    event_type text NOT NULL CHECK (event_type = 'image.task.requested.v1'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    publish_attempts integer NOT NULL DEFAULT 0 CHECK (publish_attempts >= 0),
    FOREIGN KEY(attempt_id, task_id) REFERENCES task_attempts(id, task_id),
    UNIQUE(attempt_id, event_type),
    CHECK (payload @> jsonb_build_object('event_id', id, 'task_id', task_id,
        'attempt_id', attempt_id, 'event_type', event_type, 'schema_version', 1))
);
CREATE INDEX outbox_pending_idx ON outbox_events(created_at, id) WHERE published_at IS NULL;
CREATE INDEX outbox_attempt_task_idx ON outbox_events(attempt_id, task_id);

CREATE TABLE worker_receipts (
    event_id opaque_id PRIMARY KEY,
    task_id opaque_id NOT NULL,
    attempt_id opaque_id NOT NULL UNIQUE,
    event_type text NOT NULL CHECK (event_type IN ('image.task.completed.v1', 'image.task.failed.v1')),
    payload_sha256 sha256_hash NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    received_at timestamptz NOT NULL DEFAULT now(),
    disposition text NOT NULL DEFAULT 'RECEIVED'
        CHECK (disposition IN ('RECEIVED', 'APPLIED', 'IGNORED', 'REJECTED')),
    processed_at timestamptz,
    FOREIGN KEY(attempt_id, task_id) REFERENCES task_attempts(id, task_id),
    CHECK (payload @> jsonb_build_object('event_id', event_id, 'task_id', task_id,
        'attempt_id', attempt_id, 'event_type', event_type, 'schema_version', 1))
);
CREATE INDEX worker_receipts_attempt_task_idx ON worker_receipts(attempt_id, task_id);

CREATE TABLE audit_events (
    id opaque_id PRIMARY KEY,
    actor_id opaque_id REFERENCES users(id),
    action text NOT NULL CHECK (length(btrim(action)) > 0),
    resource_id opaque_id NOT NULL,
    correlation_id opaque_id NOT NULL,
    details jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(details) = 'object'),
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_actor_idx ON audit_events(actor_id);
CREATE INDEX audit_resource_idx ON audit_events(resource_id, occurred_at);
CREATE INDEX audit_correlation_idx ON audit_events(correlation_id);

-- Triggers report a stable SQLSTATE and never echo user payloads.
CREATE FUNCTION protect_columns() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE column_name text;
BEGIN
    FOREACH column_name IN ARRAY TG_ARGV LOOP
        IF (to_jsonb(OLD) -> column_name) IS DISTINCT FROM (to_jsonb(NEW) -> column_name) THEN
            RAISE EXCEPTION 'Immutable identity or snapshot' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;
CREATE TRIGGER asset_source_immutable BEFORE UPDATE ON assets
    FOR EACH ROW EXECUTE FUNCTION protect_columns(
        'id', 'project_id', 'kind', 'source_asset_id', 'object_key', 'sha256', 'width', 'height', 'created_at');
CREATE TRIGGER task_request_immutable BEFORE UPDATE ON generation_tasks
    FOR EACH ROW EXECUTE FUNCTION protect_columns(
        'id', 'project_id', 'product_asset_id', 'gift_asset_id', 'feature_type', 'created_by',
        'idempotency_key', 'request_sha256', 'request_snapshot_json', 'template_snapshot_json', 'created_at');
CREATE TRIGGER attempt_identity_immutable BEFORE UPDATE ON task_attempts
    FOR EACH ROW EXECUTE FUNCTION protect_columns('id', 'task_id', 'attempt_no', 'created_at');
CREATE TRIGGER outbox_payload_immutable BEFORE UPDATE ON outbox_events
    FOR EACH ROW EXECUTE FUNCTION protect_columns('id', 'task_id', 'attempt_id', 'event_type', 'payload', 'created_at');
CREATE TRIGGER receipt_payload_immutable BEFORE UPDATE ON worker_receipts
    FOR EACH ROW EXECUTE FUNCTION protect_columns(
        'event_id', 'task_id', 'attempt_id', 'event_type', 'payload_sha256', 'payload', 'received_at');

CREATE FUNCTION protect_published_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.published_at IS NOT NULL THEN
        RAISE EXCEPTION 'Published template version is immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER published_version_immutable BEFORE UPDATE OR DELETE ON template_versions
    FOR EACH ROW EXECUTE FUNCTION protect_published_version();

CREATE FUNCTION protect_record() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Immutable record' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER artifact_immutable BEFORE UPDATE OR DELETE ON artifacts
    FOR EACH ROW EXECUTE FUNCTION protect_record();
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION protect_record();

-- Source roles are immutable, so checking the referenced kind cannot race a kind change.
CREATE FUNCTION validate_task_asset_roles() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT kind FROM assets WHERE id = NEW.product_asset_id) <> 'PRODUCT'
       OR (NEW.gift_asset_id IS NOT NULL
           AND (SELECT kind FROM assets WHERE id = NEW.gift_asset_id) <> 'GIFT') THEN
        RAISE EXCEPTION 'Invalid task asset role' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER task_asset_roles BEFORE INSERT ON generation_tasks
    FOR EACH ROW EXECUTE FUNCTION validate_task_asset_roles();

CREATE FUNCTION validate_alpha_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.kind = 'ALPHA' AND (SELECT kind FROM assets WHERE id = NEW.source_asset_id) = 'ALPHA' THEN
        RAISE EXCEPTION 'Alpha must derive from an original asset' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER alpha_source_role BEFORE INSERT ON assets
    FOR EACH ROW EXECUTE FUNCTION validate_alpha_source();

ALTER TABLE templates ADD CONSTRAINT published_template_has_version
    CHECK (state <> 'PUBLISHED' OR published_version_id IS NOT NULL);
CREATE FUNCTION validate_published_pointer() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.published_version_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM template_versions
        WHERE id = NEW.published_version_id AND published_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Template pointer requires a published version' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER published_pointer BEFORE INSERT OR UPDATE ON templates
    FOR EACH ROW EXECUTE FUNCTION validate_published_pointer();
