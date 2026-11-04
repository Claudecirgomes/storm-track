import unittest
from unittest.mock import patch

from backend.app.adapters import noaa_goes19_abi
from backend.app.adapters.noaa_goes19_abi import SatelliteSourceError, _fetch_index, fetch_frame, viewer_metadata
from backend.app.adapters.pending_source import SourceProfileRequired
from backend.app.adapters.registry import PENDING_CONNECTORS, connector_catalog


class ConnectorPreparationTests(unittest.TestCase):
    def test_regional_connectors_fail_closed_until_source_profile_is_approved(self):
        self.assertEqual(len(PENDING_CONNECTORS), 5)
        for connector in PENDING_CONNECTORS:
            with self.subTest(product=connector.profile.product_code):
                with self.assertRaises(SourceProfileRequired):
                    connector.fetch()

    def test_catalog_marks_only_bounded_noaa_image_display_active(self):
        catalog = connector_catalog()
        indexed = {(row["provider_code"], row["product_code"]): row for row in catalog}
        expected = {
            ("NOAA", "ABI-L2-MCMIPF"),
            ("NOAA", "GLM-L2-LCFA"),
            ("SIMEPAR", "RADAR-PR"),
            ("SMN", "SINARAME-RADAR"),
            ("INUMET", "RADAR-UY"),
            ("DEFESA_CIVIL_RS", "ALERTAS-RS"),
            ("CPTEC", "PRODUTO-SATELITE-RADAR"),
        }
        self.assertEqual(set(indexed), expected)
        self.assertTrue(indexed[("NOAA", "ABI-L2-MCMIPF")] ["enabled"])
        for key, row in indexed.items():
            if key != ("NOAA", "ABI-L2-MCMIPF"):
                self.assertFalse(row["enabled"], key)
        self.assertEqual(indexed[("NOAA", "ABI-L2-MCMIPF")]["status"], "DIRECT_IN_APP_IMAGES_ACTIVE_NO_ARCHIVE")

    def test_abi_images_are_proxied_inside_app_without_archive(self):
        viewer = viewer_metadata()
        self.assertEqual(viewer["mode"], "direct_image_proxy_inside_stormtrack")
        self.assertTrue(viewer["display_enabled"])
        self.assertFalse(viewer["archived_by_stormtrack"])
        self.assertFalse(any("url" in key for key in viewer))

    def test_index_parser_extracts_only_timestamped_medium_resolution_frames(self):
        html = b'''<a href="20262780120_GOES19-ABI-FD-GEOCOLOR-1808x1808.jpg">valid</a>
        <a href="20262780120_GOES19-ABI-FD-GEOCOLOR-5424x5424.jpg">large</a>
        <a href="https://evil.example/20262780120_GOES19-ABI-FD-GEOCOLOR-1808x1808.jpg">external</a>'''
        with patch.object(noaa_goes19_abi, "_read_response", return_value=html):
            frames = _fetch_index()
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].observed_at_utc, "2026-10-05T01:20Z")
        self.assertEqual(frames[0].image_path, f"/api/satellite/goes19/abi/image/{frames[0].filename}")

    def test_image_fetch_rejects_path_traversal_before_network(self):
        with patch.object(noaa_goes19_abi, "_read_response") as read:
            with self.assertRaises(ValueError):
                fetch_frame("../latest.jpg")
        read.assert_not_called()

    def test_empty_catalog_fails_closed(self):
        with patch.object(noaa_goes19_abi, "_read_response", return_value=b"<html>empty</html>"):
            with self.assertRaises(SatelliteSourceError):
                _fetch_index()


if __name__ == "__main__":
    unittest.main()
