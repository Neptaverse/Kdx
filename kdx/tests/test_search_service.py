from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kdx.budget import BudgetConfig
from kdx.config import KdxSettings
from kdx.search_service import build_search_plan, execute_context_search, rank_search_results, render_web_evidence_block


class _FakeKeiroClient:
    def __init__(self) -> None:
        self.crawled_urls: list[str] = []

    def search_engine(self, query: str, **kwargs):
        return {"results": [{"title": "News result", "url": "https://news.example.com/item", "snippet": query}]}

    def search_pro(self, query: str, **kwargs):
        return {
            "results": [
                {
                    "title": "FastAPI documentation",
                    "url": "https://fastapi.tiangolo.com/tutorial/security/",
                    "snippet": f"{query} official docs",
                },
                {
                    "title": "Some blog post",
                    "url": "https://medium.com/example/fastapi-auth",
                    "snippet": "tutorial post",
                },
            ]
        }

    def search(self, query: str, **kwargs):
        return self.search_pro(query, **kwargs)

    def research(self, query: str, **kwargs):
        return self.search_pro(query, **kwargs)

    def memory_search(self, query: str, workspace_id: str, **kwargs):
        return self.search_pro(query)

    def crawl(self, url: str):
        self.crawled_urls.append(url)
        return {
            "content": "FastAPI security docs explain OAuth2 and bearer token authentication in detail.",
        }


class SearchServiceTests(unittest.TestCase):
    def test_build_search_plan_uses_dependency_version_for_docs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pyproject.toml").write_text(
                "[project]\ndependencies = [\"fastapi==0.115.0\"]\n",
                encoding="utf-8",
            )
            plan = build_search_plan(root, "FastAPI auth docs for bearer tokens", limit=4)
            self.assertEqual(plan.mode, "search_pro")
            self.assertEqual(plan.intent, "package_api")
            self.assertIsNotNone(plan.dependency)
            self.assertIn("fastapi 0.115.0 official documentation", plan.query.lower())
            self.assertTrue(plan.should_crawl)

    def test_rank_search_results_prefers_official_docs(self) -> None:
        plan = build_search_plan(Path("."), "fastapi auth docs", limit=3)
        payload = {
            "results": [
                {
                    "title": "Random blog",
                    "url": "https://medium.com/example/fastapi-auth",
                    "snippet": "auth docs",
                },
                {
                    "title": "FastAPI docs",
                    "url": "https://fastapi.tiangolo.com/tutorial/security/",
                    "snippet": "FastAPI security docs",
                },
            ]
        }
        ranked = rank_search_results(payload, "fastapi auth docs", plan)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0].domain, "fastapi.tiangolo.com")

    def test_rank_search_results_prefers_brand_matching_official_docs(self) -> None:
        plan = build_search_plan(Path("."), "Keiro Search API official docs search endpoint request parameters", limit=3)
        payload = {
            "results": [
                {
                    "title": "Search API — SearXNG Documentation",
                    "url": "https://docs.searxng.org/dev/search_api.html",
                    "snippet": "Search API docs and request parameters",
                },
                {
                    "title": "Keiro Search API",
                    "url": "https://www.keirolabs.cloud/docs/api-reference/search",
                    "snippet": "Perform a basic search query to get relevant results from the web.",
                },
            ]
        }
        ranked = rank_search_results(payload, "Keiro Search API official docs search endpoint request parameters", plan)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0].domain, "keirolabs.cloud")

    def test_release_note_query_prefers_release_plan_over_news(self) -> None:
        plan = build_search_plan(Path("."), "latest OpenAI API release notes", limit=4)
        self.assertEqual(plan.intent, "release_notes")
        self.assertEqual(plan.mode, "search_pro")
        self.assertTrue(plan.should_crawl)
        self.assertEqual(plan.evidence_items, 1)
        self.assertLessEqual(plan.evidence_char_budget, 420)

    def test_docs_query_beats_news_routing_when_both_terms_present(self) -> None:
        plan = build_search_plan(Path("."), "latest Gemini API docs for structured output", limit=4)
        self.assertEqual(plan.intent, "official_docs")
        self.assertEqual(plan.mode, "search_pro")

    def test_render_web_evidence_block_stays_compact(self) -> None:
        block = render_web_evidence_block(
            [
                {
                    "title": "FastAPI docs",
                    "domain": "fastapi.tiangolo.com",
                    "source_type": "docs",
                    "trust_score": 0.93,
                    "url": "https://fastapi.tiangolo.com/tutorial/security/",
                    "crawled_excerpt": "x" * 500,
                }
            ],
            char_budget=180,
            max_items=1,
        )
        self.assertLessEqual(len(block), 180)
        self.assertIn("fastapi.tiangolo.com", block)

    def test_execute_context_search_crawls_best_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            root.mkdir(parents=True)
            data_dir = root / ".kdx"
            data_dir.mkdir()
            (root / "pyproject.toml").write_text(
                "[project]\ndependencies = [\"fastapi==0.115.0\"]\n",
                encoding="utf-8",
            )
            settings = KdxSettings(
                repo_root=root,
                data_dir=data_dir,
                index_path=data_dir / "index.json",
                history_path=data_dir / "history.jsonl",
                search_cache_path=data_dir / "keiro-cache.json",
                global_config_path=data_dir / "global.json",
                keiro_api_key="keiro_demo",
                keiro_base_url="https://kierolabs.space/api",
                codex_binary="codex",
                base_codex_home=Path(temp_dir) / ".codex",
                model="gpt-5.4",
                auto_init=True,
                budget=BudgetConfig(),
            )
            fake = _FakeKeiroClient()
            result = execute_context_search(settings, "FastAPI auth docs for bearer tokens", limit=2, client=fake)
            evidence = result["evidence"]
            self.assertTrue(evidence)
            self.assertIn("OAuth2", evidence[0]["crawled_excerpt"])
            self.assertEqual(fake.crawled_urls, ["https://fastapi.tiangolo.com/tutorial/security/"])
            self.assertLessEqual(len(result["compact"]), 420)

    def test_rank_search_results_reads_nested_keiro_payloads(self) -> None:
        plan = build_search_plan(Path("."), "Keiro search docs", limit=3)
        payload = {
            "data": {
                "extracted_content": [
                    {
                        "search_title": "Keiro search",
                        "source_url": "https://www.keirolabs.cloud/docs/api-reference/search",
                        "description": "Perform a basic search query",
                    }
                ]
            }
        }
        ranked = rank_search_results(payload, "Keiro search docs", plan)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].domain, "keirolabs.cloud")


if __name__ == "__main__":
    unittest.main()
