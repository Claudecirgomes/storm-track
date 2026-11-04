import tempfile
import unittest
import sqlite3
from pathlib import Path

from backend.app.accounts.service import provision_account
from backend.app.core.db import connect, initialize_database
from backend.app.observations.service import (
    IngestionBlocked, ingest_observation, record_data_quality, record_source_health,
)
from backend.app.sources.service import create_source_product, update_source_product


class ObservationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "stormtrack.sqlite3"
        initialize_database(database_path)
        self.db = connect(database_path)
        admin = provision_account(self.db, "admin", "Admin!Password2026", "ADMIN")
        product = create_source_product(self.db, "NOAA", "NOAA", "TEST-PRODUCT", actor_id=admin["id"])
        self.product_id = product["id"]
        self.source_id = self.db.execute("SELECT source_id FROM source_products WHERE id = ?", (self.product_id,)).fetchone()[0]
        self.admin_id = admin["id"]

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def authorize_local_collection(self):
        return update_source_product(self.db, self.product_id, {
            "access_status": "VERIFIED",
            "collection_status": "VERIFIED",
            "storage_status": "VERIFIED",
            "terms_reference": "review:TEST-PRODUCT-001",
            "enabled": True,
        }, self.admin_id)

    def observation(self, payload=None, timestamp="2026-10-04T16:00:00-03:00"):
        return ingest_observation(
            self.db, self.product_id,
            observed_at=timestamp,
            deduplication_key="scan-20261004T1600",
            data_type="IR_BAND",
            normalized_payload=payload if payload is not None else {"brightness_temperature_k": 230.0},
            geometry={"type": "Point", "coordinates": [-51.94, -23.42]},
            original_unit="K",
            raw_reference="local-test-fixture",
        )

    def test_pending_product_cannot_ingest(self):
        with self.assertRaises(IngestionBlocked):
            self.observation()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)

    def test_blank_evidence_cannot_be_used_by_internal_ingestion(self):
        # Simulate a malformed legacy/direct database write; the ingestion boundary must fail closed.
        self.db.execute(
            "UPDATE source_products SET access_status='VERIFIED', collection_status='VERIFIED', "
            "storage_status='VERIFIED', terms_reference='   ', enabled=0 WHERE id=?",
            (self.product_id,),
        )
        with self.assertRaises(IngestionBlocked):
            self.observation()

    def test_timestamp_requires_offset_and_preserves_original(self):
        self.authorize_local_collection()
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            self.observation(timestamp="2026-10-04T16:00:00")
        created = self.observation()
        stored = self.db.execute(
            "SELECT observed_at_utc, original_timestamp, original_offset FROM observations WHERE artifact_id = ?",
            (created["observation_id"],),
        ).fetchone()
        self.assertEqual(stored["observed_at_utc"], "2026-10-04T19:00:00.000000Z")
        self.assertEqual(stored["original_timestamp"], "2026-10-04T16:00:00-03:00")
        self.assertEqual(stored["original_offset"], "-03:00")

    def test_same_product_key_and_content_is_idempotent(self):
        self.authorize_local_collection()
        first = self.observation({"a": 1, "b": 2})
        duplicate = self.observation({"b": 2, "a": 1})
        self.assertEqual(first["status"], "CREATED")
        self.assertEqual(duplicate["status"], "DUPLICATE_IGNORED")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM observation_revisions").fetchone()[0], 1)

    def test_changed_content_appends_revision_without_replacing_history(self):
        self.authorize_local_collection()
        first = self.observation({"brightness_temperature_k": 230.0})
        revised = self.observation({"brightness_temperature_k": 228.0}, timestamp="2026-10-04T16:05:00-03:00")
        self.assertEqual(revised["status"], "REVISION_APPENDED")
        self.assertEqual(revised["observation_id"], first["observation_id"])
        rows = self.db.execute(
            "SELECT revision_number, normalized_payload_json, observed_at_utc, original_timestamp "
            "FROM observation_revisions "
            "WHERE observation_id = ? ORDER BY revision_number", (first["observation_id"],),
        ).fetchall()
        self.assertEqual([row["revision_number"] for row in rows], [1, 2])
        self.assertIn("230.0", rows[0]["normalized_payload_json"])
        self.assertIn("228.0", rows[1]["normalized_payload_json"])
        self.assertEqual(rows[0]["observed_at_utc"], "2026-10-04T19:00:00.000000Z")
        self.assertEqual(rows[1]["observed_at_utc"], "2026-10-04T19:05:00.000000Z")
        self.assertEqual(rows[1]["original_timestamp"], "2026-10-04T16:05:00-03:00")

    def test_observation_revision_rows_cannot_be_updated_or_deleted(self):
        self.authorize_local_collection()
        created = self.observation()
        revision_id = self.db.execute(
            "SELECT id FROM observation_revisions WHERE observation_id = ?",
            (created["observation_id"],),
        ).fetchone()["id"]
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.db.execute(
                "UPDATE observation_revisions SET normalized_payload_json = '{}' WHERE id = ?",
                (revision_id,),
            )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.db.execute("DELETE FROM observation_revisions WHERE id = ?", (revision_id,))

    def test_provenance_rows_are_append_only_in_sqlite(self):
        self.authorize_local_collection()
        created = self.observation()
        record_data_quality(
            self.db, created["observation_id"], completeness=None,
            delay_seconds=None, availability="UNKNOWN",
        )
        record_source_health(self.db, self.source_id, "AVAILABLE")
        rows = [
            ("data_artifacts", "id", created["observation_id"]),
            ("observations", "artifact_id", created["observation_id"]),
            ("observation_revisions", "id", self.db.execute(
                "SELECT id FROM observation_revisions WHERE observation_id = ?",
                (created["observation_id"],),
            ).fetchone()["id"]),
            ("data_quality_assessments", "id", self.db.execute(
                "SELECT id FROM data_quality_assessments WHERE observation_id = ?",
                (created["observation_id"],),
            ).fetchone()["id"]),
            ("source_health", "id", self.db.execute(
                "SELECT id FROM source_health WHERE source_id = ?", (self.source_id,)
            ).fetchone()["id"]),
        ]
        for table, key, row_id in rows:
            with self.subTest(table=table):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute(f"UPDATE {table} SET {key} = {key} WHERE {key} = ?", (row_id,))
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute(f"DELETE FROM {table} WHERE {key} = ?", (row_id,))

    def test_unknown_quality_stays_unknown_and_invalid_range_is_rejected(self):
        self.authorize_local_collection()
        created = self.observation()
        record_data_quality(self.db, created["observation_id"], completeness=None,
                            delay_seconds=None, availability="UNKNOWN")
        row = self.db.execute("SELECT completeness, delay_seconds, availability FROM data_quality_assessments").fetchone()
        self.assertIsNone(row["completeness"])
        self.assertIsNone(row["delay_seconds"])
        self.assertEqual(row["availability"], "UNKNOWN")
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            record_data_quality(self.db, created["observation_id"], completeness=1.2,
                                delay_seconds=0, availability="AVAILABLE")

    def test_source_health_keeps_failure_reason(self):
        record_source_health(self.db, self.source_id, "UNAVAILABLE", "fixture offline")
        row = self.db.execute("SELECT status, failure_reason FROM source_health").fetchone()
        self.assertEqual(row["status"], "UNAVAILABLE")
        self.assertEqual(row["failure_reason"], "fixture offline")


if __name__ == "__main__":
    unittest.main()
