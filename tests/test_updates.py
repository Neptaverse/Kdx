from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kdx.budget import BudgetConfig
from kdx.config import KdxSettings
from kdx.updates import check_for_updates, format_update_notice, normalize_version_tag, update_actions


class UpdateTests(unittest.TestCase):
    def test_normalize_version_tag_strips_prefixes(self) -> None:
        self.assertEqual(normalize_version_tag("v0.2.0"), "0.2.0")
        self.assertEqual(normalize_version_tag("refs/tags/v1.4.3"), "1.4.3")

    def test_check_for_updates_reports_newer_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings_for(Path(temp_dir))
            status = check_for_updates(
                settings,
                force=True,
                fetcher=lambda: {
                    "latest_version": "0.2.0",
                    "release_url": "https://github.com/Neptaverse/Kdx/releases/tag/v0.2.0",
                    "source": "release",
                },
            )
            self.assertTrue(status["update_available"])
            self.assertIn("0.2.0", format_update_notice(status))

    def test_check_for_updates_uses_fresh_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings_for(Path(temp_dir))
            first = check_for_updates(
                settings,
                force=True,
                fetcher=lambda: {
                    "latest_version": "0.2.0",
                    "release_url": "https://github.com/Neptaverse/Kdx/releases/tag/v0.2.0",
                    "source": "release",
                },
            )
            self.assertFalse(first["cached"])
            second = check_for_updates(
                settings,
                now=datetime.now(timezone.utc) + timedelta(minutes=5),
                fetcher=lambda: {
                    "latest_version": "9.9.9",
                    "release_url": "https://example.com",
                    "source": "release",
                },
            )
            self.assertTrue(second["cached"])
            self.assertEqual(second["latest_version"], "0.2.0")

    def test_check_for_updates_falls_back_to_commit_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings_for(Path(temp_dir))
            status = check_for_updates(
                settings,
                force=True,
                fetcher=lambda: {
                    "latest_version": "",
                    "latest_commit": "abc123",
                    "release_url": "https://github.com/Neptaverse/Kdx/commit/abc123",
                    "source": "commit",
                },
            )
            self.assertEqual(status["latest_commit"], "abc123")
            self.assertTrue("current_commit" in status)

    def test_update_actions_do_not_expose_stay_option(self) -> None:
        actions = update_actions({"current_version": "0.1.0", "latest_version": "0.2.0"})
        self.assertIn("update", actions)
        self.assertIn("rollback", actions)
        self.assertNotIn("stay", actions)
        self.assertIn("bootstrap.py", actions["update"])
        self.assertIn("bootstrap.py", actions["rollback"])


def _settings_for(temp_dir: Path) -> KdxSettings:
    root = temp_dir / "repo"
    root.mkdir(parents=True)
    (root / ".git").mkdir()
    data_dir = root / ".kdx"
    data_dir.mkdir()
    return KdxSettings(
        repo_root=root,
        data_dir=data_dir,
        index_path=data_dir / "index.json",
        history_path=data_dir / "history.jsonl",
        search_cache_path=data_dir / "keiro-cache.json",
        global_config_path=temp_dir / ".kdx-config" / "config.json",
        keiro_api_key="",
        keiro_base_url="https://kierolabs.space/api",
        codex_binary="codex",
        base_codex_home=temp_dir / ".codex",
        model="gpt-5.4",
        auto_init=True,
        budget=BudgetConfig(),
    )


if __name__ == "__main__":
    unittest.main()
