import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app.adapters.noaa_goes19_glm import (
    AdapterError, SourceObject, _hour_prefixes, _time_from_key, list_recent_objects, normalize_flashes,
)
from backend.app.core.db import connect, initialize_database
from backend.app.observations.service import observations_geojson
from backend.app.sources.candidates import ensure_candidate_products
from backend.app.sources.service import list_source_products, update_source_product
from backend.app.ingestion.service import collect_goes19_glm


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "stormtrack.sqlite3"
        initialize_database(self.path)
        self.db = connect(self.path)
        ensure_candidate_products(self.db)
        self.product = next(p for p in list_source_products(self.db)
                            if p["provider_code"] == "NOAA" and p["product_code"] == "GLM-L2-LCFA")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_candidates_are_seeded_pending_and_disabled(self):
        products = list_source_products(self.db)
        self.assertGreaterEqual(len(products), 7)
        for product in products:
            self.assertFalse(product["enabled"])
            self.assertEqual(product["access_status"], "PENDING")
            self.assertEqual(product["collection_status"], "PENDING")
            self.assertIsNone(product["terms_reference"])
        self.assertEqual(self.product["integration_status"], "ADAPTER_IMPLEMENTED_NOT_CONNECTED")
        other = next(p for p in products if p["provider_code"] == "SIMEPAR")
        self.assertEqual(other["integration_status"], "CONNECTOR_SCAFFOLD_PENDING_SOURCE_PROFILE")
        abi = next(p for p in products if p["provider_code"] == "NOAA" and p["product_code"] == "ABI-L2-MCMIPF")
        self.assertEqual(abi["integration_status"], "DIRECT_IN_APP_IMAGES_ACTIVE_NO_ARCHIVE")
        ensure_candidate_products(self.db)
        self.assertEqual(len(products), len(list_source_products(self.db)))

    def test_key_time_and_hour_prefixes_are_utc(self):
        key = "GLM-L2-LCFA/2026/277/22/OR_GLM-L2-LCFA_G19_s20262772215342_e20262772215362_c20262772215400.nc"
        self.assertEqual(_time_from_key(key), "2026-10-04T22:15:34.200Z")
        prefixes = _hour_prefixes(datetime(2026, 10, 4, 22, 15, tzinfo=timezone.utc))
        self.assertEqual(prefixes, ["GLM-L2-LCFA/2026/277/22/"])
        boundary = _hour_prefixes(datetime(2026, 10, 4, 22, 2, tzinfo=timezone.utc))
        self.assertEqual(boundary, ["GLM-L2-LCFA/2026/277/22/", "GLM-L2-LCFA/2026/277/21/"])

    def test_normalizer_emits_only_valid_observed_coordinates(self):
        geometry = normalize_flashes([-51.9, -54.0, 999.0, float("nan")], [-23.4, -28.0, 10, -25])
        self.assertEqual(geometry["type"], "FeatureCollection")
        self.assertEqual(len(geometry["features"]), 2)
        self.assertEqual(geometry["features"][0]["geometry"]["coordinates"], [-51.9, -23.4])
        with self.assertRaisesRegex(Exception, "different lengths"):
            normalize_flashes([-50], [])

    def test_truncated_object_catalog_fails_closed(self):
        xml = b"<ListBucketResult><IsTruncated>true</IsTruncated></ListBucketResult>"
        with patch("backend.app.adapters.noaa_goes19_glm._request_bytes", return_value=xml):
            with self.assertRaisesRegex(AdapterError, "truncated|bounded page"):
                list_recent_objects(now=datetime(2026, 10, 4, 22, 15, tzinfo=timezone.utc))

    def test_object_window_over_limit_fails_instead_of_dropping_old_files(self):
        entries = []
        for index in range(31):
            second = 10 + index
            key = ("GLM-L2-LCFA/2026/277/22/OR_GLM-L2-LCFA_G19_"
                   f"s20262772215{second:02d}0_e20262772215{second:02d}2_c20262772215{second:02d}3.nc")
            entries.append(f"<Contents><Key>{key}</Key><Size>1024</Size><LastModified>2026-10-04T22:16:00Z</LastModified></Contents>")
        xml = ("<ListBucketResult><IsTruncated>false</IsTruncated>" + "".join(entries) + "</ListBucketResult>").encode()
        with patch("backend.app.adapters.noaa_goes19_glm._request_bytes", return_value=xml):
            with self.assertRaisesRegex(AdapterError, "object limit"):
                list_recent_objects(now=datetime(2026, 10, 4, 22, 16, tzinfo=timezone.utc), max_objects=30)

    def test_gates_block_collection_before_any_source_request(self):
        with patch("backend.app.ingestion.service.glm.list_recent_objects") as listing:
            result = collect_goes19_glm(self.db, self.product["id"])
        listing.assert_not_called()
        self.assertEqual(result["status"], "BLOCKED")
        row = self.db.execute("SELECT status,error_code FROM collection_runs").fetchone()
        self.assertEqual(row["status"], "BLOCKED")
        self.assertEqual(row["error_code"], "SOURCE_GATES_NOT_PASSED")

    def test_recent_window_is_rescanned_to_capture_late_objects_behind_cursor(self):
        update_source_product(self.db, self.product["id"], {
            "access_status": "VERIFIED", "collection_status": "VERIFIED",
            "storage_status": "VERIFIED", "terms_reference": "review-001", "enabled": True,
        }, None)
        later_key = "GLM-L2-LCFA/2026/277/22/OR_GLM-L2-LCFA_G19_s20262772215400_e20262772215420_c20262772215440.nc"
        earlier_key = "GLM-L2-LCFA/2026/277/22/OR_GLM-L2-LCFA_G19_s20262772215342_e20262772215362_c20262772215400.nc"
        self.db.execute(
            "INSERT INTO ingestion_cursors(product_id,last_object_key,updated_at) VALUES(?,?,?)",
            (self.product["id"], later_key, "2026-10-04T22:16:00Z"),
        )
        item = SourceObject(earlier_key, 1024, "2026-10-04T22:15:40Z", "2026-10-04T22:15:34.200Z")
        parsed = {"flash_count": 1, "geometry": normalize_flashes([-51.9], [-23.4])}
        with patch("backend.app.ingestion.service.glm.list_recent_objects", return_value=[item]) as listing, \
             patch("backend.app.ingestion.service.glm.download_object", return_value=b"bounded sample"), \
             patch("backend.app.ingestion.service.glm.parse_netcdf", return_value=parsed):
            result = collect_goes19_glm(self.db, self.product["id"])
        self.assertIsNone(listing.call_args.kwargs["after_key"])
        self.assertEqual(result["observations_written"], 1)

    def test_approved_glm_product_is_persisted_and_exposed_as_observations(self):
        update_source_product(self.db, self.product["id"], {
            "access_status": "VERIFIED", "collection_status": "VERIFIED",
            "storage_status": "VERIFIED", "terms_reference": "NOAA Registry + GOES Readme",
            "enabled": True,
        }, None)
        item = SourceObject(
            "GLM-L2-LCFA/2026/277/22/OR_GLM-L2-LCFA_G19_s20262772215342_e20262772215362_c20262772215400.nc",
            1024, "2026-10-04T22:15:40Z", "2026-10-04T22:15:34.200Z",
        )
        parsed = {"flash_count": 1, "geometry": normalize_flashes([-51.9], [-23.4])}
        with patch("backend.app.ingestion.service.glm.list_recent_objects", return_value=[item]), \
             patch("backend.app.ingestion.service.glm.download_object", return_value=b"bounded sample"), \
             patch("backend.app.ingestion.service.glm.parse_netcdf", return_value=parsed):
            result = collect_goes19_glm(self.db, self.product["id"])
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["observations_written"], 1)
        collection = observations_geojson(self.db)
        self.assertEqual(len(collection["features"]), 1)
        self.assertEqual(collection["features"][0]["geometry"]["coordinates"], [-51.9, -23.4])
        quality = self.db.execute("SELECT completeness,availability FROM data_quality_assessments").fetchone()
        self.assertIsNone(quality["completeness"])
        self.assertEqual(quality["availability"], "AVAILABLE")


if __name__ == "__main__":
    unittest.main()
