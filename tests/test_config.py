import os
import unittest
from unittest.mock import patch

from backend.app.core.config import get_settings


class CollectionConfigTests(unittest.TestCase):
    def test_collection_interval_is_bounded_to_the_supported_recent_poll_window(self):
        with patch.dict(os.environ, {"STORMTRACK_COLLECTION_INTERVAL_SECONDS": "300"}):
            self.assertEqual(get_settings().collection_interval_seconds, 300)
        with patch.dict(os.environ, {"STORMTRACK_COLLECTION_INTERVAL_SECONDS": "301"}):
            with self.assertRaisesRegex(ValueError, "20 and 300"):
                get_settings()


if __name__ == "__main__":
    unittest.main()
