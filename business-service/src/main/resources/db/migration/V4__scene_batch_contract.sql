-- Additive v2 scene envelopes. Historical v1 rows and frozen snapshots stay unchanged.
ALTER TABLE outbox_events DROP CONSTRAINT outbox_events_event_type_check;
ALTER TABLE outbox_events DROP CONSTRAINT outbox_events_check;
ALTER TABLE outbox_events ADD CONSTRAINT outbox_events_event_type_check
    CHECK (event_type IN ('image.task.requested.v1', 'image.task.requested.v2'));
ALTER TABLE outbox_events ADD CONSTRAINT outbox_events_check
    CHECK (payload @> jsonb_build_object('event_id', id, 'task_id', task_id,
        'attempt_id', attempt_id, 'event_type', event_type,
        'schema_version', CASE WHEN event_type LIKE '%.v2' THEN 2 ELSE 1 END));

ALTER TABLE worker_receipts DROP CONSTRAINT worker_receipts_event_type_check;
ALTER TABLE worker_receipts DROP CONSTRAINT worker_receipts_check;
ALTER TABLE worker_receipts ADD CONSTRAINT worker_receipts_event_type_check
    CHECK (event_type IN ('image.task.completed.v1', 'image.task.failed.v1',
                         'image.task.completed.v2', 'image.task.failed.v2'));
ALTER TABLE worker_receipts ADD CONSTRAINT worker_receipts_check
    CHECK (payload @> jsonb_build_object('event_id', event_id, 'task_id', task_id,
        'attempt_id', attempt_id, 'event_type', event_type,
        'schema_version', CASE WHEN event_type LIKE '%.v2' THEN 2 ELSE 1 END));
