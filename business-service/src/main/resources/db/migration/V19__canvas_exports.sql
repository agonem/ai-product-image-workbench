-- ADR-20261010-W. Canvas phase 3: a board of the conversation canvas composed into one picture
-- by the Worker ("画布导出", no model call). Such a task belongs to its conversation and has no
-- product image of its own; every other task still has one.
ALTER TABLE generation_tasks DROP CONSTRAINT generation_tasks_feature_type_check;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_feature_type_check
    CHECK (feature_type IN ('GIFT', 'SCENE', 'SELLING_POINT', 'CUSTOM', 'COMPOSE'));

ALTER TABLE generation_tasks ALTER COLUMN product_asset_id DROP NOT NULL;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_product_check
    CHECK ((feature_type = 'COMPOSE') = (product_asset_id IS NULL));

ALTER TABLE generation_tasks DROP CONSTRAINT generation_tasks_conversation_check;
ALTER TABLE generation_tasks ADD CONSTRAINT generation_tasks_conversation_check
    CHECK (conversation_id IS NULL OR feature_type IN ('CUSTOM', 'COMPOSE'));

CREATE OR REPLACE FUNCTION validate_task_asset_roles() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.product_asset_id IS NOT NULL
        AND (SELECT kind FROM assets WHERE id = NEW.product_asset_id)
            NOT IN ('PRODUCT', 'GIFT', 'REFERENCE'))
       OR (NEW.gift_asset_id IS NOT NULL
           AND (SELECT kind FROM assets WHERE id = NEW.gift_asset_id)
               NOT IN ('PRODUCT', 'GIFT', 'REFERENCE')) THEN
        RAISE EXCEPTION 'Invalid task asset role' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
