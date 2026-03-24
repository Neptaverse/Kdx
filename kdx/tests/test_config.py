from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from kdx.config import clear_keiro_api_key, load_persisted_config, set_keiro_api_key


class ConfigTests(unittest.TestCase):
    def test_keiro_key_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            set_keiro_api_key("keiro_test_key", config_path)
            self.assertEqual(load_persisted_config(config_path).get("keiro_api_key"), "keiro_test_key")
            clear_keiro_api_key(config_path)
            self.assertNotIn("keiro_api_key", load_persisted_config(config_path))

    def test_keiro_config_permissions_are_private(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "nested" / "config.json"
            set_keiro_api_key("keiro_test_key", config_path)
            config_mode = stat.S_IMODE(os.stat(config_path).st_mode)
            parent_mode = stat.S_IMODE(os.stat(config_path.parent).st_mode)
            self.assertEqual(config_mode, 0o600)
            self.assertEqual(parent_mode, 0o700)


if __name__ == "__main__":
    unittest.main()
