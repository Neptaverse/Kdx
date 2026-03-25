from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from kdx.budget import BudgetConfig
from kdx.config import KdxSettings
from kdx.retrieval import build_query_profile
from kdx.wrapper import build_execution_plan, should_auto_update_on_startup, should_preload_web


class WrapperTests(unittest.TestCase):
    def test_answer_only_hybrid_with_local_context_skips_web_preload(self) -> None:
        profile = build_query_profile("Where is the API client in this repo? Do not edit files.")
        self.assertFalse(should_preload_web(profile, "hybrid", has_local_context=True))

    def test_docs_query_keeps_web_preload_enabled(self) -> None:
        profile = build_query_profile("FastAPI auth docs for bearer tokens")
        self.assertTrue(should_preload_web(profile, "hybrid", has_local_context=False))

    def test_empty_query_uses_clean_startup_without_visible_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir(parents=True)
            (root / ".git").mkdir()
            data_dir = root / ".kdx"
            data_dir.mkdir()
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
                base_codex_home=Path(temp_dir) / ".codex",
                model="gpt-5.4",
                auto_init=True,
                budget=BudgetConfig(),
            )
            plan = build_execution_plan("", settings=settings)
            self.assertEqual(plan["route"].mode, "startup")
            self.assertEqual(plan["prompt"], "")
            self.assertEqual(plan["summary"]["budget"]["input_tokens_estimate"], 0)

    def test_auto_update_only_on_interactive_startup(self) -> None:
        self.assertTrue(should_auto_update_on_startup("", exec_mode=False, environ={}))
        self.assertFalse(should_auto_update_on_startup("fix bug", exec_mode=False, environ={}))
        self.assertFalse(should_auto_update_on_startup("", exec_mode=True, environ={}))
        self.assertFalse(should_auto_update_on_startup("", exec_mode=False, environ={"KDX_NO_AUTO_UPDATE": "1"}))


if __name__ == "__main__":
    unittest.main()
