-- ADR-20261008-L. Agents for conversational generation and the text model that rewrites a brief.

-- Public agents (owner_id NULL) are kept by admins; personal ones belong to one account. Tasks
-- freeze the settings they used, so editing or deleting an agent never changes history.
CREATE TABLE agents (
    id opaque_id PRIMARY KEY,
    owner_id opaque_id REFERENCES users(id),
    name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 20),
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 60),
    instructions text NOT NULL CHECK (length(btrim(instructions)) BETWEEN 1 AND 2000),
    avatar_key text,
    created_by opaque_id REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX agents_owner_idx ON agents(owner_id, created_at);

INSERT INTO agents(id, name, description, instructions, created_at) VALUES
    ('agent-gloria', 'Gloria', '电商主图设计师，构图干净、主体突出',
     '你是资深母婴电商主图设计师。画面干净明亮，商品是绝对主角，位置醒目、比例饱满；背景简洁有质感，配色柔和统一；预留文字区域时让商品避开。',
     now() - interval '3 seconds'),
    ('agent-lumi', 'Lumi', '生活场景摄影师，擅长温馨家居氛围',
     '你是母婴生活方式摄影师。把商品放进真实、温馨的家居场景（婴儿房、卧室、客厅、浴室），使用柔和的自然光和浅景深，道具少而精，突出使用场景和安心感。',
     now() - interval '2 seconds'),
    ('agent-kira', 'Kira', '创意视觉策划，节日与促销氛围',
     '你是电商创意视觉策划。擅长节日、季节和促销主题，用有趣的道具、色块和光影营造氛围，画面有记忆点但不喧宾夺主，商品仍清晰完整。',
     now() - interval '1 second');

-- Model purpose: IMAGE models generate pictures; TEXT models rewrite briefs. Each has its own
-- default (provider_config_state rows 'active' and 'text').
ALTER TABLE provider_config_versions ADD COLUMN purpose text NOT NULL DEFAULT 'IMAGE'
    CONSTRAINT provider_config_purpose_check CHECK (purpose IN ('IMAGE', 'TEXT'));
ALTER TABLE provider_config_state DROP CONSTRAINT provider_config_state_singleton;
ALTER TABLE provider_config_state ADD CONSTRAINT provider_config_state_singleton CHECK (
    provider IN ('active', 'text'));

ALTER TABLE generation_tasks
    ADD COLUMN text_config_version text REFERENCES provider_config_versions(id);
