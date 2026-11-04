"""HTTP-level authorization checks; run after installing requirements.txt."""
import os
import tempfile
import unittest
from importlib.util import find_spec

if find_spec("fastapi") and find_spec("httpx"):
    from fastapi.testclient import TestClient
else:
    TestClient = None


@unittest.skipIf(TestClient is None, "Install requirements.txt to run HTTP integration tests")
class ApiAuthorizationTests(unittest.TestCase):
    def setUp(self):
        from backend.app.accounts.service import provision_account
        from backend.app.core.db import connect, initialize_database

        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_data_dir = os.environ.get("STORMTRACK_DATA_DIR")
        os.environ["STORMTRACK_DATA_DIR"] = self.temp_dir.name
        initialize_database(__import__("pathlib").Path(self.temp_dir.name) / "stormtrack.sqlite3")
        db = connect(__import__("pathlib").Path(self.temp_dir.name) / "stormtrack.sqlite3")
        provision_account(db, "admin", "Admin!Password2026", "ADMIN")
        provision_account(db, "user1", "User!Password2026-1", "USER")
        db.close()

        from backend.app.api.main import app
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        if self.previous_data_dir is None:
            os.environ.pop("STORMTRACK_DATA_DIR", None)
        else:
            os.environ["STORMTRACK_DATA_DIR"] = self.previous_data_dir
        self.temp_dir.cleanup()

    def token(self, username, password):
        response = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200)
        return response.json()["access_token"]

    def test_local_frontend_is_served_without_external_assets(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("StormTrack", response.text)
        self.assertIn("desligada por padrão", response.text)
        self.assertEqual(self.client.get("/app.js").status_code, 200)
        self.assertEqual(self.client.get("/styles.css").status_code, 200)

    def test_user_cannot_configure_source_and_session_revokes(self):
        user_token = self.token("user1", "User!Password2026-1")
        headers = {"Authorization": f"Bearer {user_token}"}
        response = self.client.post("/api/admin/source-products", headers=headers, json={
            "provider_code": "NOAA", "source_name": "NOAA", "product_code": "GOES-19-ABI"
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/source-products").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/logout", headers=headers).status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

    def test_observation_and_readiness_routes_are_authenticated_and_never_invent_alerts(self):
        self.assertEqual(self.client.get("/api/observations/geojson").status_code, 401)
        user_token = self.token("user1", "User!Password2026-1")
        headers = {"Authorization": f"Bearer {user_token}"}
        collection = self.client.get("/api/observations/geojson", headers=headers).json()
        self.assertEqual(collection["features"], [])
        self.assertEqual(collection["metadata"]["data_state"], "NO_OBSERVATIONS")
        self.assertEqual(self.client.get("/api/alerts", headers=headers).json()["status"], "NOT_ISSUED")
        methods = self.client.get("/api/analysis/status", headers=headers).json()
        self.assertEqual(methods["status"], "NOT_OPERATIONAL")

    def test_startup_seeds_only_pending_source_candidates(self):
        admin_token = self.token("admin", "Admin!Password2026")
        products = self.client.get("/api/source-products", headers={"Authorization": f"Bearer {admin_token}"}).json()
        glm = next(item for item in products if item["product_code"] == "GLM-L2-LCFA")
        self.assertFalse(glm["enabled"])
        self.assertEqual(glm["access_status"], "PENDING")

    def test_new_source_stays_pending_until_admin_verifies_gates(self):
        admin_token = self.token("admin", "Admin!Password2026")
        headers = {"Authorization": f"Bearer {admin_token}"}
        created = self.client.post("/api/admin/source-products", headers=headers, json={
            "provider_code": "NOAA", "source_name": "NOAA", "product_code": "GOES-19-ABI"
        })
        self.assertEqual(created.status_code, 201)
        product = created.json()
        self.assertFalse(product["enabled"])
        self.assertEqual(product["access_status"], "PENDING")
        changed = self.client.patch(f"/api/admin/source-products/{product['id']}", headers=headers, json={
            "access_status": "VERIFIED", "collection_status": "VERIFIED",
            "storage_status": "VERIFIED", "terms_reference": "review-001", "enabled": True
        })
        self.assertEqual(changed.status_code, 200)
        self.assertTrue(changed.json()["enabled"])
        self.assertEqual(changed.json()["redistribution_status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
