from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS user_accounts (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('ADMIN', 'USER')),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_admin_account
    ON user_accounts(role) WHERE role = 'ADMIN';

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES user_accounts(id),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS sessions_account_idx ON sessions(account_id);

CREATE TABLE IF NOT EXISTS data_sources (
    id TEXT PRIMARY KEY,
    provider_code TEXT NOT NULL COLLATE NOCASE UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_products (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES data_sources(id),
    product_code TEXT NOT NULL,
    access_status TEXT NOT NULL CHECK (access_status IN ('PENDING', 'VERIFIED', 'BLOCKED')) DEFAULT 'PENDING',
    collection_status TEXT NOT NULL CHECK (collection_status IN ('PENDING', 'VERIFIED', 'BLOCKED')) DEFAULT 'PENDING',
    storage_status TEXT NOT NULL CHECK (storage_status IN ('PENDING', 'VERIFIED', 'BLOCKED')) DEFAULT 'PENDING',
    redistribution_status TEXT NOT NULL CHECK (redistribution_status IN ('PENDING', 'VERIFIED', 'BLOCKED')) DEFAULT 'PENDING',
    terms_reference TEXT,
    access_verified_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(source_id, product_code)
);
CREATE TRIGGER IF NOT EXISTS source_products_validate_enabled_insert
BEFORE INSERT ON source_products
WHEN NEW.enabled = 1 AND (
    NEW.terms_reference IS NULL OR length(trim(NEW.terms_reference)) = 0 OR
    NEW.access_status != 'VERIFIED' OR
    NEW.collection_status != 'VERIFIED' OR
    NEW.storage_status != 'VERIFIED'
)
BEGIN
    SELECT RAISE(ABORT, 'enabled source products require evidence and verified access, collection and storage');
END;
CREATE TRIGGER IF NOT EXISTS source_products_validate_enabled_update
BEFORE UPDATE OF enabled, terms_reference, access_status, collection_status, storage_status
ON source_products
WHEN NEW.enabled = 1 AND (
    NEW.terms_reference IS NULL OR length(trim(NEW.terms_reference)) = 0 OR
    NEW.access_status != 'VERIFIED' OR
    NEW.collection_status != 'VERIFIED' OR
    NEW.storage_status != 'VERIFIED'
)
BEGIN
    SELECT RAISE(ABORT, 'enabled source products require evidence and verified access, collection and storage');
END;

CREATE TABLE IF NOT EXISTS operation_logs (
    id TEXT PRIMARY KEY,
    actor_id TEXT REFERENCES user_accounts(id),
    event_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
    details TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS operation_logs_time_idx ON operation_logs(occurred_at);

CREATE TABLE IF NOT EXISTS data_artifacts (
    id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('OBSERVATION', 'ANALYSIS_RESULT')),
    content_hash TEXT NOT NULL,
    raw_reference TEXT,
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS data_artifacts_reject_update
BEFORE UPDATE ON data_artifacts
BEGIN
    SELECT RAISE(ABORT, 'data artifacts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS data_artifacts_reject_delete
BEFORE DELETE ON data_artifacts
BEGIN
    SELECT RAISE(ABORT, 'data artifacts are immutable');
END;

CREATE TABLE IF NOT EXISTS observations (
    artifact_id TEXT PRIMARY KEY REFERENCES data_artifacts(id),
    product_id TEXT NOT NULL REFERENCES source_products(id),
    observed_at_utc TEXT NOT NULL,
    received_at_utc TEXT NOT NULL,
    original_timestamp TEXT NOT NULL,
    original_offset TEXT NOT NULL,
    deduplication_key TEXT NOT NULL,
    data_type TEXT NOT NULL,
    UNIQUE(product_id, deduplication_key)
);
CREATE INDEX IF NOT EXISTS observations_time_idx ON observations(observed_at_utc);
CREATE TRIGGER IF NOT EXISTS observations_reject_update
BEFORE UPDATE ON observations
BEGIN
    SELECT RAISE(ABORT, 'observations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS observations_reject_delete
BEFORE DELETE ON observations
BEGIN
    SELECT RAISE(ABORT, 'observations are immutable');
END;

CREATE TABLE IF NOT EXISTS observation_revisions (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL REFERENCES observations(artifact_id),
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    content_hash TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    original_timestamp TEXT NOT NULL,
    original_offset TEXT NOT NULL,
    data_type TEXT NOT NULL,
    normalized_payload_json TEXT NOT NULL,
    geometry_json TEXT,
    original_unit TEXT,
    received_at_utc TEXT NOT NULL,
    raw_reference TEXT,
    UNIQUE(observation_id, revision_number)
);
CREATE TRIGGER IF NOT EXISTS observation_revisions_reject_update
BEFORE UPDATE ON observation_revisions
BEGIN
    SELECT RAISE(ABORT, 'observation revisions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS observation_revisions_reject_delete
BEFORE DELETE ON observation_revisions
BEGIN
    SELECT RAISE(ABORT, 'observation revisions are immutable');
END;

CREATE TABLE IF NOT EXISTS data_quality_assessments (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL REFERENCES observations(artifact_id),
    assessed_at TEXT NOT NULL,
    completeness REAL CHECK (completeness IS NULL OR (completeness >= 0 AND completeness <= 1)),
    delay_seconds INTEGER CHECK (delay_seconds IS NULL OR delay_seconds >= 0),
    availability TEXT NOT NULL CHECK (availability IN ('AVAILABLE', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN')),
    resolution TEXT
);
CREATE TRIGGER IF NOT EXISTS data_quality_assessments_reject_update
BEFORE UPDATE ON data_quality_assessments
BEGIN
    SELECT RAISE(ABORT, 'data quality assessments are immutable');
END;
CREATE TRIGGER IF NOT EXISTS data_quality_assessments_reject_delete
BEFORE DELETE ON data_quality_assessments
BEGIN
    SELECT RAISE(ABORT, 'data quality assessments are immutable');
END;

CREATE TABLE IF NOT EXISTS source_health (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES data_sources(id),
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('AVAILABLE', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN')),
    failure_reason TEXT
);
CREATE INDEX IF NOT EXISTS source_health_time_idx ON source_health(source_id, checked_at);
CREATE TRIGGER IF NOT EXISTS source_health_reject_update
BEFORE UPDATE ON source_health
BEGIN
    SELECT RAISE(ABORT, 'source health records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS source_health_reject_delete
BEFORE DELETE ON source_health
BEGIN
    SELECT RAISE(ABORT, 'source health records are immutable');
END;
CREATE TABLE IF NOT EXISTS collection_runs (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES source_products(id),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED', 'BLOCKED', 'NO_DATA', 'DEGRADED')),
    objects_seen INTEGER NOT NULL DEFAULT 0 CHECK (objects_seen >= 0),
    observations_written INTEGER NOT NULL DEFAULT 0 CHECK (observations_written >= 0),
    error_code TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS collection_runs_product_time_idx
    ON collection_runs(product_id, started_at DESC);
CREATE TRIGGER IF NOT EXISTS collection_runs_reject_update
BEFORE UPDATE ON collection_runs
BEGIN
    SELECT RAISE(ABORT, 'collection runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS collection_runs_reject_delete
BEFORE DELETE ON collection_runs
BEGIN
    SELECT RAISE(ABORT, 'collection runs are immutable');
END;
CREATE TABLE IF NOT EXISTS ingestion_cursors (
    product_id TEXT PRIMARY KEY REFERENCES source_products(id),
    last_object_key TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(database_path: Path | str):
    if isinstance(database_path, str) and "://" in database_path:
        from backend.app.core.config import validate_database_url
        from backend.app.core.postgres import PostgresConnection
        return PostgresConnection(validate_database_url(database_path))
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may run dependency entry, route and cleanup in different workers.
    # Each request owns its connection; transactions serialize account changes.
    connection = sqlite3.connect(database_path, timeout=5, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.create_function("ascii_nocase", 1, ascii_nocase, deterministic=True)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database(database_path: Path | str) -> None:
    connection = connect(database_path)
    try:
        if getattr(connection, "dialect", "sqlite") == "postgresql":
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.executescript(Path(__file__).with_name("postgres_schema.sql").read_text(encoding="utf-8"))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return
        connection.executescript(SCHEMA)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(user_accounts)")}
        if "deleted_at" not in columns:
            connection.execute("ALTER TABLE user_accounts ADD COLUMN deleted_at TEXT")
    finally:
        connection.close()


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def ascii_nocase(value):
    return value.translate(_ASCII_LOWER) if isinstance(value, str) else value


def database_health(connection) -> str:
    if getattr(connection, "dialect", "sqlite") == "postgresql":
        return "ok" if connection.execute("SELECT 1 AS alive").fetchone()[0] == 1 else "degraded"
    return connection.execute("PRAGMA quick_check").fetchone()[0]
