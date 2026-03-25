from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kdx.budget import BudgetConfig
from kdx.config import KdxSettings
from kdx.token_compare import _build_codex_exec_command, parse_turn_usage


class TokenCompareTests(unittest.TestCase):
    def test_parse_turn_usage_reads_turn_completed_usage(self) -> None:
        stdout = "\n".join(
            [
                '{"type":"item.completed","item":{"type":"agent_message","text":"answer"}}',
                '{"type":"turn.completed","usage":{"input_tokens":120,"cached_input_tokens":30,"output_tokens":15}}',
            ]
        )
        usage = parse_turn_usage(stdout)
        self.assertEqual(
            usage,
            {
                "input_tokens": 120,
                "cached_input_tokens": 30,
                "output_tokens": 15,
                "total_tokens": 165,
            },
        )

    def test_parse_turn_usage_raises_when_missing(self) -> None:
        with self.assertRaises(RuntimeError):
            parse_turn_usage('{"type":"item.completed"}')

    def test_build_codex_exec_command_includes_overrides_before_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir(parents=True)
            settings = KdxSettings(
                repo_root=root,
                data_dir=root / ".kdx",
                index_path=root / ".kdx" / "index.json",
                history_path=root / ".kdx" / "history.jsonl",
                search_cache_path=root / ".kdx" / "keiro-cache.json",
                global_config_path=Path(temp_dir) / ".kdx-config.json",
                keiro_api_key="",
                keiro_base_url="https://kierolabs.space/api",
                codex_binary="codex",
                base_codex_home=Path(temp_dir) / ".codex",
                model="gpt-5.4",
                auto_init=True,
                budget=BudgetConfig(),
            )
            command = _build_codex_exec_command(
                settings,
                "hello",
                model="gpt-5.4",
                config_overrides=("web_search=false",),
            )
            self.assertIn("-c", command)
            self.assertIn("web_search=false", command)
            self.assertEqual(command[-1], "hello")


if __name__ == "__main__":
    unittest.main()
