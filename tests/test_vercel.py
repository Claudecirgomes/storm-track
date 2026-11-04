"""Cloud startup must not create disposable SQLite databases or run migrations."""
import os
import unittest
from unittest.mock import patch

from backend.app.core.config import get_settings


class VercelConfigurationTests(unittest.TestCase):
    def test_cloud_rejects_sqlite_fallback(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "STORMTRACK_DATABASE_URL"):
                get_settings()

    def test_cloud_rejects_continuous_collector(self):
        with patch.dict(os.environ, {
            "VERCEL": "1", "STORMTRACK_DATABASE_URL": "postgresql://example.invalid/postgres",
            "STORMTRACK_COLLECTION_ENABLED": "true",
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "separate worker"):
                get_settings()

    def test_cloud_boot_serves_frontend_without_schema_writes_or_db_connection(self):
        from fastapi.testclient import TestClient
        from app import app
        with patch.dict(os.environ, {
            "VERCEL": "1", "STORMTRACK_DATABASE_URL": "postgresql://example.invalid/postgres",
        }, clear=True), patch("backend.app.api.main.initialize_database") as initialize, \
                patch("backend.app.api.main.ensure_candidate_products") as seed, \
                patch("backend.app.api.main.connect") as connect:
            with TestClient(app) as client:
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("StormTrack", response.text)
                self.assertEqual(client.get("/console.css").status_code, 200)
                self.assertEqual(client.get("/app.js").status_code, 200)
                self.assertIsNone(app.state.collection_task)
            initialize.assert_not_called()
            seed.assert_not_called()
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
