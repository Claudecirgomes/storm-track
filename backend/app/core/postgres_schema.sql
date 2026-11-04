-- PostgreSQL 14+ / Supabase schema for the local-first StormTrack backend.
-- Run through backend initialization inside its transaction, using the dedicated
-- backend database identity. This file creates only the private stormtrack schema.
-- IDs, timestamps and serialized JSON stay TEXT to preserve SQLite payloads and
-- application behavior. REAL maps to DOUBLE PRECISION; enabled stays INTEGER.
-- COLLATE "C" preserves binary comparison for text. SQLite NOCASE only folds
-- ASCII letters, so username/provider uniqueness uses ascii_nocase below.

CREATE SCHEMA IF NOT EXISTS stormtrack;
REVOKE ALL ON SCHEMA stormtrack FROM PUBLIC;

CREATE OR REPLACE FUNCTION stormtrack.ascii_nocase(value TEXT)
RETURNS TEXT
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
SET search_path = pg_catalog
AS $function$
    SELECT pg_catalog.translate(value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz');
$function$;
CREATE TABLE IF NOT EXISTS stormtrack.user_accounts (
    id TEXT COLLATE "C" PRIMARY KEY,
    username TEXT COLLATE "C" NOT NULL,
    password_hash TEXT COLLATE "C" NOT NULL,
    role TEXT COLLATE "C" NOT NULL CHECK (role IN ('ADMIN', 'USER')),
    status TEXT COLLATE "C" NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at TEXT COLLATE "C" NOT NULL,
    updated_at TEXT COLLATE "C" NOT NULL,
    deleted_at TEXT COLLATE "C"
);
CREATE UNIQUE INDEX IF NOT EXISTS one_admin_account
    ON stormtrack.user_accounts(role) WHERE role = 'ADMIN';

CREATE TABLE IF NOT EXISTS stormtrack.sessions (
    id TEXT COLLATE "C" PRIMARY KEY,
    account_id TEXT COLLATE "C" NOT NULL REFERENCES stormtrack.user_accounts(id),
    token_hash TEXT COLLATE "C" NOT NULL UNIQUE,
    created_at TEXT COLLATE "C" NOT NULL,
    expires_at TEXT COLLATE "C" NOT NULL,
    revoked_at TEXT COLLATE "C"
);
CREATE INDEX IF NOT EXISTS sessions_account_idx ON stormtrack.sessions(account_id);

CREATE TABLE IF NOT EXISTS stormtrack.data_sources (
    id TEXT COLLATE "C" PRIMARY KEY,
    provider_code TEXT COLLATE "C" NOT NULL,
    name TEXT COLLATE "C" NOT NULL,
    created_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE IF NOT EXISTS stormtrack.source_products (
    id TEXT COLLATE "C" PRIMARY KEY,
    source_id TEXT COLLATE "C" NOT NULL REFERENCES stormtrack.data_sources(id),
    product_code TEXT COLLATE "C" NOT NULL,
    access_status TEXT COLLATE "C" NOT NULL CHECK (access_status IN ('PENDING', 'VERIFIED', 'BLOCKED')) DEFAULT 'PENDING',
    collection_status TEXT COLLATE "C" NOT NULL CHECK (collection_status IN ('PENDING', 'VERIFIED', 'BLOCKED')) DEFAULT 'PENDING',
    storage_status TEXT COLLATE "C" NOT NULL CHECK (storage_status IN ('PENDING', 'VERIFIED', 'BLOCKED')) DEFAULT 'PENDING',
    redistribution_status TEXT COLLATE "C" NOT NULL CHECK (redistribution_status IN ('PENDING', 'VERIFIED', 'BLOCKED')) DEFAULT 'PENDING',
    terms_reference TEXT COLLATE "C",
    access_verified_at TEXT COLLATE "C",
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    created_at TEXT COLLATE "C" NOT NULL,
    UNIQUE(source_id, product_code)
);

CREATE TABLE IF NOT EXISTS stormtrack.operation_logs (
    id TEXT COLLATE "C" PRIMARY KEY,
    actor_id TEXT COLLATE "C" REFERENCES stormtrack.user_accounts(id),
    event_code TEXT COLLATE "C" NOT NULL,
    severity TEXT COLLATE "C" NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
    details TEXT COLLATE "C" NOT NULL DEFAULT '',
    occurred_at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX IF NOT EXISTS operation_logs_time_idx ON stormtrack.operation_logs(occurred_at);

CREATE TABLE IF NOT EXISTS stormtrack.data_artifacts (
    id TEXT COLLATE "C" PRIMARY KEY,
    artifact_type TEXT COLLATE "C" NOT NULL CHECK (artifact_type IN ('OBSERVATION', 'ANALYSIS_RESULT')),
    content_hash TEXT COLLATE "C" NOT NULL,
    raw_reference TEXT COLLATE "C",
    created_at TEXT COLLATE "C" NOT NULL
);

CREATE TABLE IF NOT EXISTS stormtrack.observations (
    artifact_id TEXT COLLATE "C" PRIMARY KEY REFERENCES stormtrack.data_artifacts(id),
    product_id TEXT COLLATE "C" NOT NULL REFERENCES stormtrack.source_products(id),
    observed_at_utc TEXT COLLATE "C" NOT NULL,
    received_at_utc TEXT COLLATE "C" NOT NULL,
    original_timestamp TEXT COLLATE "C" NOT NULL,
    original_offset TEXT COLLATE "C" NOT NULL,
    deduplication_key TEXT COLLATE "C" NOT NULL,
    data_type TEXT COLLATE "C" NOT NULL,
    UNIQUE(product_id, deduplication_key)
);
CREATE INDEX IF NOT EXISTS observations_time_idx ON stormtrack.observations(observed_at_utc);

CREATE TABLE IF NOT EXISTS stormtrack.observation_revisions (
    id TEXT COLLATE "C" PRIMARY KEY,
    observation_id TEXT COLLATE "C" NOT NULL REFERENCES stormtrack.observations(artifact_id),
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    content_hash TEXT COLLATE "C" NOT NULL,
    observed_at_utc TEXT COLLATE "C" NOT NULL,
    original_timestamp TEXT COLLATE "C" NOT NULL,
    original_offset TEXT COLLATE "C" NOT NULL,
    data_type TEXT COLLATE "C" NOT NULL,
    normalized_payload_json TEXT COLLATE "C" NOT NULL,
    geometry_json TEXT COLLATE "C",
    original_unit TEXT COLLATE "C",
    received_at_utc TEXT COLLATE "C" NOT NULL,
    raw_reference TEXT COLLATE "C",
    UNIQUE(observation_id, revision_number)
);

CREATE TABLE IF NOT EXISTS stormtrack.data_quality_assessments (
    id TEXT COLLATE "C" PRIMARY KEY,
    observation_id TEXT COLLATE "C" NOT NULL REFERENCES stormtrack.observations(artifact_id),
    assessed_at TEXT COLLATE "C" NOT NULL,
    completeness DOUBLE PRECISION CHECK (completeness IS NULL OR (completeness >= 0 AND completeness <= 1)),
    delay_seconds INTEGER CHECK (delay_seconds IS NULL OR delay_seconds >= 0),
    availability TEXT COLLATE "C" NOT NULL CHECK (availability IN ('AVAILABLE', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN')),
    resolution TEXT COLLATE "C"
);

CREATE TABLE IF NOT EXISTS stormtrack.source_health (
    id TEXT COLLATE "C" PRIMARY KEY,
    source_id TEXT COLLATE "C" NOT NULL REFERENCES stormtrack.data_sources(id),
    checked_at TEXT COLLATE "C" NOT NULL,
    status TEXT COLLATE "C" NOT NULL CHECK (status IN ('AVAILABLE', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN')),
    failure_reason TEXT COLLATE "C"
);
CREATE INDEX IF NOT EXISTS source_health_time_idx ON stormtrack.source_health(source_id, checked_at);
CREATE TABLE IF NOT EXISTS stormtrack.collection_runs (
    id TEXT COLLATE "C" PRIMARY KEY,
    product_id TEXT COLLATE "C" NOT NULL REFERENCES stormtrack.source_products(id),
    started_at TEXT COLLATE "C" NOT NULL,
    finished_at TEXT COLLATE "C" NOT NULL,
    status TEXT COLLATE "C" NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED', 'BLOCKED', 'NO_DATA', 'DEGRADED')),
    objects_seen INTEGER NOT NULL DEFAULT 0 CHECK (objects_seen >= 0),
    observations_written INTEGER NOT NULL DEFAULT 0 CHECK (observations_written >= 0),
    error_code TEXT COLLATE "C",
    details_json TEXT COLLATE "C" NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS collection_runs_product_time_idx
    ON stormtrack.collection_runs(product_id, started_at DESC);
CREATE TABLE IF NOT EXISTS stormtrack.ingestion_cursors (
    product_id TEXT COLLATE "C" PRIMARY KEY REFERENCES stormtrack.source_products(id),
    last_object_key TEXT COLLATE "C" NOT NULL,
    updated_at TEXT COLLATE "C" NOT NULL
);

-- Support an older schema in which deleted_at has not yet been added.
ALTER TABLE stormtrack.user_accounts ADD COLUMN IF NOT EXISTS deleted_at TEXT COLLATE "C";

CREATE UNIQUE INDEX IF NOT EXISTS user_accounts_username_nocase_idx
    ON stormtrack.user_accounts ((stormtrack.ascii_nocase(username) COLLATE "C"));
CREATE UNIQUE INDEX IF NOT EXISTS data_sources_provider_code_nocase_idx
    ON stormtrack.data_sources ((stormtrack.ascii_nocase(provider_code) COLLATE "C"));

CREATE OR REPLACE FUNCTION stormtrack.validate_enabled_source_product()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
BEGIN
    IF NEW.enabled = 1 AND (
        NEW.terms_reference IS NULL OR pg_catalog.length(pg_catalog.btrim(NEW.terms_reference)) = 0 OR
        NEW.access_status <> 'VERIFIED' OR
        NEW.collection_status <> 'VERIFIED' OR
        NEW.storage_status <> 'VERIFIED'
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514',
            MESSAGE = 'enabled source products require evidence and verified access, collection and storage';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE TRIGGER source_products_validate_enabled_insert
BEFORE INSERT ON stormtrack.source_products
FOR EACH ROW EXECUTE FUNCTION stormtrack.validate_enabled_source_product();
CREATE OR REPLACE TRIGGER source_products_validate_enabled_update
BEFORE UPDATE OF enabled, terms_reference, access_status, collection_status, storage_status
ON stormtrack.source_products
FOR EACH ROW EXECUTE FUNCTION stormtrack.validate_enabled_source_product();

-- A shared trigger preserves each SQLite error message. It also protects against
-- TRUNCATE, which is a PostgreSQL-only way of removing immutable observations.
CREATE OR REPLACE FUNCTION stormtrack.reject_immutable_record_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
BEGIN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = TG_ARGV[0];
END;
$function$;
CREATE OR REPLACE TRIGGER data_artifacts_reject_update
BEFORE UPDATE ON stormtrack.data_artifacts
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('data artifacts are immutable');

CREATE OR REPLACE TRIGGER data_artifacts_reject_delete
BEFORE DELETE ON stormtrack.data_artifacts
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('data artifacts are immutable');

CREATE OR REPLACE TRIGGER data_artifacts_reject_truncate
BEFORE TRUNCATE ON stormtrack.data_artifacts
FOR EACH STATEMENT EXECUTE FUNCTION stormtrack.reject_immutable_record_change('data artifacts are immutable');

CREATE OR REPLACE TRIGGER observations_reject_update
BEFORE UPDATE ON stormtrack.observations
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('observations are immutable');

CREATE OR REPLACE TRIGGER observations_reject_delete
BEFORE DELETE ON stormtrack.observations
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('observations are immutable');

CREATE OR REPLACE TRIGGER observations_reject_truncate
BEFORE TRUNCATE ON stormtrack.observations
FOR EACH STATEMENT EXECUTE FUNCTION stormtrack.reject_immutable_record_change('observations are immutable');

CREATE OR REPLACE TRIGGER observation_revisions_reject_update
BEFORE UPDATE ON stormtrack.observation_revisions
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('observation revisions are immutable');

CREATE OR REPLACE TRIGGER observation_revisions_reject_delete
BEFORE DELETE ON stormtrack.observation_revisions
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('observation revisions are immutable');

CREATE OR REPLACE TRIGGER observation_revisions_reject_truncate
BEFORE TRUNCATE ON stormtrack.observation_revisions
FOR EACH STATEMENT EXECUTE FUNCTION stormtrack.reject_immutable_record_change('observation revisions are immutable');

CREATE OR REPLACE TRIGGER data_quality_assessments_reject_update
BEFORE UPDATE ON stormtrack.data_quality_assessments
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('data quality assessments are immutable');

CREATE OR REPLACE TRIGGER data_quality_assessments_reject_delete
BEFORE DELETE ON stormtrack.data_quality_assessments
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('data quality assessments are immutable');

CREATE OR REPLACE TRIGGER data_quality_assessments_reject_truncate
BEFORE TRUNCATE ON stormtrack.data_quality_assessments
FOR EACH STATEMENT EXECUTE FUNCTION stormtrack.reject_immutable_record_change('data quality assessments are immutable');

CREATE OR REPLACE TRIGGER source_health_reject_update
BEFORE UPDATE ON stormtrack.source_health
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('source health records are immutable');

CREATE OR REPLACE TRIGGER source_health_reject_delete
BEFORE DELETE ON stormtrack.source_health
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('source health records are immutable');

CREATE OR REPLACE TRIGGER source_health_reject_truncate
BEFORE TRUNCATE ON stormtrack.source_health
FOR EACH STATEMENT EXECUTE FUNCTION stormtrack.reject_immutable_record_change('source health records are immutable');

CREATE OR REPLACE TRIGGER collection_runs_reject_update
BEFORE UPDATE ON stormtrack.collection_runs
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('collection runs are immutable');

CREATE OR REPLACE TRIGGER collection_runs_reject_delete
BEFORE DELETE ON stormtrack.collection_runs
FOR EACH ROW EXECUTE FUNCTION stormtrack.reject_immutable_record_change('collection runs are immutable');

CREATE OR REPLACE TRIGGER collection_runs_reject_truncate
BEFORE TRUNCATE ON stormtrack.collection_runs
FOR EACH STATEMENT EXECUTE FUNCTION stormtrack.reject_immutable_record_change('collection runs are immutable');

-- Access is exclusively through the backend database identity. These objects
-- are not public API tables and do not reuse or modify Supabase auth users.
REVOKE ALL ON ALL TABLES IN SCHEMA stormtrack FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA stormtrack FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA stormtrack FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA stormtrack REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA stormtrack REVOKE ALL ON SEQUENCES FROM PUBLIC;

-- The same SQL works on ordinary PostgreSQL where Supabase roles do not exist.
DO $permissions$
DECLARE
    api_role TEXT;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = api_role) THEN
            EXECUTE pg_catalog.format('REVOKE ALL ON SCHEMA stormtrack FROM %I', api_role);
            EXECUTE pg_catalog.format('REVOKE ALL ON ALL TABLES IN SCHEMA stormtrack FROM %I', api_role);
            EXECUTE pg_catalog.format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA stormtrack FROM %I', api_role);
            EXECUTE pg_catalog.format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA stormtrack FROM %I', api_role);
            EXECUTE pg_catalog.format('ALTER DEFAULT PRIVILEGES IN SCHEMA stormtrack REVOKE ALL ON TABLES FROM %I', api_role);
            EXECUTE pg_catalog.format('ALTER DEFAULT PRIVILEGES IN SCHEMA stormtrack REVOKE ALL ON SEQUENCES FROM %I', api_role);
        END IF;
    END LOOP;
END;
$permissions$;
