from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BudgetConfig:
    max_total_chars: int = 12_000
    max_file_chars: int = 2_200
    max_files: int = 6
    max_snippets: int = 10
    max_search_results: int = 5


class BudgetGovernor:
    def __init__(self, config: BudgetConfig | None = None) -> None:
        self.config = config or BudgetConfig()
        self.used_chars = 0
        self.used_snippets = 0

    @property
    def remaining_chars(self) -> int:
        return max(0, self.config.max_total_chars - self.used_chars)

    def allow(self, requested_chars: int) -> int:
        if self.used_snippets >= self.config.max_snippets:
            return 0
        granted = min(max(0, requested_chars), self.config.max_file_chars, self.remaining_chars)
        if granted <= 0:
            return 0
        self.used_chars += granted
        self.used_snippets += 1
        return granted


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)
