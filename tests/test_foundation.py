import tempfile
import unittest
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.accounts.service import (
    AccountConflictError,
    AccountLimitError,
    AuthenticationError,
    authenticate_and_issue_session,
    provision_account,
    revoke_session,
    resolve_session,
)
from backend.app.core.db import connect, initialize_database
from backend.app.core.security import hash_password, verify_password
from backend.app.sources.policy import CollectionGate, GateStatus, collection_is_allowed, redistribution_is_allowed
from backend.app.sources.service import create_source_product, list_source_products, update_source_product


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        initialize_database(self.db_path)
        self.db = connect(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_password_hash_is_not_plaintext_and_verifies(self):
        encoded = hash_password("StormTrack!Local2026")
        self.assertNotEqual(encoded, "StormTrack!Local2026")
        self.assertTrue(verify_password("StormTrack!Local2026", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))

    def test_account_policy_allows_one_admin_and_four_users_only(self):
        admin = provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        self.assertEqual(admin["role"], "ADMIN")
        with self.assertRaises(AccountConflictError):
            provision_account(self.db, "admin2", "Another!Password2026", "ADMIN")
        for n in range(1, 5):
            provision_account(self.db, f"user{n}", f"User!Password2026-{n}", "USER")
        with self.assertRaises(AccountLimitError):
            provision_account(self.db, "user5", "User!Password2026-5", "USER")
        count = self.db.execute("SELECT COUNT(*) FROM user_accounts").fetchone()[0]
        self.assertEqual(count, 5)

    def test_cli_provisioning_log_does_not_attribute_creation_to_the_new_account(self):
        provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        log = self.db.execute(
            "SELECT actor_id, event_code FROM operation_logs WHERE event_code = 'ACCOUNT_PROVISIONED'"
        ).fetchone()
        self.assertIsNone(log["actor_id"])

    def test_duplicate_username_is_case_insensitive(self):
        provision_account(self.db, "Admin", "Admin!Password2026", "ADMIN")
        with self.assertRaises(AccountConflictError):
            provision_account(self.db, "admin", "Another!Password2026", "USER")

    def test_session_stores_digest_and_rejects_bad_credentials(self):
        admin = provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        account, token, _ = authenticate_and_issue_session(self.db, "admin", "Admin!Password2026", 60)
        self.assertEqual(account["id"], admin["id"])
        row = self.db.execute("SELECT token_hash FROM sessions").fetchone()
        self.assertNotEqual(row["token_hash"], token)
        self.assertEqual(resolve_session(self.db, token)["role"], "ADMIN")
        revoke_session(self.db, token)
        self.assertIsNone(resolve_session(self.db, token))
        with self.assertRaises(AuthenticationError):
            authenticate_and_issue_session(self.db, "admin", "bad-password", 60)

    def test_disabled_account_and_expired_session_are_rejected(self):
        account = provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        _, token, _ = authenticate_and_issue_session(self.db, "admin", "Admin!Password2026", 60)
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        self.db.execute("UPDATE sessions SET expires_at = ? WHERE account_id = ?", (expired, account["id"]))
        self.assertIsNone(resolve_session(self.db, token))
        _, disabled_token, _ = authenticate_and_issue_session(self.db, "admin", "Admin!Password2026", 60)
        self.db.execute("UPDATE user_accounts SET status = 'DISABLED' WHERE id = ?", (account["id"],))
        self.assertIsNone(resolve_session(self.db, disabled_token))

    def test_source_product_defaults_pending_and_disabled(self):
        product = create_source_product(self.db, "NOAA", "NOAA", "GOES-19-ABI")
        row = list_source_products(self.db)[0]
        self.assertEqual(product["access_status"], "PENDING")
        self.assertFalse(product["enabled"])
        self.assertEqual(row["collection_status"], "PENDING")
        self.assertFalse(row["enabled"])

    def test_whitespace_evidence_is_normalized_and_cannot_authorize_a_product(self):
        product = create_source_product(self.db, "NOAA", "NOAA", "GOES-19-ABI", "   ")
        row = self.db.execute(
            "SELECT terms_reference FROM source_products WHERE id = ?", (product["id"],)
        ).fetchone()
        self.assertIsNone(row["terms_reference"])
        with self.assertRaisesRegex(ValueError, "evidence reference"):
            update_source_product(self.db, product["id"], {
                "access_status": "VERIFIED",
                "collection_status": "VERIFIED",
                "storage_status": "VERIFIED",
                "terms_reference": "   ",
                "enabled": True,
            }, "audit-admin")

    def test_database_rejects_enabling_source_without_verified_gates_and_evidence(self):
        product = create_source_product(self.db, "NOAA", "NOAA", "GOES-19-ABI")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "require evidence"):
            self.db.execute(
                "UPDATE source_products SET enabled = 1, terms_reference = '   ' WHERE id = ?",
                (product["id"],),
            )

    def test_duplicate_product_does_not_leave_partial_source_or_log(self):
        admin = provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        create_source_product(self.db, "NOAA", "NOAA", "GOES-19-ABI", actor_id=admin["id"])
        logs_before = self.db.execute("SELECT COUNT(*) FROM operation_logs").fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            create_source_product(self.db, "NOAA", "NOAA", "GOES-19-ABI", actor_id=admin["id"])
        logs_after = self.db.execute("SELECT COUNT(*) FROM operation_logs").fetchone()[0]
        self.assertEqual(logs_before, logs_after)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM source_products").fetchone()[0], 1)

    def test_source_product_cannot_be_enabled_before_all_local_use_gates(self):
        admin = provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        product = create_source_product(self.db, "NOAA", "NOAA", "GOES-19-ABI", actor_id=admin["id"])
        with self.assertRaises(ValueError):
            update_source_product(self.db, product["id"], {"enabled": True}, admin["id"])
        with self.assertRaises(ValueError):
            update_source_product(self.db, product["id"], {"access_status": "VERIFIED"}, admin["id"])
        row = next(p for p in list_source_products(self.db) if p["id"] == product["id"])
        self.assertFalse(row["enabled"])
        self.assertEqual(row["access_status"], "PENDING")

    def test_admin_gate_update_is_audited_and_requires_evidence_to_enable(self):
        admin = provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        product = create_source_product(self.db, "NOAA", "NOAA", "GOES-19-ABI", actor_id=admin["id"])
        updated = update_source_product(
            self.db, product["id"],
            {"access_status": "VERIFIED", "collection_status": "VERIFIED",
             "storage_status": "VERIFIED", "terms_reference": "official-terms-review-001",
             "enabled": True},
            admin["id"],
        )
        self.assertTrue(updated["enabled"])
        self.assertEqual(updated["redistribution_status"], "PENDING")
        log = self.db.execute(
            "SELECT event_code FROM operation_logs WHERE event_code = 'SOURCE_PRODUCT_UPDATED'"
        ).fetchone()
        self.assertIsNotNone(log)

    def test_unrelated_gate_update_does_not_rewrite_access_verification_time(self):
        admin = provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        product = create_source_product(self.db, "NOAA", "NOAA", "GOES-19-ABI", actor_id=admin["id"])
        update_source_product(self.db, product["id"], {
            "access_status": "VERIFIED",
            "collection_status": "VERIFIED",
            "storage_status": "VERIFIED",
            "terms_reference": "official-terms-review-001",
            "enabled": True,
        }, admin["id"])
        original = "2000-01-01T00:00:00+00:00"
        self.db.execute(
            "UPDATE source_products SET access_verified_at = ? WHERE id = ?", (original, product["id"])
        )
        update_source_product(self.db, product["id"], {
            "redistribution_status": "VERIFIED",
        }, admin["id"])
        stored = self.db.execute(
            "SELECT access_verified_at FROM source_products WHERE id = ?", (product["id"],)
        ).fetchone()["access_verified_at"]
        self.assertEqual(stored, original)

    def test_collection_requires_access_collection_storage_and_enabled(self):
        ready = CollectionGate(GateStatus.VERIFIED, GateStatus.VERIFIED, GateStatus.VERIFIED,
                               GateStatus.PENDING, True)
        self.assertTrue(collection_is_allowed(ready))
        self.assertFalse(redistribution_is_allowed(ready))
        disabled = CollectionGate(GateStatus.VERIFIED, GateStatus.VERIFIED, GateStatus.VERIFIED,
                                  GateStatus.VERIFIED, False)
        self.assertFalse(collection_is_allowed(disabled))
        pending = CollectionGate(GateStatus.VERIFIED, GateStatus.PENDING, GateStatus.VERIFIED,
                                 GateStatus.VERIFIED, True)
        self.assertFalse(collection_is_allowed(pending))


if __name__ == "__main__":
    unittest.main()
