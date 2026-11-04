"""Offline checks for dry-run and verified all-or-nothing database transfers."""
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from backend.app.core.db import connect, initialize_database
from backend.app.scripts import migrate_to_postgres as migration


class DatabaseTransferTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source.sqlite3"
        self.target = self.root / "target.sqlite3"
        initialize_database(self.source)
        initialize_database(self.target)
        self.source_connection = connect(self.source)
        self.target_connection = connect(self.target)
        self.addCleanup(self.source_connection.close)
        self.addCleanup(self.target_connection.close)
        self.timestamp = "2026-10-06T19:00:00+00:00"
        self.fixtures = {
            "user_accounts": [
                ("admin-id", "Admin", "unchanged-password-hash", "ADMIN", "ACTIVE", self.timestamp, self.timestamp, None),
                ("deleted-user-id", "deleted-user", "deleted-user-password-hash", "USER", "DISABLED",
                 self.timestamp, self.timestamp, self.timestamp),
            ],
            "data_sources": [("source-id", "NOAA", "NOAA", self.timestamp)],
            "source_products": [("product-id", "source-id", "GOES-19-GLM", "VERIFIED", "VERIFIED",
                                 "VERIFIED", "PENDING", "reviewed-terms", self.timestamp, 1, self.timestamp)],
            "operation_logs": [("log-id", "deleted-user-id", "LOGIN_SUCCEEDED", "INFO", '{"cidade":"Maringá"}', self.timestamp)],
            "data_artifacts": [("artifact-id", "OBSERVATION", "original-content-hash", "data/raw/example.nc", self.timestamp)],
            "observations": [("artifact-id", "product-id", self.timestamp, self.timestamp, self.timestamp,
                              "+00:00", "dedupe-id", "LIGHTNING")],
            "observation_revisions": [("revision-id", "artifact-id", 1, "revision-content-hash",
                                       self.timestamp, self.timestamp, "+00:00", "LIGHTNING",
                                       '{"energia":0.8,"cidade":"Maringá"}', '{"type":"Point","coordinates":[-51.93,-23.42]}',
                                       "J", self.timestamp, "data/raw/example.nc")],
            "data_quality_assessments": [("quality-id", "artifact-id", self.timestamp, 0.875, 3, "AVAILABLE", None)],
            "source_health": [("health-id", "source-id", self.timestamp, "AVAILABLE", None)],
            "collection_runs": [("run-id", "product-id", self.timestamp, self.timestamp, "SUCCEEDED", 1, 1, None, '{"bytes":2048}')],
            "ingestion_cursors": [("product-id", "example.nc", self.timestamp)],
            "sessions": [("session-id", "admin-id", "unchanged-session-token-hash", self.timestamp, self.timestamp, None)],
        }
        for table, rows in self.fixtures.items():
            for row in rows:
                placeholders = ", ".join("?" for _ in row)
                self.source_connection.execute(f'INSERT INTO "{table}" VALUES ({placeholders})', row)

    def assert_target_empty(self):
        for table in migration.TABLE_COLUMNS:
            self.assertEqual(self.target_connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0], 0, table)

    def test_default_inspection_never_opens_destination_or_changes_source(self):
        before = self.source.read_bytes()
        factory = Mock(side_effect=AssertionError("No destination connection during inspection"))
        initializer = Mock(side_effect=AssertionError("No destination setup during inspection"))
        report = migration.migrate(
            self.source, database_url="postgresql://username:secret@invalid.invalid/database",
            connect_fn=factory, initialize_fn=initializer,
        )
        factory.assert_not_called()
        initializer.assert_not_called()
        self.assertEqual(len(report), 12)
        self.assertEqual(report["user_accounts"], migration.TableSummary(2, 2))
        self.assertEqual(report["sessions"], migration.TableSummary(1, 0))
        self.assertEqual(self.source.read_bytes(), before)
        self.assert_target_empty()

    def test_transfer_preserves_full_contents_and_does_not_migrate_sessions(self):
        before = self.source.read_bytes()
        with migration.source_snapshot(self.source) as snapshot:
            report = migration.transfer_snapshot(snapshot, self.target_connection)
            for table in migration.TABLE_COLUMNS:
                if table != "sessions":
                    self.assertEqual(migration.content_digest(snapshot, table),
                                     migration.content_digest(self.target_connection, table), table)
        self.assertEqual(report["sessions"].destination_rows, 0)
        self.assertEqual(self.target_connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
        copied = self.target_connection.execute("SELECT * FROM user_accounts WHERE id = 'admin-id'").fetchone()
        self.assertEqual(copied["password_hash"], "unchanged-password-hash")
        deleted = self.target_connection.execute("SELECT * FROM user_accounts WHERE id = 'deleted-user-id'").fetchone()
        self.assertEqual(deleted["deleted_at"], self.timestamp)
        self.assertEqual(self.target_connection.execute("SELECT actor_id FROM operation_logs").fetchone()[0], "deleted-user-id")
        self.assertEqual(list(self.target_connection.execute("PRAGMA foreign_key_check")), [])
        self.assertEqual(self.source.read_bytes(), before)

    def test_readonly_snapshot_is_consistent_even_when_live_source_changes(self):
        with migration.source_snapshot(self.source) as snapshot:
            original = migration.content_digest(snapshot, "user_accounts")
            self.source_connection.execute("UPDATE user_accounts SET username = 'new-admin-name' WHERE id = 'admin-id'")
            self.assertEqual(migration.content_digest(snapshot, "user_accounts"), original)
            with self.assertRaises(sqlite3.OperationalError):
                snapshot.execute("UPDATE user_accounts SET username = 'not-allowed' WHERE id = 'admin-id'")
            migration.transfer_snapshot(snapshot, self.target_connection)
        self.assertEqual(self.target_connection.execute("SELECT username FROM user_accounts WHERE id = 'admin-id'").fetchone()[0], "Admin")

    def test_legacy_deleted_at_is_normalized_in_memory_only(self):
        self.source_connection.execute("ALTER TABLE user_accounts DROP COLUMN deleted_at")
        before = self.source.read_bytes()
        with migration.source_snapshot(self.source) as snapshot:
            self.assertIsNone(snapshot.execute("SELECT deleted_at FROM user_accounts LIMIT 1").fetchone()[0])
            migration.transfer_snapshot(snapshot, self.target_connection)
        self.assertEqual(self.source.read_bytes(), before)
        columns = {row["name"] for row in self.source_connection.execute("PRAGMA table_info(user_accounts)")}
        self.assertNotIn("deleted_at", columns)
        self.assertIsNone(self.target_connection.execute("SELECT deleted_at FROM user_accounts LIMIT 1").fetchone()[0])

    def test_existing_target_sessions_cause_rejection_without_changes(self):
        for row in self.fixtures["user_accounts"]:
            self.target_connection.execute("INSERT INTO user_accounts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
        self.target_connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)", self.fixtures["sessions"][0])
        before = self.target.read_bytes()
        with migration.source_snapshot(self.source) as snapshot:
            with self.assertRaises(migration.MigrationError):
                migration.transfer_snapshot(snapshot, self.target_connection)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.target_connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)

    def test_insert_failure_rolls_back_all_tables_and_preserves_source(self):
        self.target_connection.execute("""
            CREATE TRIGGER reject_import BEFORE INSERT ON data_artifacts
            BEGIN SELECT RAISE(ABORT, 'test destination failure'); END
        """)
        before = self.source.read_bytes()
        with migration.source_snapshot(self.source) as snapshot:
            with self.assertRaises(sqlite3.IntegrityError):
                migration.transfer_snapshot(snapshot, self.target_connection)
        self.assert_target_empty()
        self.assertEqual(self.source.read_bytes(), before)

    def test_same_row_count_but_changed_content_causes_full_rollback(self):
        self.target_connection.execute("""
            CREATE TRIGGER change_import AFTER INSERT ON user_accounts
            BEGIN UPDATE user_accounts SET password_hash = 'changed' WHERE id = NEW.id; END
        """)
        with migration.source_snapshot(self.source) as snapshot:
            with self.assertRaisesRegex(migration.MigrationError, "conteúdo"):
                migration.transfer_snapshot(snapshot, self.target_connection)
        self.assert_target_empty()

    def test_unexpected_source_table_or_column_and_missing_table_are_rejected_before_connect(self):
        cases = (
            "CREATE TABLE unexpected_table (id TEXT)",
            "ALTER TABLE user_accounts ADD COLUMN unexpected_column TEXT",
            "DROP TABLE ingestion_cursors",
        )
        for statement in cases:
            with self.subTest(statement=statement):
                self.source_connection.execute("BEGIN")
                self.source_connection.execute(statement)
                self.source_connection.execute("COMMIT")
                factory = Mock()
                initializer = Mock()
                try:
                    with self.assertRaises(migration.MigrationError):
                        migration.migrate(self.source, apply=True, database_url="postgresql://test/test",
                                          connect_fn=factory, initialize_fn=initializer)
                    factory.assert_not_called()
                    initializer.assert_not_called()
                finally:
                    if "CREATE TABLE" in statement:
                        self.source_connection.execute("DROP TABLE unexpected_table")
                    elif "ADD COLUMN" in statement:
                        self.source_connection.execute("ALTER TABLE user_accounts DROP COLUMN unexpected_column")
                    else:
                        initialize_database(self.source)

    def test_unexpected_target_columns_are_rejected_without_importing_data(self):
        self.target_connection.execute("ALTER TABLE user_accounts ADD COLUMN unexpected_column TEXT")
        with migration.source_snapshot(self.source) as snapshot:
            with self.assertRaises(migration.MigrationError):
                migration.transfer_snapshot(snapshot, self.target_connection)
        self.assert_target_empty()

    def test_missing_source_and_non_postgres_destination_are_rejected_without_creation(self):
        missing = self.root / "missing.sqlite3"
        with self.assertRaises(migration.MigrationError):
            migration.migrate(missing)
        self.assertFalse(missing.exists())
        for destination in (None, "", str(self.target), "sqlite:///test.sqlite3", "https://example.supabase.co"):
            with self.subTest(destination=destination):
                factory = Mock()
                initializer = Mock()
                with self.assertRaises(migration.MigrationError):
                    migration.migrate(self.source, apply=True, database_url=destination,
                                      connect_fn=factory, initialize_fn=initializer)
                factory.assert_not_called()
                initializer.assert_not_called()
        self.assert_target_empty()

    def test_cli_counts_and_driver_error_never_expose_secrets(self):
        url = "postgresql://username:highly-secret-password@example.invalid/postgres"
        output = io.StringIO()
        errors = io.StringIO()
        with patch.dict(os.environ, {"STORMTRACK_DATABASE_URL": url}):
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(migration.main(["--source", str(self.source)]), 0)
            self.assertIn("user_accounts: origem=2; destino=2", output.getvalue())
            self.assertIn("sessions: origem=1; destino=0", output.getvalue())
            with patch.object(migration, "initialize_database", side_effect=RuntimeError(url + " unchanged-password-hash")):
                with redirect_stdout(output), redirect_stderr(errors):
                    self.assertEqual(migration.main(["--source", str(self.source), "--apply"]), 1)
        rendered = output.getvalue() + errors.getvalue()
        for secret in (url, "highly-secret-password", "unchanged-password-hash", "unchanged-session-token-hash"):
            self.assertNotIn(secret, rendered)
        self.assert_target_empty()

    def test_checksum_reads_values_from_postgres_mapping_rows(self):
        from backend.app.core.postgres import HybridRow

        class MappingConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql):
                return [HybridRow(dict(row)) for row in self.connection.execute(sql)]

        mapping_connection = MappingConnection(self.source_connection)
        for table in migration.TABLE_COLUMNS:
            self.assertEqual(migration.content_digest(self.source_connection, table),
                             migration.content_digest(mapping_connection, table), table)

    def test_argument_errors_do_not_repeat_accidentally_supplied_credentials(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            with self.assertRaises(SystemExit):
                migration.main(["--database-url", "postgresql://user:do-not-print@host/database"])
        self.assertNotIn("do-not-print", errors.getvalue())
        self.assertNotIn("postgresql://", errors.getvalue())

    def test_numeric_checksum_accepts_equivalent_real_representations(self):
        self.assertEqual(migration._canonical(1.0), migration._canonical(1))
        self.assertEqual(migration._canonical(-0.0), migration._canonical(0))
        from decimal import Decimal
        self.assertEqual(migration._canonical(0.875), migration._canonical(Decimal('0.875')))
        with self.assertRaises(migration.MigrationError):
            migration._canonical(float("inf"))


if __name__ == "__main__":
    unittest.main()

