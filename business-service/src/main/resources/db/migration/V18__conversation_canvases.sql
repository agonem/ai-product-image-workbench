-- ADR-20261010-V. Canvas phase 2: where the owner placed each picture of a conversation on its
-- canvas (positions, copies, pictures taken off the canvas). Only placement is kept here; the
-- tasks and images are unaffected, and the layout goes with its conversation.
CREATE TABLE conversation_canvases (
    conversation_id opaque_id PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    layout jsonb NOT NULL CHECK (jsonb_typeof(layout) = 'object'),
    version integer NOT NULL CHECK (version >= 1),
    updated_at timestamptz NOT NULL DEFAULT now()
);
