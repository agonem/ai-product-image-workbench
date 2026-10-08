-- ADR-20261008-L follow-up: an OpenRouter text model may leave provider routing to OpenRouter
-- (only the brief is sent, never an image). OpenRouter image models still need their tag.
ALTER TABLE provider_config_versions DROP CONSTRAINT provider_config_tag_check;
ALTER TABLE provider_config_versions ADD CONSTRAINT provider_config_tag_check CHECK (
    (provider = 'openrouter' OR provider_tag IS NULL)
    AND (provider <> 'openrouter' OR purpose = 'TEXT' OR provider_tag IS NOT NULL)
    AND (provider_tag IS NULL OR provider_tag ~ '^[a-zA-Z0-9_./-]{1,100}$'));
