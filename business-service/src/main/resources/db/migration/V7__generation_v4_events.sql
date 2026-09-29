-- v4 whole-image generation (ADR-20260929): allow its request/receipt envelopes.
-- Existing v1-v3 rows and constraints on payload identity are kept unchanged in meaning.
ALTER TABLE outbox_events DROP CONSTRAINT outbox_events_event_type_check;
ALTER TABLE outbox_events ADD CONSTRAINT outbox_events_event_type_check
 CHECK (event_type IN ('image.task.requested.v1','image.task.requested.v2',
 'image.task.requested.v3','image.task.requested.v4'));
ALTER TABLE worker_receipts DROP CONSTRAINT worker_receipts_event_type_check;
ALTER TABLE worker_receipts ADD CONSTRAINT worker_receipts_event_type_check
 CHECK (event_type IN ('image.task.completed.v1','image.task.failed.v1','image.task.completed.v2',
 'image.task.failed.v2','image.task.completed.v3','image.task.failed.v3',
 'image.task.completed.v4','image.task.failed.v4'));
