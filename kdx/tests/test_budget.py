from __future__ import annotations

import unittest

from kdx.budget import BudgetConfig, BudgetGovernor, estimate_tokens


class BudgetGovernorTests(unittest.TestCase):
    def test_allow_respects_total_and_snippet_caps(self) -> None:
        governor = BudgetGovernor(BudgetConfig(max_total_chars=100, max_file_chars=60, max_snippets=2))
        self.assertEqual(governor.allow(80), 60)
        self.assertEqual(governor.allow(80), 40)
        self.assertEqual(governor.allow(10), 0)

    def test_estimate_tokens_is_non_zero_for_non_empty_text(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)
        self.assertGreaterEqual(estimate_tokens("abcd"), 1)


if __name__ == "__main__":
    unittest.main()
