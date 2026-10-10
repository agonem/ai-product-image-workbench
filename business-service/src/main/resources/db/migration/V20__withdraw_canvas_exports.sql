-- ADR-20261010-X (user decision): canvas phase 3 (ADR-20261010-W) is withdrawn. V19 was already
-- applied on the test server, so it stays in the history and this migration takes the schema
-- back to the V18 state: every task has a product image again, no "画布导出" task type, and
-- only conversation messages (CUSTOM) belong to a conversation. No COMPOSE task exists.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM generation_tasks WHERE feature_type = 'COMPOSE') THEN
        RAISE EXCEPTION 'Canvas exports exist; withdraw them before this migration';
    END IF;
END;
$$;

ALTER TABLE generation_tasks DROP CONSTRAINT generation_tasks_product_check;
ALTER TABLE generation_tasks ALTER COLUMN product_asset_id SET NOT NULL;

ALTER TABLE generation_tasks DROP CONSTRAINT generation_tasks_feature_type_check;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_feature_type_check
    CHECK (feature_type IN ('GIFT', 'SCENE', 'SELLING_POINT', 'CUSTOM'));

ALTER TABLE generation_tasks DROP CONSTRAINT generation_tasks_conversation_check;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_conversation_check
    CHECK (conversation_id IS NULL OR feature_type = 'CUSTOM');

CREATE OR REPLACE FUNCTION validate_task_asset_roles() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT kind FROM assets WHERE id = NEW.product_asset_id)
           NOT IN ('PRODUCT', 'GIFT', 'REFERENCE')
       OR (NEW.gift_asset_id IS NOT NULL
           AND (SELECT kind FROM assets WHERE id = NEW.gift_asset_id)
               NOT IN ('PRODUCT', 'GIFT', 'REFERENCE')) THEN
        RAISE EXCEPTION 'Invalid task asset role' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

-- Canvas layouts keep only results and message cards (ADR-20261010-V); the withdrawn text boxes,
-- library pictures and boards are taken off. The pictures themselves stay in the library.
UPDATE conversation_canvases c
SET layout = jsonb_set(
        c.layout,
        '{items}',
        COALESCE(
            (SELECT jsonb_agg(item ORDER BY position)
             FROM jsonb_array_elements(c.layout -> 'items') WITH ORDINALITY AS e(item, position)
             WHERE item ->> 'artifact_id' IS NOT NULL OR item ->> 'task_id' IS NOT NULL),
            '[]'::jsonb)),
    version = c.version + 1,
    updated_at = now()
WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(c.layout -> 'items') AS e(item)
    WHERE NOT (item ->> 'artifact_id' IS NOT NULL OR item ->> 'task_id' IS NOT NULL));
