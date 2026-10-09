-- ADR-20261009-Q (user decision): models are edited in place and can be deleted. Submitted
-- tasks use the edited settings; unfinished tasks of a deleted model move to the default model,
-- finished ones keep their receipts but lose the link. Per-model parameters (quality,
-- resolution, temperature) are stored with the model.
ALTER TABLE provider_config_versions ADD COLUMN parameters jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_parameters_check
    CHECK (jsonb_typeof(parameters) = 'object');

DROP TRIGGER provider_config_immutable ON provider_config_versions;
CREATE TRIGGER provider_config_immutable BEFORE UPDATE ON provider_config_versions
    FOR EACH ROW EXECUTE FUNCTION protect_columns('id', 'purpose', 'created_by', 'created_at');

DROP TRIGGER task_provider_config_immutable ON generation_tasks;
ALTER TABLE generation_tasks DROP CONSTRAINT generation_tasks_provider_config_version_fkey;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_provider_config_version_fkey
    FOREIGN KEY (provider_config_version) REFERENCES provider_config_versions(id) ON DELETE SET NULL;
ALTER TABLE generation_tasks DROP CONSTRAINT generation_tasks_text_config_version_fkey;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_text_config_version_fkey
    FOREIGN KEY (text_config_version) REFERENCES provider_config_versions(id) ON DELETE SET NULL;
