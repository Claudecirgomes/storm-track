"""HTTP account-management lifecycle checks, isolated from local project data."""
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

if find_spec("fastapi") and find_spec("httpx"):
    from fastapi.testclient import TestClient
else:
    TestClient = None


@unittest.skipIf(TestClient is None, "Install requirements.txt to run HTTP integration tests")
class AccountManagementTests(unittest.TestCase):
    ADMIN_PASSWORD = "Admin!Password2026"
    USER_PASSWORD = "User!Password2026-1"
    NEW_PASSWORD = "New!Password2026-2"
    SAFE_FIELDS = {"id", "username", "role", "status", "created_at", "updated_at"}

    def setUp(self):
        from backend.app.accounts.service import provision_account
        from backend.app.core.db import connect, initialize_database

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database_path = Path(temporary.name) / "stormtrack.sqlite3"
        environment = patch.dict(os.environ, {
            "STORMTRACK_DATA_DIR": temporary.name,
            "STORMTRACK_COLLECTION_ENABLED": "false",
            "STORMTRACK_SESSION_TTL_MINUTES": "60",
            "STORMTRACK_COLLECTION_INTERVAL_SECONDS": "60",
        })
        environment.start()
        self.addCleanup(environment.stop)
        initialize_database(self.database_path)
        connection = connect(self.database_path)
        try:
            self.admin = provision_account(connection, "admin", self.ADMIN_PASSWORD, "ADMIN")
            self.user = provision_account(connection, "user1", self.USER_PASSWORD, "USER")
        finally:
            connection.close()

        from backend.app.api.main import app
        context = TestClient(app)
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.admin_headers = self.headers(self.login("admin", self.ADMIN_PASSWORD))

    @staticmethod
    def headers(token):
        return {"Authorization": f"Bearer {token}"}

    def login(self, username, password):
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    def accounts(self):
        response = self.client.get("/api/admin/accounts", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def database_rows(self, sql, parameters=()):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute(sql, parameters)]
        finally:
            connection.close()

    def patch_account(self, account_id, changes):
        return self.client.patch(f"/api/admin/accounts/{account_id}", headers=self.admin_headers, json=changes)

    def create_user(self, username):
        response = self.client.post("/api/admin/accounts", headers=self.admin_headers, json={
            "username": username, "password": self.USER_PASSWORD,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_every_account_route_requires_administrator(self):
        user_headers = self.headers(self.login("user1", self.USER_PASSWORD))
        requests = (
            ("GET", "/api/admin/accounts", None),
            ("POST", "/api/admin/accounts", {"username": "newuser", "password": self.NEW_PASSWORD}),
            ("PATCH", f"/api/admin/accounts/{self.user['id']}", {"username": "changed"}),
            ("DELETE", f"/api/admin/accounts/{self.user['id']}", None),
        )
        for method, url, payload in requests:
            for headers, expected in (({}, 401), (user_headers, 403)):
                with self.subTest(method=method, expected=expected):
                    options = {"headers": headers}
                    if payload is not None:
                        options["json"] = payload
                    self.assertEqual(self.client.request(method, url, **options).status_code, expected)
        self.assertEqual({account["username"] for account in self.accounts()}, {"admin", "user1"})

    def test_list_create_and_update_never_return_secrets(self):
        accounts = self.accounts()
        self.assertEqual(len(accounts), 2)
        for account in accounts:
            self.assertEqual(set(account), self.SAFE_FIELDS)
        created = self.create_user("visitor")
        self.assertEqual(set(created), self.SAFE_FIELDS)
        self.assertEqual(created["role"], "USER")
        self.assertEqual(created["status"], "ACTIVE")
        changed = self.patch_account(created["id"], {"password": self.NEW_PASSWORD})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(set(changed.json()), self.SAFE_FIELDS | {"sessions_revoked"})
        audit = self.client.get("/api/admin/operation-logs", headers=self.admin_headers)
        self.assertEqual(audit.status_code, 200)
        public_json = json.dumps([accounts, created, changed.json(), audit.json()])
        for secret in (self.ADMIN_PASSWORD, self.USER_PASSWORD, self.NEW_PASSWORD):
            self.assertNotIn(secret, public_json)
        for row in self.database_rows("SELECT password_hash FROM user_accounts"):
            self.assertNotIn(row["password_hash"], public_json)
        for row in self.database_rows("SELECT token_hash FROM sessions"):
            self.assertNotIn(row["token_hash"], public_json)

    def test_rename_updates_login_and_revokes_current_session(self):
        token = self.login("user1", self.USER_PASSWORD)
        changed = self.patch_account(self.user["id"], {"username": "  visitante  "})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["username"], "visitante")
        self.assertTrue(changed.json()["sessions_revoked"])
        me = self.client.get("/api/auth/me", headers=self.headers(token))
        self.assertEqual(me.status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "user1", "password": self.USER_PASSWORD,
        }).status_code, 401)
        self.login("visitante", self.USER_PASSWORD)

    def test_password_reset_revokes_all_target_sessions_and_changes_credentials(self):
        tokens = [self.login("user1", self.USER_PASSWORD) for _ in range(2)]
        changed = self.patch_account(self.user["id"], {"password": self.NEW_PASSWORD})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertTrue(changed.json()["sessions_revoked"])
        for token in tokens:
            self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(token)).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "user1", "password": self.USER_PASSWORD,
        }).status_code, 401)
        self.login("user1", self.NEW_PASSWORD)
        self.assertEqual(self.client.get("/api/auth/me", headers=self.admin_headers).status_code, 200)

    def test_disable_then_reactivate_never_revives_previous_sessions(self):
        tokens = [self.login("user1", self.USER_PASSWORD) for _ in range(2)]
        disabled = self.patch_account(self.user["id"], {"status": "DISABLED"})
        self.assertEqual(disabled.status_code, 200, disabled.text)
        self.assertEqual(disabled.json()["status"], "DISABLED")
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "user1", "password": self.USER_PASSWORD,
        }).status_code, 401)
        for token in tokens:
            self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(token)).status_code, 401)
        active = self.patch_account(self.user["id"], {"status": "ACTIVE"})
        self.assertEqual(active.status_code, 200, active.text)
        for token in tokens:
            self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(token)).status_code, 401)
        self.login("user1", self.USER_PASSWORD)

    def test_delete_preserves_audit_and_frees_username_and_account_slot(self):
        token = self.login("user1", self.USER_PASSWORD)
        for username in ("user2", "user3", "user4"):
            self.create_user(username)
        history = self.database_rows("SELECT id, actor_id FROM operation_logs WHERE actor_id = ?", (self.user["id"],))
        self.assertTrue(history)
        response = self.client.delete(f"/api/admin/accounts/{self.user['id']}", headers=self.admin_headers)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        self.assertNotIn(self.user["id"], {account["id"] for account in self.accounts()})
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(token)).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "user1", "password": self.USER_PASSWORD,
        }).status_code, 401)
        deleted = self.database_rows("SELECT id, status, deleted_at FROM user_accounts WHERE id = ?", (self.user["id"],))[0]
        self.assertEqual(deleted["status"], "DISABLED")
        self.assertIsNotNone(deleted["deleted_at"])
        self.assertEqual(history, self.database_rows(
            "SELECT id, actor_id FROM operation_logs WHERE actor_id = ?", (self.user["id"],),
        ))
        replacement = self.create_user("user1")
        self.assertNotEqual(replacement["id"], self.user["id"])
        self.assertEqual(len(self.accounts()), 5)
        self.login("user1", self.USER_PASSWORD)
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(token)).status_code, 401)
        self.assertEqual(self.patch_account(self.user["id"], {"status": "ACTIVE"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/admin/accounts/{self.user['id']}", headers=self.admin_headers).status_code, 404)

    def test_disabled_users_still_count_toward_four_user_limit(self):
        for username in ("user2", "user3", "user4"):
            self.create_user(username)
        self.assertEqual(self.patch_account(self.user["id"], {"status": "DISABLED"}).status_code, 200)
        overflow = self.client.post("/api/admin/accounts", headers=self.admin_headers, json={
            "username": "user5", "password": self.USER_PASSWORD,
        })
        self.assertEqual(overflow.status_code, 409, overflow.text)
        self.assertEqual(len(self.accounts()), 5)

    def test_admin_cannot_be_disabled_deleted_or_demoted(self):
        disabled = self.patch_account(self.admin["id"], {"status": "DISABLED"})
        self.assertEqual(disabled.status_code, 403, disabled.text)
        deleted = self.client.delete(f"/api/admin/accounts/{self.admin['id']}", headers=self.admin_headers)
        self.assertEqual(deleted.status_code, 403, deleted.text)
        demoted = self.patch_account(self.admin["id"], {"role": "USER"})
        self.assertEqual(demoted.status_code, 422, demoted.text)
        me = self.client.get("/api/auth/me", headers=self.admin_headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "ADMIN")
        self.assertEqual(next(account for account in self.accounts() if account["id"] == self.admin["id"])["status"], "ACTIVE")

    def test_admin_self_password_reset_requires_new_login(self):
        another_admin_token = self.login("admin", self.ADMIN_PASSWORD)
        user_token = self.login("user1", self.USER_PASSWORD)
        changed = self.patch_account(self.admin["id"], {"password": self.NEW_PASSWORD})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertTrue(changed.json()["sessions_revoked"])
        for headers in (self.admin_headers, self.headers(another_admin_token)):
            self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)
            self.assertEqual(self.client.get("/api/admin/accounts", headers=headers).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "admin", "password": self.ADMIN_PASSWORD,
        }).status_code, 401)
        self.admin_headers = self.headers(self.login("admin", self.NEW_PASSWORD))
        self.assertEqual(len(self.accounts()), 2)
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(user_token)).status_code, 200)

    def test_duplicate_username_patch_is_atomic(self):
        token = self.login("user1", self.USER_PASSWORD)
        before_accounts = self.database_rows("SELECT * FROM user_accounts ORDER BY id")
        before_sessions = self.database_rows("SELECT * FROM sessions ORDER BY id")
        before_logs = self.database_rows("SELECT * FROM operation_logs ORDER BY id")
        duplicate = self.patch_account(self.user["id"], {"username": "ADMIN", "password": self.NEW_PASSWORD, "status": "DISABLED"})
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        self.assertEqual(before_accounts, self.database_rows("SELECT * FROM user_accounts ORDER BY id"))
        self.assertEqual(before_sessions, self.database_rows("SELECT * FROM sessions ORDER BY id"))
        self.assertEqual(before_logs, self.database_rows("SELECT * FROM operation_logs ORDER BY id"))
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(token)).status_code, 200)
        self.login("user1", self.USER_PASSWORD)
        created = self.client.post("/api/admin/accounts", headers=self.admin_headers, json={
            "username": " USER1 ", "password": self.NEW_PASSWORD,
        })
        self.assertEqual(created.status_code, 409, created.text)
        self.assertEqual(len(self.accounts()), 2)

    def test_invalid_payloads_cannot_change_accounts_or_revoke_sessions(self):
        token = self.login("user1", self.USER_PASSWORD)
        before_accounts = self.database_rows("SELECT * FROM user_accounts ORDER BY id")
        before_sessions = self.database_rows("SELECT * FROM sessions ORDER BY id")
        before_logs = self.database_rows("SELECT * FROM operation_logs ORDER BY id")
        payloads = ({}, {"username": None}, {"password": None}, {"status": None},
                    {"username": "   "}, {"username": "a" * 81}, {"password": "short"},
                    {"password": "a" * 257}, {"status": "INVALID"}, {"role": "ADMIN"},
                    {"unexpected": "value"}, {"username": "valid", "password": "short"})
        for payload in payloads:
            with self.subTest(payload=payload):
                response = self.patch_account(self.user["id"], payload)
                self.assertEqual(response.status_code, 422, response.text)
        for payload in (
            {"username": "newuser", "password": self.NEW_PASSWORD, "role": "ADMIN"},
            {"username": "   ", "password": self.NEW_PASSWORD},
            {"username": "newuser", "password": "short"},
        ):
            with self.subTest(create=payload):
                response = self.client.post("/api/admin/accounts", headers=self.admin_headers, json=payload)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(before_accounts, self.database_rows("SELECT * FROM user_accounts ORDER BY id"))
        self.assertEqual(before_sessions, self.database_rows("SELECT * FROM sessions ORDER BY id"))
        self.assertEqual(before_logs, self.database_rows("SELECT * FROM operation_logs ORDER BY id"))
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(token)).status_code, 200)

    def test_missing_account_updates_and_deletes_return_404(self):
        account_id = str(uuid.uuid4())
        self.assertEqual(self.patch_account(account_id, {"username": "missing"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/admin/accounts/{account_id}", headers=self.admin_headers).status_code, 404)

    def test_all_administrative_writes_are_audited_by_admin(self):
        def administrative_logs():
            return self.database_rows("SELECT id, actor_id, details FROM operation_logs WHERE actor_id = ?", (self.admin["id"],))

        before = {row["id"] for row in administrative_logs()}
        created = self.create_user("audited")
        after_creation = administrative_logs()
        creation_logs = [row for row in after_creation if row["id"] not in before]
        self.assertTrue(creation_logs)
        self.assertTrue(any(created["id"] in row["details"] for row in creation_logs))
        operations = (
            lambda: self.patch_account(created["id"], {"username": "audited-renamed"}),
            lambda: self.patch_account(created["id"], {"password": self.NEW_PASSWORD}),
            lambda: self.patch_account(created["id"], {"status": "DISABLED"}),
            lambda: self.patch_account(created["id"], {"status": "ACTIVE"}),
            lambda: self.client.delete(f"/api/admin/accounts/{created['id']}", headers=self.admin_headers),
        )
        for operation in operations:
            before = {row["id"] for row in administrative_logs()}
            response = operation()
            self.assertIn(response.status_code, (200, 204), response.text)
            added = [row for row in administrative_logs() if row["id"] not in before]
            self.assertTrue(added)
            self.assertTrue(any(created["id"] in row["details"] for row in added))
            for row in added:
                self.assertNotIn(self.USER_PASSWORD, row["details"])
                self.assertNotIn(self.NEW_PASSWORD, row["details"])

    def test_legacy_migration_preserves_accounts_sessions_and_audit_and_is_idempotent(self):
        from datetime import datetime, timedelta, timezone
        from backend.app.accounts.service import list_accounts, resolve_session
        from backend.app.core.db import connect, initialize_database
        from backend.app.core.security import digest_session_token, hash_password

        legacy_path = self.database_path.with_name("legacy.sqlite3")
        password_hash = hash_password(self.ADMIN_PASSWORD)
        token = "legacy-session-token-fixture"
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        account_values = ("legacy-admin", "LegacyAdmin", password_hash, "ADMIN", "ACTIVE", created_at, created_at)
        session_values = ("legacy-session", "legacy-admin", digest_session_token(token), created_at, expires_at, None)
        log_values = ("legacy-log", "legacy-admin", "LOGIN_SUCCEEDED", "INFO", "{}", created_at)
        legacy = sqlite3.connect(legacy_path)
        try:
            legacy.executescript("""
                CREATE TABLE user_accounts (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('ADMIN', 'USER')),
                    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL REFERENCES user_accounts(id),
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE TABLE operation_logs (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT REFERENCES user_accounts(id),
                    event_code TEXT NOT NULL,
                    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
                    details TEXT NOT NULL DEFAULT '',
                    occurred_at TEXT NOT NULL
                );
            """)
            legacy.execute("INSERT INTO user_accounts VALUES (?, ?, ?, ?, ?, ?, ?)", account_values)
            legacy.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)", session_values)
            legacy.execute("INSERT INTO operation_logs VALUES (?, ?, ?, ?, ?, ?)", log_values)
            legacy.commit()
        finally:
            legacy.close()

        initialize_database(legacy_path)
        initialize_database(legacy_path)
        migrated = connect(legacy_path)
        try:
            row = migrated.execute("SELECT * FROM user_accounts WHERE id = 'legacy-admin'").fetchone()
            original_fields = ("id", "username", "password_hash", "role", "status", "created_at", "updated_at")
            self.assertEqual(tuple(row[field] for field in original_fields), account_values)
            self.assertIsNone(row["deleted_at"])
            self.assertEqual(tuple(migrated.execute("SELECT * FROM sessions").fetchone()), session_values)
            self.assertEqual(tuple(migrated.execute("SELECT * FROM operation_logs").fetchone()), log_values)
            self.assertEqual(resolve_session(migrated, token), {"id": "legacy-admin", "username": "LegacyAdmin", "role": "ADMIN"})
            self.assertEqual(len(list_accounts(migrated)), 1)
            self.assertEqual(list(migrated.execute("PRAGMA foreign_key_check")), [])
            columns = [column["name"] for column in migrated.execute("PRAGMA table_info(user_accounts)")]
            self.assertEqual(columns.count("deleted_at"), 1)
        finally:
            migrated.close()

    def test_direct_services_enforce_admin_protection_and_authorization(self):
        from backend.app.accounts.service import (
            AccountProtectionError, delete_account, provision_account, update_account,
        )
        from backend.app.core.db import connect

        before_accounts = self.database_rows("SELECT * FROM user_accounts ORDER BY id")
        before_sessions = self.database_rows("SELECT * FROM sessions ORDER BY id")
        before_logs = self.database_rows("SELECT * FROM operation_logs ORDER BY id")
        connection = connect(self.database_path)
        try:
            forbidden = (
                lambda: update_account(connection, self.admin["id"], {"status": "DISABLED"}, self.admin["id"]),
                lambda: delete_account(connection, self.admin["id"], self.admin["id"]),
                lambda: update_account(connection, self.user["id"], {"username": "unauthorized"}, self.user["id"]),
                lambda: delete_account(connection, self.user["id"], self.user["id"]),
                lambda: provision_account(connection, "unauthorized", self.NEW_PASSWORD, "USER", actor_id=self.user["id"]),
            )
            for operation in forbidden:
                with self.assertRaises(AccountProtectionError):
                    operation()
            with self.assertRaises(ValueError):
                update_account(connection, self.admin["id"], {"role": "USER"}, self.admin["id"])
        finally:
            connection.close()
        self.assertEqual(before_accounts, self.database_rows("SELECT * FROM user_accounts ORDER BY id"))
        self.assertEqual(before_sessions, self.database_rows("SELECT * FROM sessions ORDER BY id"))
        self.assertEqual(before_logs, self.database_rows("SELECT * FROM operation_logs ORDER BY id"))
        self.assertEqual(self.client.get("/api/auth/me", headers=self.admin_headers).status_code, 200)

    def test_concurrent_old_password_login_cannot_survive_password_reset(self):
        import threading
        from backend.app.accounts import service
        from backend.app.core.db import connect

        verification_started = threading.Event()
        verification_release = threading.Event()
        reset_attempted = threading.Event()
        reset_finished = threading.Event()
        original_verify = service.verify_password
        results = {}
        errors = []

        def paused_verify(password, encoded):
            verification_started.set()
            if not verification_release.wait(4):
                raise RuntimeError("Timed out waiting to release credential verification")
            return original_verify(password, encoded)

        def login_worker():
            connection = connect(self.database_path)
            try:
                _, token, _ = service.authenticate_and_issue_session(connection, "user1", self.USER_PASSWORD, 60)
                results["token"] = token
            except Exception as error:
                errors.append(("login", repr(error)))
            finally:
                connection.close()

        def reset_worker():
            connection = connect(self.database_path)
            try:
                reset_attempted.set()
                service.update_account(connection, self.user["id"], {"password": self.NEW_PASSWORD}, self.admin["id"])
            except Exception as error:
                errors.append(("reset", repr(error)))
            finally:
                connection.close()
                reset_finished.set()

        threads = []
        with patch("backend.app.accounts.service.verify_password", side_effect=paused_verify):
            try:
                login_thread = threading.Thread(target=login_worker, daemon=True)
                login_thread.start()
                threads.append(login_thread)
                self.assertTrue(verification_started.wait(2), "Old-password login did not reach verification")
                reset_thread = threading.Thread(target=reset_worker, daemon=True)
                reset_thread.start()
                threads.append(reset_thread)
                self.assertTrue(reset_attempted.wait(2), "Reset worker did not start")
                # Without serialization, reset completes before the paused login
                # creates its token; that token would then escape revocation.
                reset_finished.wait(0.2)
            finally:
                verification_release.set()
                for thread in threads:
                    thread.join(7)
        self.assertTrue(all(not thread.is_alive() for thread in threads), "Account workers did not finish")
        self.assertEqual(errors, [])
        self.assertIn("token", results)
        self.assertTrue(reset_finished.is_set())
        self.assertEqual(self.client.get("/api/auth/me", headers=self.headers(results["token"])).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "username": "user1", "password": self.USER_PASSWORD,
        }).status_code, 401)
        self.login("user1", self.NEW_PASSWORD)

if __name__ == "__main__":
    unittest.main()
