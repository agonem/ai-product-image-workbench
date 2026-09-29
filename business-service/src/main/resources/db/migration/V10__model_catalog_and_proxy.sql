-- ADR-20260929-C: several models can be enabled at once; operators pick one per task and the
-- admin marks one as the default. Each version row is one selectable model. Rotating a key adds a
-- new row and retires the old one, so tasks keep their exact frozen binding.
ALTER TABLE provider_config_versions ADD COLUMN name text;
ALTER TABLE provider_config_versions ADD COLUMN enabled boolean NOT NULL DEFAULT false;
ALTER TABLE provider_config_versions ADD COLUMN use_proxy boolean NOT NULL DEFAULT false;
ALTER TABLE provider_config_versions ADD COLUMN retired boolean NOT NULL DEFAULT false;

-- Existing rows keep working: the previously active and enabled version stays enabled.
UPDATE provider_config_versions v SET name = v.model,
    enabled = EXISTS (
        SELECT 1 FROM provider_config_state s WHERE s.active_version_id = v.id AND s.enabled),
    retired = NOT EXISTS (
        SELECT 1 FROM provider_config_state s WHERE s.active_version_id = v.id);
ALTER TABLE provider_config_versions ALTER COLUMN name SET NOT NULL;
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_name_check CHECK (
    length(btrim(name)) BETWEEN 1 AND 40);
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_retired_check CHECK (
    NOT (retired AND enabled));

-- The state row now only points at the default model.
ALTER TABLE provider_config_state DROP COLUMN enabled;

-- Outbound proxy for model endpoints, managed in the admin pages; the URL may carry credentials
-- and is stored like API keys (AES-256-GCM under the external master key, masked on read).
CREATE TABLE network_settings (
    id text CONSTRAINT network_settings_pkey PRIMARY KEY
        CONSTRAINT network_settings_singleton CHECK (id = 'proxy'),
    proxy_cipher text NOT NULL,
    proxy_mask text NOT NULL,
    updated_by text NOT NULL REFERENCES users(id),
    updated_at timestamptz NOT NULL DEFAULT now()
);
