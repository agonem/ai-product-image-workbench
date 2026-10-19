-- ADR-20261019-AD (user decision; no environment other than the test server holds data): remove
-- what no longer runs and give the model tables their plain names. Nothing is removed unless it
-- is really empty or unused; otherwise the whole migration stops here.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM generation_tasks
               WHERE coalesce((worker_snapshot_json ->> 'schema_version')::int, 0) <> 4) THEN
        RAISE EXCEPTION 'Tasks in the retired v1-v3 formats exist';
    END IF;
    IF EXISTS (SELECT 1 FROM assets WHERE kind = 'ALPHA')
       OR EXISTS (SELECT 1 FROM artifacts WHERE kind = 'ALPHA') THEN
        RAISE EXCEPTION 'Cutout masks exist';
    END IF;
    IF EXISTS (SELECT 1 FROM templates) OR EXISTS (SELECT 1 FROM template_versions)
       OR EXISTS (SELECT 1 FROM output_presets) THEN
        RAISE EXCEPTION 'Retired templates or output presets exist';
    END IF;
    IF EXISTS (SELECT 1 FROM users WHERE role IS NOT NULL) THEN
        RAISE EXCEPTION 'users.role is in use; roles live in local_credentials';
    END IF;
    IF EXISTS (SELECT 1 FROM provider_config_versions WHERE retired) THEN
        RAISE EXCEPTION 'Retired models exist';
    END IF;
END;
$$;

-- v1 templates and output presets (the preset catalogue replaced them).
DROP TABLE templates, template_versions;
DROP FUNCTION validate_published_pointer();
DROP FUNCTION protect_published_version();
DROP TABLE output_presets;

-- Cutout masks (cancelled by ADR-20260929).
DROP TRIGGER alpha_source_role ON assets;
DROP FUNCTION validate_alpha_source();
DROP TRIGGER asset_source_immutable ON assets;
ALTER TABLE assets DROP CONSTRAINT assets_check;
ALTER TABLE assets DROP CONSTRAINT assets_check1;
ALTER TABLE assets DROP CONSTRAINT assets_source_asset_id_project_id_fkey;
DROP INDEX assets_source_idx;
ALTER TABLE assets DROP COLUMN source_asset_id;
ALTER TABLE assets DROP COLUMN review_status;
ALTER TABLE assets DROP CONSTRAINT assets_kind_check;
ALTER TABLE assets ADD CONSTRAINT assets_kind_check CHECK (kind IN ('PRODUCT', 'GIFT', 'REFERENCE'));
CREATE TRIGGER asset_source_immutable BEFORE UPDATE ON assets
    FOR EACH ROW EXECUTE FUNCTION protect_columns(
        'id', 'project_id', 'kind', 'object_key', 'sha256', 'width', 'height', 'created_at',
        'source_artifact_id');
-- COMPOSITE: the finished picture; BACKGROUND: the model's own output, kept for re-typesetting.
ALTER TABLE artifacts DROP CONSTRAINT artifacts_kind_check;
ALTER TABLE artifacts ADD CONSTRAINT artifacts_kind_check CHECK (kind IN ('COMPOSITE', 'BACKGROUND'));

-- Roles live in local_credentials only.
ALTER TABLE users DROP COLUMN role;

-- One-off flags of earlier model storage. Interfaces V21 left unmerged stay separate; each still
-- holds its own model's key.
ALTER TABLE provider_config_versions DROP CONSTRAINT provider_config_retired_check;
ALTER TABLE provider_config_versions DROP COLUMN retired;
ALTER TABLE model_interfaces DROP COLUMN merge_pending;

-- Plain names: models and the default model per purpose.
ALTER TABLE provider_config_versions RENAME TO models;
ALTER TABLE models RENAME CONSTRAINT provider_config_versions_pkey TO models_pkey;
ALTER TABLE models RENAME CONSTRAINT provider_config_model_check TO models_model_check;
ALTER TABLE models RENAME CONSTRAINT provider_config_name_check TO models_name_check;
ALTER TABLE models RENAME CONSTRAINT provider_config_parameters_check TO models_parameters_check;
ALTER TABLE models RENAME CONSTRAINT provider_config_purpose_check TO models_purpose_check;
ALTER TABLE models RENAME CONSTRAINT provider_config_tag_check TO models_tag_check;
ALTER TABLE models RENAME CONSTRAINT provider_config_vision_check TO models_vision_check;
ALTER TABLE models RENAME CONSTRAINT provider_config_versions_created_by_fkey TO models_created_by_fkey;
ALTER TABLE models RENAME CONSTRAINT provider_config_versions_interface_id_fkey TO models_interface_id_fkey;
ALTER INDEX provider_config_versions_interface_idx RENAME TO models_interface_idx;
ALTER TRIGGER provider_config_immutable ON models RENAME TO models_immutable;

ALTER TABLE provider_config_state RENAME TO default_models;
ALTER TABLE default_models DROP CONSTRAINT provider_config_state_singleton;
UPDATE default_models SET provider = CASE provider WHEN 'active' THEN 'IMAGE' ELSE 'TEXT' END;
ALTER TABLE default_models RENAME COLUMN provider TO purpose;
ALTER TABLE default_models RENAME COLUMN active_version_id TO model_id;
ALTER TABLE default_models RENAME CONSTRAINT provider_config_state_pkey TO default_models_pkey;
ALTER TABLE default_models RENAME CONSTRAINT provider_config_state_active_version_id_fkey
    TO default_models_model_id_fkey;
ALTER TABLE default_models ADD CONSTRAINT default_models_purpose_check
    CHECK (purpose IN ('IMAGE', 'TEXT'));

ALTER TABLE generation_tasks RENAME COLUMN provider_config_version TO image_model_id;
ALTER TABLE generation_tasks RENAME COLUMN text_config_version TO text_model_id;
ALTER TABLE generation_tasks RENAME CONSTRAINT generation_tasks_provider_config_version_fkey
    TO generation_tasks_image_model_id_fkey;
ALTER TABLE generation_tasks RENAME CONSTRAINT generation_tasks_text_config_version_fkey
    TO generation_tasks_text_model_id_fkey;
