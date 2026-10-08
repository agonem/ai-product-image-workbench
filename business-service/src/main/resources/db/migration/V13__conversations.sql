-- ADR-20261008-I. Conversational generation ("对话生图"): a conversation groups the owner's
-- custom-prompt tasks in one project. Each message is an ordinary v4 task (feature CUSTOM) with
-- its prompt, references and results; deleting a conversation keeps its images.
CREATE TABLE conversations (
    id opaque_id PRIMARY KEY,
    project_id opaque_id NOT NULL REFERENCES projects(id),
    title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 40),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_project_idx ON conversations(project_id, updated_at DESC);

ALTER TABLE generation_tasks DROP CONSTRAINT generation_tasks_feature_type_check;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_feature_type_check
    CHECK (feature_type IN ('GIFT', 'SCENE', 'SELLING_POINT', 'CUSTOM'));
ALTER TABLE generation_tasks
    ADD COLUMN conversation_id opaque_id REFERENCES conversations(id) ON DELETE SET NULL;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_conversation_check
    CHECK (conversation_id IS NULL OR feature_type = 'CUSTOM');
CREATE INDEX generation_tasks_conversation_idx ON generation_tasks(conversation_id, created_at);
