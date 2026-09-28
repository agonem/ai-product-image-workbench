-- Provider configuration versions are append-only; the state row selects what new tasks bind.
-- The api_key_cipher column holds AES-256-GCM output under an external master key, never plaintext.
CREATE TABLE provider_config_versions (
    id text CONSTRAINT provider_config_versions_pkey PRIMARY KEY,
    provider text NOT NULL CONSTRAINT provider_config_provider_check CHECK (provider = 'openrouter'),
    model text NOT NULL CONSTRAINT provider_config_model_check CHECK (model ~ '[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+'),
    provider_tag text NOT NULL CONSTRAINT provider_config_tag_check CHECK (provider_tag ~ '[a-zA-Z0-9_./-]{1,100}'),
    api_key_cipher text NOT NULL,
    api_key_mask text NOT NULL,
    created_by text NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE provider_config_state (
    provider text CONSTRAINT provider_config_state_pkey PRIMARY KEY CHECK (provider = 'openrouter'),
    active_version_id text REFERENCES provider_config_versions(id),
    enabled boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE generation_tasks ADD COLUMN provider_config_version text REFERENCES provider_config_versions(id);

CREATE TRIGGER provider_config_immutable BEFORE UPDATE ON provider_config_versions
    FOR EACH ROW EXECUTE FUNCTION protect_columns(
        'id', 'provider', 'model', 'provider_tag', 'api_key_cipher', 'api_key_mask', 'created_by', 'created_at');
CREATE TRIGGER task_provider_config_immutable BEFORE UPDATE ON generation_tasks
    FOR EACH ROW EXECUTE FUNCTION protect_columns('provider_config_version');
