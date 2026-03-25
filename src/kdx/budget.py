from __future__ import annotations

from dataclasses import dataclass

BYTES_PER_TOKEN = 4  # industry-standard heuristic (Codex, tiktoken avg)


@dataclass(slots=True)
class BudgetConfig:
    max_total_tokens: int = 3_000
    max_file_tokens: int = 550
    max_files: int = 6
    max_snippets: int = 10
    max_search_results: int = 5

    @property
    def max_total_chars(self) -> int:
        return self.max_total_tokens * BYTES_PER_TOKEN

    @property
    def max_file_chars(self) -> int:
        return self.max_file_tokens * BYTES_PER_TOKEN


class BudgetGovernor:
    def __init__(self, config: BudgetConfig | None = None) -> None:
        self.config = config or BudgetConfig()
        self.used_tokens = 0
        self.used_snippets = 0

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.config.max_total_tokens - self.used_tokens)

    def allow(self, requested_tokens: int) -> int:
        if self.used_snippets >= self.config.max_snippets:
            return 0
        granted = min(max(0, requested_tokens), self.config.max_file_tokens, self.remaining_tokens)
        if granted <= 0:
            return 0
        self.used_tokens += granted
        self.used_snippets += 1
        return granted


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // BYTES_PER_TOKEN)


def tokens_to_chars(tokens: int) -> int:
    return tokens * BYTES_PER_TOKEN


def chars_to_tokens(chars: int) -> int:
    return max(1, chars // BYTES_PER_TOKEN)
