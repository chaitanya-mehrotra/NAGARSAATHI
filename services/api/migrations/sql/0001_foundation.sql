CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_subject text NOT NULL UNIQUE,
    display_name text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pilots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL,
    name text NOT NULL,
    timezone text NOT NULL DEFAULT 'Asia/Kolkata',
    geom geometry(MultiPolygon,4326) NOT NULL,
    boundary_version text NOT NULL,
    synthetic boolean NOT NULL DEFAULT false,
    enabled boolean NOT NULL DEFAULT true,
    provenance jsonb NOT NULL DEFAULT '{}',
    UNIQUE (code, boundary_version),
    CHECK (ST_IsValid(geom) AND NOT ST_IsEmpty(geom))
);
CREATE INDEX pilots_geom_gist ON pilots USING gist (geom);

CREATE TABLE areas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pilot_id uuid NOT NULL REFERENCES pilots(id),
    code text NOT NULL,
    display_name text NOT NULL,
    geom geometry(Polygon,4326) NOT NULL,
    boundary_version text NOT NULL,
    provenance jsonb NOT NULL DEFAULT '{}',
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    UNIQUE (pilot_id, code),
    UNIQUE (id, pilot_id),
    CHECK (ST_IsValid(geom) AND NOT ST_IsEmpty(geom)),
    CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE INDEX areas_geom_gist ON areas USING gist (geom);

CREATE TABLE categories (
    code text PRIMARY KEY,
    label text NOT NULL,
    department_tag text NOT NULL,
    default_severity double precision NOT NULL CHECK (default_severity BETWEEN 0 AND 1),
    target_resolution_hours double precision NOT NULL CHECK (target_resolution_hours > 0),
    duplicate_radius_m double precision NOT NULL CHECK (duplicate_radius_m >= 0),
    requires_manual_categorisation boolean NOT NULL DEFAULT false,
    auto_merge_allowed boolean NOT NULL DEFAULT false,
    rule_version text NOT NULL,
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE user_roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    role text NOT NULL CHECK (role IN ('citizen','reviewer','operator','admin')),
    area_id uuid REFERENCES areas(id),
    UNIQUE NULLS NOT DISTINCT (user_id, role, area_id)
);

CREATE TABLE assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_asset_id text NOT NULL,
    category_code text NOT NULL REFERENCES categories(code),
    area_id uuid NOT NULL REFERENCES areas(id),
    geom geography(Point,4326) NOT NULL,
    source text NOT NULL,
    UNIQUE (source, source_asset_id)
);
CREATE INDEX assets_geom_gist ON assets USING gist (geom);

CREATE TABLE poi_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version text NOT NULL UNIQUE,
    coverage geometry(MultiPolygon,4326) NOT NULL,
    source text NOT NULL,
    source_date date NOT NULL,
    synthetic boolean NOT NULL DEFAULT false,
    coverage_complete boolean NOT NULL DEFAULT false,
    coverage_notes text NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    CHECK (ST_IsValid(coverage) AND NOT ST_IsEmpty(coverage))
);
CREATE TABLE pois (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id uuid NOT NULL REFERENCES poi_snapshots(id),
    source_id text NOT NULL,
    name text NOT NULL,
    type text NOT NULL CHECK (type IN ('school','hospital','major_road')),
    geom geography(Geometry,4326) NOT NULL,
    synthetic boolean NOT NULL DEFAULT false,
    UNIQUE (snapshot_id, source_id)
);
CREATE INDEX pois_geom_gist ON pois USING gist (geom);
CREATE INDEX pois_snapshot_type ON pois (snapshot_id, type);

CREATE TABLE priority_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version text NOT NULL UNIQUE,
    weights jsonb NOT NULL,
    category_parameters jsonb NOT NULL,
    hazard_rules jsonb NOT NULL,
    author_id uuid REFERENCES users(id),
    activated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    public_reference text NOT NULL UNIQUE,
    reporter_id uuid NOT NULL REFERENCES users(id),
    parent_submission_id uuid,
    description text NOT NULL,
    language_hint text,
    claimed_category text NOT NULL REFERENCES categories(code),
    canonical_category text REFERENCES categories(code),
    state text NOT NULL DEFAULT 'submitted' CHECK (state IN
        ('submitted','processing','awaiting_review','out_of_scope','rejected','admitted','processing_failed')),
    confirmed_point geography(Point,4326),
    location_accuracy_m double precision CHECK (location_accuracy_m >= 0),
    location_source text,
    address_text text,
    area_id uuid REFERENCES areas(id),
    boundary_version text,
    received_at timestamptz NOT NULL DEFAULT now(),
    captured_at timestamptz,
    content_revision integer NOT NULL DEFAULT 1 CHECK (content_revision >= 1),
    synthetic boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (state <> 'admitted' OR
        (canonical_category IS NOT NULL AND confirmed_point IS NOT NULL AND area_id IS NOT NULL))
);
CREATE INDEX reports_reporter_received ON reports (reporter_id, received_at);
CREATE INDEX reports_area_category_state ON reports (area_id, canonical_category, state);

