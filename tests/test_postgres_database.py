"""PostgreSQL adapter checks; integration uses only an opt-in disposable local DB.

STORMTRACK_TEST_POSTGRES_URL must name stormtrack_test on localhost or 127.0.0.1.
Integration tests reset the stormtrack schema in that database. They never connect
when the variable is unset. No live Supabase credentials are needed.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, unquote, urlsplit

from backend.app.core.postgres import HybridRow, PostgresConnection, translate_sql


def integration_url():
    value = os.environ.get("STORMTRACK_TEST_POSTGRES_URL", "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    allowed_query = {"sslmode", "connect_timeout", "application_name"}
    if (parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or unquote(parsed.path.lstrip("/")) != "stormtrack_test"
            or set(parse_qs(parsed.query, keep_blank_values=True)) - allowed_query):
        raise ValueError("PostgreSQL integration requires a disposable local stormtrack_test database")
    return value


class SqlTranslationTests(unittest.TestCase):
    def test_only_unquoted_question_marks_become_parameters(self):
        self.assertEqual(
            translate_sql("""SELECT ?, '?', 'it''s?', "field?", ?"""),
            """SELECT %s, '?', 'it''s?', "field?", %s""",
        )

    def test_comments_and_dollar_quoted_bodies_preserve_question_marks(self):
        query = "SELECT ? -- ?\n, $body$ ? 50% $body$, ? /* ? /* ? */ ? */"
        self.assertEqual(
            translate_sql(query),
            "SELECT %s -- ?\n, $body$ ? 50%% $body$, %s /* ? /* ? */ ? */",
        )

    def test_literal_percents_remain_literals_with_parameter_binding(self):
        self.assertEqual(
            translate_sql("SELECT ?, '95%', '%s', 10 % 3, 'already%%'"),
            "SELECT %s, '95%%', '%%s', 10 %% 3, 'already%%%%'",
        )

    def test_test_url_rejects_remote_or_overridden_destinations(self):
        unsafe = [
            "postgresql://localhost/production",
            "postgresql://example.com/stormtrack_test",
            "postgresql://127.0.0.1/stormtrack_test?host=example.com",
            "postgresql://127.0.0.1/stormtrack_test?dbname=production",
            "postgresql://127.0.0.1/stormtrack_test?hostaddr=192.0.2.1",
        ]
        for value in unsafe:
            with self.subTest(value=value), patch.dict(
                os.environ, {"STORMTRACK_TEST_POSTGRES_URL": value}
            ):
                with self.assertRaises(ValueError):
                    integration_url()
        with patch.dict(os.environ, {
            "STORMTRACK_TEST_POSTGRES_URL":
                "postgresql://127.0.0.1:55432/stormtrack_test?sslmode=disable"
        }):
            self.assertIsNotNone(integration_url())

    def test_hybrid_rows_keep_mapping_and_position_access(self):
        row = HybridRow({"id": "account-1", "count": 4, "optional": None})
        self.assertEqual(row[0], "account-1")
        self.assertEqual(row[1], 4)
        self.assertIsNone(row[-1])
        self.assertEqual(row["count"], 4)
        self.assertEqual(dict(row), {"id": "account-1", "count": 4, "optional": None})


class DatabaseConfigTests(unittest.TestCase):
    def test_database_url_absent_preserves_sqlite_default(self):
        from backend.app.core.config import get_settings
        with patch.dict(os.environ, {}, clear=True):
            settings = get_settings()
        self.assertIsNone(settings.database_url)
        self.assertEqual(settings.database_backend, "sqlite")
        self.assertEqual(settings.database_target, settings.database_path)
        self.assertEqual(settings.database_path.name, "stormtrack.sqlite3")

    def test_explicit_postgres_target_selects_postgresql_backend(self):
        from backend.app.core.config import get_settings
        url = "postgresql://backend:fixture-secret@localhost/stormtrack_test"
        with patch.dict(os.environ, {"STORMTRACK_DATABASE_URL": url}, clear=True):
            settings = get_settings()
        self.assertEqual(settings.database_url, url)
        self.assertEqual(settings.database_target, url)
        self.assertEqual(settings.database_backend, "postgresql")

    def test_invalid_database_urls_do_not_leak_secrets(self):
        from backend.app.core.config import get_settings, validate_database_url
        invalid = [
            "mysql://backend:fixture-secret@localhost/database",
            "https://backend:fixture-secret@localhost/database",
            "postgresql://backend:fixture-secret@localhost",
            "postgresql://backend:fixture-secret@:5432/database",
            "postgresql://backend:fixture-secret@localhost:bad/database",
            "postgresql://backend:fixture-secret@localhost:99999/database",
            "postgresql://backend:fixture-secret@localhost/database#fragment-secret",
        ]
        for url in invalid:
            with self.subTest(url=url):
                with self.assertRaises(ValueError) as caught:
                    validate_database_url(url)
                self.assertNotIn("fixture-secret", str(caught.exception))
                self.assertNotIn("fragment-secret", str(caught.exception))
                with patch.dict(os.environ, {"STORMTRACK_DATABASE_URL": url}, clear=True):
                    with self.assertRaises(ValueError):
                        get_settings()

    def test_supabase_session_pooler_allowed_transaction_pooler_rejected(self):
        from backend.app.core.config import validate_database_url
        session = (
            "postgresql://postgres.project:fixture-secret@"
            "aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
        )
        self.assertEqual(validate_database_url(session), session)
        for transaction in [
            session.replace(":5432/", ":6543/"),
            "postgresql://postgres:fixture-secret@db.project.supabase.co:6543/postgres",
        ]:
            with self.subTest(url=transaction):
                with self.assertRaises(ValueError) as caught:
                    validate_database_url(transaction)
                self.assertNotIn("fixture-secret", str(caught.exception))


class FakeDriverError(Exception):
    pass


class FakeIntegrityError(FakeDriverError):
    def __init__(self, message):
        super().__init__(message)
        self.diag = types.SimpleNamespace(message_primary=message)


class FakeCursor:
    def __init__(self, raw, rows=()):
        self.raw = raw
        self.rows = deque(rows)
        self.rowcount = len(self.rows)
        self.description = [
            types.SimpleNamespace(name=name) for name in (self.rows[0] if self.rows else [])
        ]

    def execute(self, sql, params=None, **kwargs):
        return self.raw.execute(sql, params, **kwargs)

    def executemany(self, sql, parameters, **kwargs):
        values = list(parameters)
        self.raw.calls.append(("executemany", sql, values))
        self.rowcount = len(values)
        return self

    def fetchone(self):
        return self.rows.popleft() if self.rows else None

    def fetchall(self):
        result = list(self.rows)
        self.rows.clear()
        return result

    def __iter__(self):
        while self.rows:
            yield self.rows.popleft()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.next_rows = []
        self.next_error = None
        self.closed = False

    def execute(self, sql, params=None, **kwargs):
        self.calls.append(("execute", sql, params, kwargs))
        if self.next_error is not None:
            error, self.next_error = self.next_error, None
            raise error
        rows, self.next_rows = self.next_rows, []
        return FakeCursor(self, rows)

    def cursor(self, **kwargs):
        return FakeCursor(self)

    def commit(self):
        self.calls.append(("commit",))

    def rollback(self):
        self.calls.append(("rollback",))

    def close(self):
        self.closed = True


class AdapterUnitTests(unittest.TestCase):
    def setUp(self):
        self.raw = FakeConnection()
        driver = types.ModuleType("psycopg")
        driver.Error = FakeDriverError
        driver.IntegrityError = FakeIntegrityError
        driver.connect = Mock(return_value=self.raw)
        rows = types.ModuleType("psycopg.rows")
        rows.dict_row = object()
        conninfo = types.ModuleType("psycopg.conninfo")
        conninfo.conninfo_to_dict = lambda dsn: {"sslmode": "disable"}
        driver.rows = rows
        self.driver = driver
        self.modules = patch.dict(sys.modules, {
            "psycopg": driver, "psycopg.rows": rows, "psycopg.conninfo": conninfo,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.db = PostgresConnection(
            "postgresql://127.0.0.1/stormtrack_test?sslmode=disable"
        )
        self.addCleanup(self.db.close)
        self.raw.calls.clear()

    def test_connection_uses_autocommit_and_disables_preparation(self):
        kwargs = self.driver.connect.call_args.kwargs
        self.assertTrue(kwargs["autocommit"])
        self.assertIsNone(kwargs["prepare_threshold"])
        self.assertEqual(self.db.dialect, "postgresql")

    def test_execute_binds_values_and_wraps_rows(self):
        self.raw.next_rows = [{"label": "fixture", "count": 3}]
        result = self.db.execute("SELECT ? AS label, 3 AS count", ("fixture",)).fetchone()
        self.assertEqual(result[0], "fixture")
        self.assertEqual(result["count"], 3)
        self.assertEqual(dict(result), {"label": "fixture", "count": 3})
        call = self.raw.calls[-1]
        self.assertEqual(call[1], "SELECT %s AS label, 3 AS count")
        self.assertEqual(call[2], ("fixture",))

    def test_cursor_iteration_fetchall_and_empty_fetchone(self):
        self.raw.next_rows = [{"id": 1}, {"id": 2}]
        self.assertEqual([row["id"] for row in self.db.execute("SELECT id")], [1, 2])
        self.raw.next_rows = [{"id": 3}, {"id": 4}]
        self.assertEqual(
            [row[0] for row in self.db.execute("SELECT id").fetchall()], [3, 4]
        )
        self.assertIsNone(self.db.execute("SELECT id WHERE false").fetchone())

    def test_begin_immediate_takes_transaction_advisory_lock(self):
        self.db.execute("BEGIN IMMEDIATE")
        executed = [call[1] for call in self.raw.calls if call[0] == "execute"]
        self.assertEqual(executed[0].strip().upper(), "BEGIN")
        self.assertTrue(any("pg_advisory_xact_lock" in query for query in executed[1:]))
        self.db.rollback()
        self.assertEqual(self.raw.calls[-1], ("rollback",))

    def test_integrity_errors_use_existing_sqlite_contract(self):
        self.raw.next_error = FakeIntegrityError("fixture uniqueness failed")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "fixture uniqueness failed"):
            self.db.execute("INSERT INTO example VALUES (?)", ("same",))
        self.raw.next_rows = [{"ok": 1}]
        self.assertEqual(self.db.execute("SELECT 1 AS ok").fetchone()[0], 1)

    def test_driver_error_messages_do_not_expose_connection_details(self):
        self.raw.next_error = FakeDriverError("postgresql://user:secret@example.com/db")
        with self.assertRaises(sqlite3.DatabaseError) as caught:
            self.db.execute("SELECT 1")
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("example.com", str(caught.exception))

    def test_raw_ddl_does_not_translate_dollar_quoted_bodies(self):
        ddl = "DO $$ BEGIN RAISE NOTICE 'keep ? and 50%'; END $$;"
        self.db.executescript(ddl)
        self.assertEqual(self.raw.calls[-1][1], ddl)


@unittest.skipUnless(
    os.environ.get("STORMTRACK_TEST_POSTGRES_URL"),
    "Set STORMTRACK_TEST_POSTGRES_URL for disposable local PostgreSQL integration",
)
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = integration_url()

    def setUp(self):
        import psycopg
        from backend.app.core.db import connect, initialize_database
        from backend.app.accounts.service import provision_account

        # The guard above forbids remote hosts and URI query overrides.
        with psycopg.connect(self.url, autocommit=True) as raw:
            raw.execute("DROP SCHEMA IF EXISTS stormtrack CASCADE")
        initialize_database(self.url)
        self.db = connect(self.url)
        self.addCleanup(self.db.close)
        self.admin = provision_account(
            self.db, "Admin", "Admin!Password2026", "ADMIN"
        )

    def product(self, authorized=False):
        from backend.app.sources.service import create_source_product, update_source_product
        result = create_source_product(
            self.db, "NOAA", "NOAA test fixture", "TEST-GLM", actor_id=self.admin["id"]
        )
        if authorized:
            update_source_product(self.db, result["id"], {
                "access_status": "VERIFIED", "collection_status": "VERIFIED",
                "storage_status": "VERIFIED", "enabled": True,
                "terms_reference": "local-postgres-fixture",
            }, self.admin["id"])
        return result

    def test_schema_is_private_and_initialization_is_idempotent(self):
        from backend.app.core.db import initialize_database
        initialize_database(self.url)
        tables = {row[0] for row in self.db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'stormtrack'"
        )}
        self.assertEqual(len(tables), 12)
        self.assertIn("user_accounts", tables)
        self.assertIn("observation_revisions", tables)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM user_accounts"
        ).fetchone()[0], 1)
        public_schema_grants = self.db.execute(
            "SELECT a.privilege_type FROM pg_namespace n "
            "CROSS JOIN LATERAL aclexplode(COALESCE(n.nspacl, acldefault('n', n.nspowner))) a "
            "WHERE n.nspname = 'stormtrack' AND a.grantee = 0"
        ).fetchall()
        self.assertEqual(public_schema_grants, [])
        for role in ("anon", "authenticated"):
            if self.db.execute("SELECT 1 FROM pg_roles WHERE rolname = ?", (role,)).fetchone():
                self.assertFalse(self.db.execute(
                    "SELECT has_schema_privilege(?, 'stormtrack', 'USAGE')", (role,)
                ).fetchone()[0])
        public_table_grants = self.db.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) a "
            "WHERE n.nspname = 'stormtrack' AND c.relkind = 'r' AND a.grantee = 0"
        ).fetchall()
        self.assertEqual(public_table_grants, [])

    def test_case_insensitive_accounts_and_password_reset_revoke_sessions(self):
        from backend.app.accounts.service import (
            AccountConflictError, AuthenticationError, authenticate_and_issue_session,
            provision_account, resolve_session, update_account,
        )
        user = provision_account(self.db, "Joao", "User!Password2026", "USER")
        with self.assertRaises(AccountConflictError):
            provision_account(self.db, "jOAO", "User!Password2026", "USER")
        account, token, _ = authenticate_and_issue_session(
            self.db, "JOAO", "User!Password2026", 60
        )
        self.assertEqual(account["id"], user["id"])
        self.assertIsNotNone(resolve_session(self.db, token))
        update_account(
            self.db, user["id"], {"password": "Changed!Password2026"}, self.admin["id"]
        )
        self.assertIsNone(resolve_session(self.db, token))
        with self.assertRaises(AuthenticationError):
            authenticate_and_issue_session(self.db, "joao", "User!Password2026", 60)
        self.assertEqual(
            authenticate_and_issue_session(self.db, "joao", "Changed!Password2026", 60)[0]["id"],
            user["id"],
        )

    def test_bound_literals_and_metadata_remain_compatible(self):
        row = self.db.execute(
            "SELECT ? AS bound, '?' AS question, '95%' AS percent, 10 % 3 AS remainder",
            ("value?%",),
        ).fetchone()
        self.assertEqual(dict(row), {
            "bound": "value?%", "question": "?", "percent": "95%", "remainder": 1
        })
        self.assertEqual(row[0], "value?%")
        self.assertEqual(self.db.dialect, "postgresql")
        self.assertIsInstance(self.db.execute(
            "SELECT created_at FROM user_accounts"
        ).fetchone()[0], str)

    def test_enabled_gate_is_enforced_by_database(self):
        from backend.app.sources.service import update_source_product
        product = self.product()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE source_products SET enabled = 1 WHERE id = ?", (product["id"],)
            )
        self.db.rollback()
        self.assertEqual(self.db.execute(
            "SELECT enabled FROM source_products WHERE id = ?", (product["id"],)
        ).fetchone()[0], 0)
        update_source_product(self.db, product["id"], {
            "access_status": "VERIFIED", "collection_status": "VERIFIED",
            "storage_status": "VERIFIED", "enabled": True, "terms_reference": "fixture",
        }, self.admin["id"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "UPDATE source_products SET terms_reference = ' ' WHERE id = ?",
                (product["id"],),
            )

    def test_provenance_rejects_update_delete_and_truncate(self):
        from backend.app.observations.service import (
            ingest_observation, record_data_quality, record_source_health,
        )
        product = self.product(authorized=True)
        observation = ingest_observation(
            self.db, product["id"], observed_at="2026-10-06T16:00:00-03:00",
            deduplication_key="postgres-fixture", data_type="LIGHTNING_FLASHES",
            normalized_payload={"flashes": 1},
            geometry={"type": "FeatureCollection", "features": [{
                "type": "Feature", "geometry": {"type": "Point", "coordinates": [-51.94, -23.42]},
                "properties": {},
            }]},
        )
        record_data_quality(
            self.db, observation["observation_id"], completeness=None,
            delay_seconds=None, availability="UNKNOWN",
        )
        source_id = self.db.execute(
            "SELECT source_id FROM source_products WHERE id = ?", (product["id"],)
        ).fetchone()[0]
        record_source_health(self.db, source_id, "AVAILABLE")
        self.db.execute(
            "INSERT INTO collection_runs(id, product_id, started_at, finished_at, status) "
            "VALUES ('fixture-run', ?, '2026-10-06T19:00:00Z', '2026-10-06T19:01:00Z', 'NO_DATA')",
            (product["id"],),
        )
        for table, key in [
            ("data_artifacts", "id"), ("observations", "artifact_id"),
            ("observation_revisions", "id"), ("data_quality_assessments", "id"),
            ("source_health", "id"), ("collection_runs", "id"),
        ]:
            for sql in (
                f"UPDATE {table} SET {key} = {key}",
                f"DELETE FROM {table}",
                f"TRUNCATE {table} CASCADE",
            ):
                with self.subTest(table=table, sql=sql):
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.db.execute(sql)
                    self.db.rollback()
                    self.assertEqual(
                        self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1
                    )

    def test_transaction_rollback_and_executemany(self):
        self.db.execute("BEGIN IMMEDIATE")
        self.db.executemany(
            "INSERT INTO data_sources(id, provider_code, name, created_at) VALUES (?, ?, ?, ?)",
            [
                ("rollback-1", "TEST-1", "fixture", "2026-10-06T19:00:00Z"),
                ("rollback-2", "TEST-2", "fixture", "2026-10-06T19:00:00Z"),
            ],
        )
        self.db.rollback()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM data_sources").fetchone()[0], 0)

    def test_account_limit_is_serialized_between_connections(self):
        from backend.app.accounts.service import AccountLimitError, provision_account
        from backend.app.core.db import connect
        for i in range(3):
            provision_account(self.db, f"existing-{i}", "User!Password2026", "USER")
        barrier = threading.Barrier(2)

        def attempt(name):
            connection = connect(self.url)
            try:
                barrier.wait(timeout=5)
                try:
                    provision_account(connection, name, "User!Password2026", "USER")
                    return "created"
                except AccountLimitError:
                    return "limit"
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, ("candidate-one", "candidate-two")))
        self.assertCountEqual(results, ["created", "limit"])
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM user_accounts").fetchone()[0], 5
        )


if __name__ == "__main__":
    unittest.main()
