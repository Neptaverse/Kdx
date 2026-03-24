from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kdx.budget import BudgetConfig
from kdx.codex_home import prepared_codex_home
from kdx.config import KdxSettings


class CodexHomeTests(unittest.TestCase):
    def test_prepared_codex_home_preserves_auth_and_injects_kdx_servers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir(parents=True)
            (root / ".git").mkdir()
            data_dir = root / ".kdx"
            data_dir.mkdir()
            base_home = Path(temp_dir) / "codex-home"
            (base_home / "rules").mkdir(parents=True)
            (base_home / "auth.json").write_text("{}", encoding="utf-8")
            (base_home / "config.toml").write_text(
                'model = "gpt-5.4"\n\n[mcp_servers.dual-graph]\ncommand = "npx"\nargs = ["mcp-remote", "http://localhost:8081/mcp"]\n\n'
                f'[projects."{root}"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )
            (base_home / "rules" / "default.rules").write_text("rule", encoding="utf-8")
            settings = KdxSettings(
                repo_root=root,
                data_dir=data_dir,
                index_path=data_dir / "index.json",
                history_path=data_dir / "history.jsonl",
                search_cache_path=data_dir / "keiro-cache.json",
                global_config_path=Path(temp_dir) / ".kdx-config.json",
                keiro_api_key="",
                keiro_base_url="https://kierolabs.space/api",
                codex_binary="codex",
                base_codex_home=base_home,
                model="gpt-5.4",
                auto_init=True,
                budget=BudgetConfig(),
            )
            with prepared_codex_home(settings, session_instructions="Use kdx_repo first.") as temp_home:
                config = (temp_home / "config.toml").read_text(encoding="utf-8")
                instructions = (temp_home / "AGENTS.override.md").read_text(encoding="utf-8")
                self.assertTrue((temp_home / "auth.json").exists())
                self.assertTrue((temp_home / "rules" / "default.rules").exists())
                self.assertIn("[mcp_servers.kdx_repo]", config)
                self.assertIn("[mcp_servers.kdx_web]", config)
                self.assertNotIn("[mcp_servers.dual-graph]", config)
                self.assertEqual(config.count(f'[projects."{root}"]'), 1)
                self.assertIn("Use kdx_repo first.", instructions)

if __name__ == "__main__":
    unittest.main()