CREATE TABLE media (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id uuid REFERENCES reports(id),
    owner_id uuid NOT NULL REFERENCES users(id),
    storage_key text NOT NULL UNIQUE,
    original_sha256 text NOT NULL CHECK (original_sha256 ~ '^[0-9a-f]{64}$'),
    derivative_sha256 text CHECK (derivative_sha256 ~ '^[0-9a-f]{64}$'),
    perceptual_hash text,
    mime text NOT NULL,
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    exif_point geography(Point,4326),
    exif_time timestamptz,
    derivative_key text,
    processing_state text NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX media_original_hash ON media (original_sha256);
CREATE INDEX media_report ON media (report_id);

CREATE TABLE validation_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id uuid NOT NULL REFERENCES reports(id),
    media_id uuid NOT NULL REFERENCES media(id),
    report_revision integer NOT NULL CHECK (report_revision >= 1),
    media_sha256 text NOT NULL CHECK (media_sha256 ~ '^[0-9a-f]{64}$'),
    provider text NOT NULL CHECK (provider IN ('fixture','human_review','model')),
    provider_version text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('accepted','needs_review','rejected','error')),
    labels jsonb NOT NULL,
    confidence double precision CHECK (confidence BETWEEN 0 AND 1),
    reviewer_id uuid REFERENCES users(id),
    request_id uuid NOT NULL UNIQUE,
    completed_at timestamptz NOT NULL,
    reason text,
    CHECK (provider <> 'human_review' OR (reviewer_id IS NOT NULL AND confidence IS NULL))
);
CREATE TABLE location_decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id uuid NOT NULL REFERENCES reports(id),
    submitted_point geography(Point,4326),
    approved_point geography(Point,4326),
    method text NOT NULL,
    accuracy_m double precision CHECK (accuracy_m >= 0),
    reviewer_id uuid REFERENCES users(id),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE idempotency_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_id uuid NOT NULL REFERENCES users(id),
    operation text NOT NULL,
    key text NOT NULL,
    request_body_hash text NOT NULL CHECK (request_body_hash ~ '^[0-9a-f]{64}$'),
    response jsonb,
    resource_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    UNIQUE (principal_id, operation, key)
);

CREATE TABLE issues (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    public_reference text NOT NULL UNIQUE,
    pilot_id uuid NOT NULL REFERENCES pilots(id),
    category_code text NOT NULL REFERENCES categories(code),
    geom geography(Point,4326) NOT NULL,
    address_text text,
    area_id uuid NOT NULL,
    boundary_version text NOT NULL,
    asset_id uuid REFERENCES assets(id),
    status text NOT NULL DEFAULT 'open' CHECK (status IN
        ('open','assigned','in_progress','resolution_pending','resolved','reopened','merged')),
    first_accepted_at timestamptz NOT NULL,
    most_recent_accepted_at timestamptz NOT NULL,
    assigned_operator_id uuid REFERENCES users(id),
    assigned_team text,
    hazard_state jsonb NOT NULL DEFAULT '{}',
    current_priority_snapshot_id uuid,
    location_revision integer NOT NULL DEFAULT 1 CHECK (location_revision >= 1),
    recurrence_parent_issue_id uuid REFERENCES issues(id),
    merged_into_issue_id uuid REFERENCES issues(id),
    row_version integer NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    synthetic boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (area_id, pilot_id) REFERENCES areas(id, pilot_id),
    CHECK (first_accepted_at <= most_recent_accepted_at),
    CHECK (recurrence_parent_issue_id IS DISTINCT FROM id),
    CHECK (merged_into_issue_id IS DISTINCT FROM id),
    CHECK ((status = 'merged') = (merged_into_issue_id IS NOT NULL))
);
CREATE INDEX issues_geom_gist ON issues USING gist (geom);
CREATE INDEX issues_queue ON issues (category_code, status, area_id, first_accepted_at, id);
CREATE INDEX issues_active_area ON issues (area_id, category_code)
    WHERE status IN ('open','assigned','in_progress','resolution_pending','reopened');

CREATE TABLE priority_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id uuid NOT NULL REFERENCES issues(id),
    policy_id uuid NOT NULL REFERENCES priority_policies(id),
    issue_revision integer NOT NULL CHECK (issue_revision >= 1),
    as_of timestamptz NOT NULL,
    inputs jsonb NOT NULL,
    factors jsonb NOT NULL,
    contributions jsonb NOT NULL,
    score double precision NOT NULL CHECK (score BETWEEN 0 AND 100),
    band text NOT NULL CHECK (band IN ('critical','high','medium','low')),
    urgency_source text NOT NULL,
    missing_data_flags jsonb NOT NULL,
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    UNIQUE (id, issue_id)
);
ALTER TABLE issues ADD CONSTRAINT issues_priority_snapshot_fk
    FOREIGN KEY (current_priority_snapshot_id, id) REFERENCES priority_snapshots(id, issue_id);

