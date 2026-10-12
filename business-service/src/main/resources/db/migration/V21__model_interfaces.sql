-- ADR-20261012-AB (user decision): models are configured under model interfaces, as in Dify.
-- An interface (OpenRouter, official OpenAI / DeepSeek / Gemini, or an OpenAI-protocol third
-- party) holds the key, address and proxy setting once; its models hold the model id, purpose
-- and the official parameters the admin filled in (blank ones are not sent). Clarity is chosen
-- per task on the generation pages only.
CREATE TABLE model_interfaces (
    id text CONSTRAINT model_interfaces_pkey PRIMARY KEY,
    name text NOT NULL CONSTRAINT model_interfaces_name_check CHECK (
        length(btrim(name)) BETWEEN 1 AND 40),
    -- gemini-compatible is no longer offered but existing ones keep working.
    kind text NOT NULL CONSTRAINT model_interfaces_kind_check CHECK (kind IN (
        'openrouter', 'openai', 'deepseek', 'gemini', 'openai-compatible', 'gemini-compatible')),
    -- Third parties carry their address; Java checks https, or http to a private IPv4 address.
    base_url text CONSTRAINT model_interfaces_base_url_check CHECK (
        (kind IN ('openai-compatible', 'gemini-compatible')) = (base_url IS NOT NULL)
        AND (base_url IS NULL OR (base_url ~ '^https?://[^[:space:]]+$' AND length(base_url) <= 300))),
    -- AES-256-GCM under the external master key, as before; never plaintext.
    api_key_cipher text NOT NULL,
    api_key_mask text NOT NULL,
    use_proxy boolean NOT NULL DEFAULT false,
    -- Created by this migration, one per model; the business service merges those with the same
    -- type, address, proxy setting and key (keys only compare decrypted) on its next start.
    merge_pending boolean NOT NULL DEFAULT false,
    created_by text NOT NULL REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO model_interfaces(
    id, name, kind, base_url, api_key_cipher, api_key_mask, use_proxy, merge_pending,
    created_by, created_at)
SELECT 'mi-' || v.id,
       (CASE v.provider
            WHEN 'openrouter' THEN 'OpenRouter'
            WHEN 'openai' THEN 'OpenAI 官方'
            WHEN 'gemini' THEN 'Gemini 官方'
            WHEN 'openai-compatible' THEN 'OpenAI 协议第三方'
            ELSE 'Gemini 格式第三方' END) || '（' || left(btrim(v.name), 24) || '）',
       v.provider, v.base_url, v.api_key_cipher, v.api_key_mask, v.use_proxy, true,
       v.created_by, v.created_at
FROM provider_config_versions v;

ALTER TABLE provider_config_versions ADD COLUMN interface_id text REFERENCES model_interfaces(id);
UPDATE provider_config_versions SET interface_id = 'mi-' || id;
ALTER TABLE provider_config_versions ALTER COLUMN interface_id SET NOT NULL;
CREATE INDEX provider_config_versions_interface_idx ON provider_config_versions(interface_id);

-- Text models say whether they can look at images; the ones in use already did (ADR-20261009-P).
ALTER TABLE provider_config_versions ADD COLUMN vision boolean NOT NULL DEFAULT false;
UPDATE provider_config_versions SET vision = true WHERE purpose = 'TEXT';
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_vision_check CHECK (
    NOT vision OR purpose = 'TEXT');

-- Parameters: official names with typed values. Clarity is no longer a model setting.
UPDATE provider_config_versions SET parameters = parameters - 'resolution'
WHERE parameters ? 'resolution';
UPDATE provider_config_versions
SET parameters = jsonb_set(parameters, '{temperature}', to_jsonb((parameters ->> 'temperature')::numeric))
WHERE jsonb_typeof(parameters -> 'temperature') = 'string'
  AND parameters ->> 'temperature' ~ '^[0-9]+(\.[0-9]+)?$';
UPDATE provider_config_versions
SET parameters = (parameters - 'temperature')
    || jsonb_build_object('generationConfig.temperature', parameters -> 'temperature')
WHERE provider IN ('gemini', 'gemini-compatible') AND parameters ? 'temperature';
-- What the Worker used to send to text models when nothing was set (temperature 0.7, an output
-- budget of 6000 and, on OpenRouter, light thinking: ADR-20261009-Q, ADR-20261012-Y) becomes
-- explicit, so nothing changes until the admin clears or edits it.
UPDATE provider_config_versions
SET parameters = (CASE provider
        WHEN 'openrouter' THEN '{"temperature": 0.7, "max_tokens": 6000, "reasoning.effort": "low"}'
        WHEN 'openai' THEN '{"temperature": 0.7, "max_completion_tokens": 6000}'
        WHEN 'openai-compatible' THEN '{"temperature": 0.7, "max_tokens": 6000}'
        ELSE '{"generationConfig.temperature": 0.7, "generationConfig.maxOutputTokens": 6000}'
    END)::jsonb || parameters
WHERE purpose = 'TEXT';

-- The type, address, key and proxy setting now live on the interface.
ALTER TABLE provider_config_versions DROP CONSTRAINT provider_config_tag_check;
ALTER TABLE provider_config_versions DROP CONSTRAINT provider_config_model_check;
ALTER TABLE provider_config_versions DROP CONSTRAINT provider_config_base_url_check;
ALTER TABLE provider_config_versions DROP COLUMN provider;
ALTER TABLE provider_config_versions DROP COLUMN base_url;
ALTER TABLE provider_config_versions DROP COLUMN api_key_cipher;
ALTER TABLE provider_config_versions DROP COLUMN api_key_mask;
ALTER TABLE provider_config_versions DROP COLUMN use_proxy;
-- Model id and routing tag shapes; which interface allows which (OpenRouter's vendor/model ids,
-- tags only there) is checked by Java.
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_model_check CHECK (
    model ~ '^[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}$');
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_tag_check CHECK (
    provider_tag IS NULL OR provider_tag ~ '^[a-zA-Z0-9_./-]{1,100}$');

-- A chat message that skipped the look-first analysis because the default text model cannot
-- look at images (shown in the task details).
ALTER TABLE generation_tasks ADD COLUMN analysis_skipped text
    CONSTRAINT generation_tasks_analysis_skipped_check CHECK (
        analysis_skipped IS NULL OR analysis_skipped = 'NO_VISION');
