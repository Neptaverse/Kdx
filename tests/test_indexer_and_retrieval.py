from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from kdx.budget import BudgetConfig
from kdx.indexer import ensure_project_index, load_index, scan_project
from kdx.retrieval import budget_for_query, build_query_profile, classify_query, retrieve_context


class IndexerAndRetrievalTests(unittest.TestCase):
    def test_scan_project_extracts_python_symbols_and_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text(
                "import os\n\nclass AuthService:\n    def login(self):\n        return os.getenv('X')\n\n\ndef helper():\n    return 1\n",
                encoding="utf-8",
            )
            index_path = root / ".kdx" / "index.json"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index = scan_project(root, index_path)
            self.assertEqual(index.file_count, 1)
            record = index.files[0]
            self.assertEqual(record.path, "src/app.py")
            self.assertIn("os", record.imports)
            names = {symbol.name for symbol in record.symbols}
            self.assertIn("AuthService", names)
            self.assertIn("helper", names)
            self.assertEqual(load_index(index_path).file_count, 1)

    def test_scan_project_skips_bench_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / ".bench" / "copy").mkdir(parents=True)
            (root / ".bench" / "copy" / "ignored.py").write_text("def ignored():\n    return 1\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "real.py").write_text("def real():\n    return 1\n", encoding="utf-8")
            index_path = root / ".kdx" / "index.json"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index = scan_project(root, index_path)
            self.assertEqual(index.file_count, 1)
            self.assertEqual(index.files[0].path, "src/real.py")

    def test_bench_files_are_classified_as_bench_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "bench").mkdir()
            (root / "bench" / "perf.py").write_text("def perf():\n    return 1\n", encoding="utf-8")
            index_path = root / ".kdx" / "index.json"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index = scan_project(root, index_path)
            self.assertEqual(index.file_count, 1)
            self.assertEqual(index.files[0].role, "bench")

    def test_classify_query_detects_hybrid_work(self) -> None:
        route = classify_query("fix auth bug and check latest SDK docs")
        self.assertEqual(route.mode, "hybrid")
        self.assertTrue(route.needs_web)

    def test_read_only_question_gets_compact_budget_and_answer_only_profile(self) -> None:
        query = "Where does KDX decide whether a query is local, external, or hybrid? Keep the answer brief. Do not edit files."
        profile = build_query_profile(query)
        tuned = budget_for_query(BudgetConfig(max_total_tokens=3000, max_file_tokens=550, max_files=6, max_snippets=10), query)
        self.assertTrue(profile.answer_only)
        self.assertTrue(profile.navigation_question)
        self.assertLessEqual(tuned.max_total_tokens, 750)
        self.assertLessEqual(tuned.max_files, 2)

    def test_retrieve_context_prefers_matching_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "src").mkdir()
            (root / "src" / "auth.py").write_text(
                "class AuthManager:\n    def refresh_token(self):\n        return 'ok'\n",
                encoding="utf-8",
            )
            index_path = root / ".kdx" / "index.json"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index = scan_project(root, index_path)
            snippets = retrieve_context(root, index, "refresh token auth manager", BudgetConfig(max_total_tokens=1000, max_file_tokens=200, max_files=3))
            self.assertTrue(snippets)
            self.assertEqual(snippets[0].path, "src/auth.py")
            self.assertEqual(snippets[0].symbol, "refresh_token")

    def test_ensure_project_index_refreshes_when_repo_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "src").mkdir()
            file_path = root / "src" / "app.py"
            file_path.write_text("def alpha():\n    return 1\n", encoding="utf-8")
            index_path = root / ".kdx" / "index.json"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            first = scan_project(root, index_path)
            file_path.write_text("def beta():\n    return 2\n", encoding="utf-8")
            refreshed = ensure_project_index(root, index_path)
            names = {symbol.name for symbol in refreshed.files[0].symbols}
            self.assertEqual(first.file_count, refreshed.file_count)
            self.assertIn("beta", names)

    def test_ensure_project_index_refreshes_on_version_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "bench").mkdir()
            file_path = root / "bench" / "app.py"
            file_path.write_text("def alpha():\n    return 1\n", encoding="utf-8")
            index_path = root / ".kdx" / "index.json"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index = scan_project(root, index_path)
            payload = index.to_dict()
            payload["version"] = 2
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            refreshed = ensure_project_index(root, index_path)
            self.assertEqual(refreshed.version, 5)
            self.assertEqual(refreshed.files[0].role, "bench")

    def test_retrieve_context_prefers_source_over_docs_for_code_question(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "src").mkdir()
            (root / "docs").mkdir()
            (root / "src" / "router.py").write_text(
                "def classify_query(query: str):\n    return 'local'\n",
                encoding="utf-8",
            )
            (root / "docs" / "routing.md").write_text(
                "# Routing\nKDX decides between local and hybrid modes here.\n",
                encoding="utf-8",
            )
            index_path = root / ".kdx" / "index.json"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index = scan_project(root, index_path)
            snippets = retrieve_context(root, index, "where does kdx decide whether a query is local or hybrid", BudgetConfig())
            self.assertTrue(snippets)
            self.assertEqual(snippets[0].path, "src/router.py")

    def test_path_hint_drives_exact_file_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "src").mkdir()
            (root / "src" / "router.py").write_text("def choose_route():\n    return 'local'\n", encoding="utf-8")
            (root / "src" / "other.py").write_text("def choose_other():\n    return 'external'\n", encoding="utf-8")
            index_path = root / ".kdx" / "index.json"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index = scan_project(root, index_path)
            snippets = retrieve_context(root, index, "explain src/router.py", BudgetConfig())
            self.assertTrue(snippets)
            self.assertEqual(snippets[0].path, "src/router.py")


if __name__ == "__main__":
    unittest.main()