CREATE TABLE issue_report_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id uuid NOT NULL REFERENCES reports(id),
    issue_id uuid NOT NULL REFERENCES issues(id),
    active boolean NOT NULL DEFAULT true,
    method text NOT NULL CHECK (method IN ('new','asset_match','reviewed_duplicate')),
    actor_id uuid REFERENCES users(id),
    rule_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    reason text,
    CHECK (NOT active OR ended_at IS NULL)
);
CREATE UNIQUE INDEX issue_report_one_active ON issue_report_links (report_id) WHERE active;
CREATE INDEX issue_report_issue ON issue_report_links (issue_id);

CREATE TABLE duplicate_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id uuid NOT NULL REFERENCES reports(id),
    issue_id uuid NOT NULL REFERENCES issues(id),
    report_revision integer NOT NULL,
    issue_revision integer NOT NULL,
    features jsonb NOT NULL,
    proposal_score double precision,
    rule_version text NOT NULL,
    state text NOT NULL CHECK (state IN ('proposed','accepted','rejected')),
    reviewer_id uuid REFERENCES users(id),
    decided_at timestamptz,
    reason text,
    UNIQUE (report_id, issue_id, report_revision, issue_revision, rule_version)
);
CREATE TABLE issue_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id uuid NOT NULL REFERENCES issues(id),
    actor_id uuid REFERENCES users(id),
    action text NOT NULL,
    from_state text,
    to_state text,
    reason text,
    evidence jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX issue_events_timeline ON issue_events (issue_id, created_at, id);
CREATE TABLE resolution_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id uuid NOT NULL REFERENCES issues(id),
    repaired_at timestamptz NOT NULL,
    operator_id uuid NOT NULL REFERENCES users(id),
    notes text NOT NULL,
    evidence_media_ids jsonb NOT NULL,
    verifier_id uuid REFERENCES users(id),
    verification_state text NOT NULL CHECK (verification_state IN ('pending','verified','failed')),
    decided_at timestamptz
);
CREATE TABLE audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id uuid REFERENCES users(id),
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    operation text NOT NULL,
    revision integer NOT NULL,
    request_id uuid NOT NULL,
    changes jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type text NOT NULL,
    payload jsonb NOT NULL,
    entity_revision integer NOT NULL CHECK (entity_revision >= 1),
    deduplication_key text NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','completed','failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_run_at timestamptz NOT NULL DEFAULT now(),
    lease_expires_at timestamptz,
    worker_id text,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_ready ON jobs (next_run_at, id) WHERE status IN ('pending','running');

CREATE FUNCTION immutable_event_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'event history is append-only' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER issue_events_immutable BEFORE UPDATE OR DELETE ON issue_events
    FOR EACH ROW EXECUTE FUNCTION immutable_event_history();
CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION immutable_event_history();

CREATE FUNCTION prevent_merge_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.merged_into_issue_id IS NOT NULL AND EXISTS (
        WITH RECURSIVE chain(id, next_id) AS (
            SELECT id, merged_into_issue_id FROM issues WHERE id = NEW.merged_into_issue_id
            UNION
            SELECT i.id, i.merged_into_issue_id FROM issues i JOIN chain c ON i.id = c.next_id
        ) SELECT 1 FROM chain WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'issue merge cycle' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER issues_no_merge_cycle BEFORE INSERT OR UPDATE OF merged_into_issue_id ON issues
    FOR EACH ROW EXECUTE FUNCTION prevent_merge_cycle();

CREATE FUNCTION check_admitted_report_link() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target uuid;
BEGIN
    IF TG_TABLE_NAME = 'reports' THEN
        target := COALESCE(NEW.id, OLD.id);
    ELSE
        target := COALESCE(NEW.report_id, OLD.report_id);
    END IF;
    IF EXISTS (SELECT 1 FROM reports WHERE id = target AND state = 'admitted')
       AND NOT EXISTS (SELECT 1 FROM issue_report_links WHERE report_id = target) THEN
        RAISE EXCEPTION 'admitted report requires an issue link' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM issue_report_links l JOIN reports r ON r.id = l.report_id
        JOIN issues i ON i.id = l.issue_id
        WHERE l.report_id = target AND l.active AND
            (r.state <> 'admitted' OR r.canonical_category <> i.category_code)
    ) THEN
        RAISE EXCEPTION 'active issue link requires an admitted compatible report'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER reports_link_integrity AFTER INSERT OR UPDATE ON reports
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_admitted_report_link();
CREATE CONSTRAINT TRIGGER links_report_integrity AFTER INSERT OR UPDATE OR DELETE ON issue_report_links
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_admitted_report_link();
