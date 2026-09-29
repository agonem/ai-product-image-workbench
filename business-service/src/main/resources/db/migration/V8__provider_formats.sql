-- ADR-20260929-B: besides OpenRouter, official OpenAI / Gemini APIs and third-party endpoints in
-- the OpenAI or Gemini format. Versions stay append-only; existing OpenRouter rows are unchanged.
ALTER TABLE provider_config_versions DROP CONSTRAINT provider_config_provider_check;
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_provider_check CHECK (
    provider IN ('openrouter', 'openai', 'gemini', 'openai-compatible', 'gemini-compatible'));

-- Official model names have no vendor prefix (gpt-image-2, gemini-2.5-flash-image).
ALTER TABLE provider_config_versions DROP CONSTRAINT provider_config_model_check;
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_model_check CHECK (
    model ~ '^[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}$'
    AND (provider <> 'openrouter' OR model ~ '^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+$'));

-- The routing tag only exists for OpenRouter.
ALTER TABLE provider_config_versions ALTER COLUMN provider_tag DROP NOT NULL;
ALTER TABLE provider_config_versions DROP CONSTRAINT provider_config_tag_check;
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_tag_check CHECK (
    (provider = 'openrouter') = (provider_tag IS NOT NULL)
    AND (provider_tag IS NULL OR provider_tag ~ '^[a-zA-Z0-9_./-]{1,100}$'));

-- Third-party endpoints carry their base URL; official ones use the vendor's fixed address.
-- Java validates the scheme and host (https, or http to a private IPv4 address only).
ALTER TABLE provider_config_versions ADD COLUMN base_url text;
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_base_url_check CHECK (
    (provider IN ('openai-compatible', 'gemini-compatible')) = (base_url IS NOT NULL)
    AND (base_url IS NULL OR (base_url ~ '^https?://[^[:space:]]+$' AND length(base_url) <= 300)));

DROP TRIGGER provider_config_immutable ON provider_config_versions;
CREATE TRIGGER provider_config_immutable BEFORE UPDATE ON provider_config_versions
    FOR EACH ROW EXECUTE FUNCTION protect_columns(
        'id', 'provider', 'model', 'provider_tag', 'base_url', 'api_key_cipher', 'api_key_mask',
        'created_by', 'created_at');

-- One active configuration for the whole deployment, whatever its provider type.
ALTER TABLE provider_config_state DROP CONSTRAINT provider_config_state_provider_check;
UPDATE provider_config_state SET provider = 'active';
ALTER TABLE provider_config_state ADD CONSTRAINT provider_config_state_singleton CHECK (
    provider = 'active');
