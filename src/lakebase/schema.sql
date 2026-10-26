-- Lakebase (Postgres) operational state for the metrology review / approval app.
-- Holds transactional metadata only; images stay in UC Volumes and results in Delta.

CREATE SCHEMA IF NOT EXISTS fabs;
SET search_path TO fabs;

-- Who can do what. Identity comes from Databricks SSO (X-Forwarded-Email);
-- this table only maps identities to application roles.
CREATE TABLE IF NOT EXISTS app_users (
    email         TEXT PRIMARY KEY,
    display_name  TEXT,
    roles         TEXT[] NOT NULL DEFAULT ARRAY['viewer'],   -- viewer | submitter | reviewer | approver | admin
    user_type     TEXT NOT NULL DEFAULT 'employee' CHECK (user_type IN ('employee', 'external')),
    site          TEXT,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reason_codes (
    code         TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    applies_to   TEXT NOT NULL CHECK (applies_to IN ('review', 'approval', 'any'))
);

-- A user-initiated processing request (upload and/or reprocess).
CREATE TABLE IF NOT EXISTS submissions (
    submission_id  TEXT PRIMARY KEY,
    submitted_by   TEXT NOT NULL,
    submitted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    description    TEXT,
    experiment_id  TEXT,
    lot_id         TEXT,
    file_count     INT NOT NULL DEFAULT 0,
    job_run_id     BIGINT,
    status         TEXT NOT NULL DEFAULT 'SUBMITTED'
                   CHECK (status IN ('SUBMITTED', 'RUNNING', 'PROCESSED', 'FAILED')),
    status_detail  TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per processed image: current review state + snapshot of the model result.
--   PENDING_REVIEW -> PENDING_APPROVAL (reviewer verdict GOOD or BAD)
--   PENDING_REVIEW -> NEEDS_REWORK      (reviewer)
--   PENDING_APPROVAL -> APPROVED_GOOD | REJECTED_BAD   (approver confirms verdict)
--   PENDING_APPROVAL -> PENDING_REVIEW  (approver declines verdict)
--   NEEDS_REWORK -> PENDING_REVIEW      (image reprocessed)
CREATE TABLE IF NOT EXISTS review_items (
    image_id           TEXT PRIMARY KEY,
    submission_id      TEXT REFERENCES submissions (submission_id),
    submitted_by       TEXT,
    experiment_id      TEXT,
    lot_id             TEXT,
    wafer_id           TEXT,
    tool_id            TEXT,
    capture_ts         TIMESTAMPTZ,
    predicted_class    TEXT,
    class_confidence   DOUBLE PRECISION,
    mean_cd_nm         DOUBLE PRECISION,
    cd_spec_status     TEXT,
    disposition        TEXT,              -- model disposition: PASS | FLAGGED
    priority           SMALLINT NOT NULL DEFAULT 2,   -- 1 = high
    overlay_path       TEXT,
    model_version      TEXT,
    state              TEXT NOT NULL DEFAULT 'PENDING_REVIEW'
                       CHECK (state IN ('PENDING_REVIEW', 'PENDING_APPROVAL', 'APPROVED_GOOD',
                                        'REJECTED_BAD', 'NEEDS_REWORK')),
    reviewer_verdict   TEXT CHECK (reviewer_verdict IN ('GOOD', 'BAD')),
    assigned_reviewer  TEXT,
    reviewed_by        TEXT,
    reviewed_at        TIMESTAMPTZ,
    approved_by        TEXT,
    approved_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS review_items_state_idx ON review_items (state, priority, capture_ts);
CREATE INDEX IF NOT EXISTS review_items_lot_idx ON review_items (experiment_id, lot_id);

-- Immutable history of every review-workflow action (append-only).
CREATE TABLE IF NOT EXISTS review_actions (
    action_id     BIGSERIAL PRIMARY KEY,
    image_id      TEXT NOT NULL REFERENCES review_items (image_id),
    actor_email   TEXT NOT NULL,
    acting_role   TEXT NOT NULL,
    action        TEXT NOT NULL CHECK (action IN ('REVIEW_GOOD', 'REVIEW_BAD', 'NEEDS_REWORK', 'APPROVE',
                                                  'DECLINE', 'COMMENT', 'ASSIGN', 'PUBLISHED', 'REPROCESSED')),
    from_state    TEXT,
    to_state      TEXT,
    reason_code   TEXT REFERENCES reason_codes (code),
    comment       TEXT,
    sod_override  BOOLEAN NOT NULL DEFAULT FALSE,   -- separation-of-duties relaxed (demo mode)
    action_ts     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS review_actions_image_idx ON review_actions (image_id, action_ts);

-- Application access and material actions (append-only).
CREATE TABLE IF NOT EXISTS audit_events (
    event_id     BIGSERIAL PRIMARY KEY,
    event_ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_email  TEXT NOT NULL,
    event_type   TEXT NOT NULL,   -- APP_ACCESS | PAGE_VIEW | UPLOAD | JOB_SUBMIT | AI_SUMMARY | ROLE_CHANGE | ...
    object_type  TEXT,
    object_id    TEXT,
    details      JSONB
);
CREATE INDEX IF NOT EXISTS audit_events_ts_idx ON audit_events (event_ts);
CREATE INDEX IF NOT EXISTS audit_events_actor_idx ON audit_events (actor_email, event_ts);

-- LLM-generated review summaries, kept for traceability of AI assistance.
CREATE TABLE IF NOT EXISTS ai_summaries (
    summary_id         BIGSERIAL PRIMARY KEY,
    image_id           TEXT NOT NULL REFERENCES review_items (image_id),
    model_endpoint     TEXT NOT NULL,
    summary            TEXT NOT NULL,
    prompt_tokens      INT,
    completion_tokens  INT,
    created_by         TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit tables are append-only for the application role.
CREATE OR REPLACE FUNCTION fabs.block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS review_actions_append_only ON review_actions;
CREATE TRIGGER review_actions_append_only BEFORE UPDATE OR DELETE ON review_actions
    FOR EACH ROW EXECUTE FUNCTION fabs.block_mutation();
DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events;
CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION fabs.block_mutation();

INSERT INTO reason_codes (code, description, applies_to) VALUES
    ('OK_IN_SPEC',        'Measurements within specification, no visible defect', 'review'),
    ('CD_HIGH',           'Critical dimension above USL',                         'review'),
    ('CD_LOW',            'Critical dimension below LSL',                         'review'),
    ('MISSING_CONTACT',   'One or more contacts not opened',                      'review'),
    ('BRIDGE',            'Adjacent contacts merged / bridged',                   'review'),
    ('PARTICLE',          'Particle or contamination in field',                   'review'),
    ('IMAGE_QUALITY',     'Focus, charging or noise prevents a reliable call',    'review'),
    ('MODEL_MISS',        'Model result disagrees with visual inspection',        'review'),
    ('VERDICT_CONFIRMED', 'Approver confirms reviewer verdict',                   'approval'),
    ('NEEDS_SECOND_LOOK', 'Approver requests another review',                     'approval'),
    ('WRONG_REASON',      'Verdict right but reason code wrong',                  'approval'),
    ('OTHER',             'Other (see comment)',                                  'any')
ON CONFLICT (code) DO NOTHING;

-- Lakebase change data feed -> Delta (UC schema fabs_review) needs full row images.
ALTER TABLE app_users      REPLICA IDENTITY FULL;
ALTER TABLE reason_codes   REPLICA IDENTITY FULL;
ALTER TABLE submissions    REPLICA IDENTITY FULL;
ALTER TABLE review_items   REPLICA IDENTITY FULL;
ALTER TABLE review_actions REPLICA IDENTITY FULL;
ALTER TABLE audit_events   REPLICA IDENTITY FULL;
ALTER TABLE ai_summaries   REPLICA IDENTITY FULL;
