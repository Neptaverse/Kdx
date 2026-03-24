from __future__ import annotations

import unittest

from kdx.token_compare import parse_turn_usage


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


if __name__ == "__main__":
    unittest.main()
