from __future__ import annotations

import unittest

from kdx.keiro import DEFAULT_HTTP_USER_AGENT, KeiroClient, normalize_results


class KeiroTests(unittest.TestCase):
    def test_headers_include_user_agent_and_accept(self) -> None:
        headers = KeiroClient._headers(content_type="application/json")
        self.assertEqual(headers["User-Agent"], DEFAULT_HTTP_USER_AGENT)
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_normalize_results_reads_nested_data_results(self) -> None:
        payload = {
            "data": {
                "results": [
                    {
                        "title": "Keiro docs",
                        "url": "https://www.keirolabs.cloud/docs/api-reference/search",
                        "snippet": "Search API docs",
                    }
                ]
            }
        }
        normalized = normalize_results(payload, limit=3)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["title"], "Keiro docs")

    def test_normalize_results_reads_extracted_content_and_crawl_payloads(self) -> None:
        extracted = normalize_results(
            {
                "data": {
                    "extracted_content": [
                        {
                            "search_title": "Gemini docs",
                            "source_url": "https://ai.google.dev/gemini-api/docs/structured-output",
                            "description": "Structured output guide",
                        }
                    ]
                }
            },
            limit=2,
        )
        self.assertEqual(extracted[0]["title"], "Gemini docs")
        self.assertIn("ai.google.dev", extracted[0]["url"])

        crawled = normalize_results({"data": {"content": "Detailed crawled page content"}}, limit=2)
        self.assertEqual(crawled[0]["title"], "summary")
        self.assertIn("Detailed crawled page content", crawled[0]["snippet"])


if __name__ == "__main__":
    unittest.main()
