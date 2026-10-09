-- ADR-20261009-R (user decision): 参考图 is its own material category next to 商品图 and
-- 赠品图, and any original may be used in any slot (the product slot may take a 赠品图, and so
-- on): the category only organises the library. ALPHA rows stay for historical v1 tasks.
ALTER TABLE assets DROP CONSTRAINT assets_kind_check;
ALTER TABLE assets ADD CONSTRAINT assets_kind_check
    CHECK (kind IN ('PRODUCT', 'GIFT', 'REFERENCE', 'ALPHA'));

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
