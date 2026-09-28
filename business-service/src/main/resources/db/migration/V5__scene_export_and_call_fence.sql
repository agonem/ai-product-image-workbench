-- v1/v2 snapshots remain immutable; only new v3 requests use local export semantics.
ALTER TABLE outbox_events DROP CONSTRAINT outbox_events_event_type_check;
ALTER TABLE outbox_events DROP CONSTRAINT outbox_events_check;
ALTER TABLE outbox_events ADD CONSTRAINT outbox_events_event_type_check
 CHECK (event_type IN ('image.task.requested.v1','image.task.requested.v2','image.task.requested.v3'));
ALTER TABLE outbox_events ADD CONSTRAINT outbox_events_check
 CHECK (payload @> jsonb_build_object('event_id',id,'task_id',task_id,'attempt_id',attempt_id,
 'event_type',event_type,'schema_version',right(event_type,1)::integer));
ALTER TABLE worker_receipts DROP CONSTRAINT worker_receipts_event_type_check;
ALTER TABLE worker_receipts DROP CONSTRAINT worker_receipts_check;
ALTER TABLE worker_receipts ADD CONSTRAINT worker_receipts_event_type_check
 CHECK (event_type IN ('image.task.completed.v1','image.task.failed.v1','image.task.completed.v2',
 'image.task.failed.v2','image.task.completed.v3','image.task.failed.v3'));
ALTER TABLE worker_receipts ADD CONSTRAINT worker_receipts_check
 CHECK (payload @> jsonb_build_object('event_id',event_id,'task_id',task_id,'attempt_id',attempt_id,
 'event_type',event_type,'schema_version',right(event_type,1)::integer));
CREATE TABLE generation_call_fences (
 attempt_id varchar(64) NOT NULL REFERENCES task_attempts(id),
 ordinal integer NOT NULL CHECK (ordinal >= 0),
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(attempt_id,ordinal)
);
