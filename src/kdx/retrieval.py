from __future__ import annotations

from dataclasses import dataclass, replace
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable

from kdx.budget import BudgetConfig, BudgetGovernor, estimate_tokens
from kdx.indexer import tokenize
from kdx.models import FileRecord, HistoryEntry, ProjectIndex, QueryRoute, RetrievedSnippet

EXTERNAL_TERMS = {
    "latest", "current", "today", "recent", "release", "version", "docs", "documentation",
    "api", "changelog", "news", "web", "online", "search", "github", "pypi", "npm",
}
LOCAL_TERMS = {
    "repo", "repository", "codebase", "file", "files", "function", "class", "module", "test",
    "tests", "refactor", "bug", "fix", "implement", "code", "symbol", "import",
    "prompt", "route", "routing", "local", "external", "hybrid", "query", "wrapper", "server", "mcp",
}
EDIT_TERMS = {"fix", "implement", "edit", "change", "refactor", "add", "write", "create", "update", "remove"}
QUESTION_TERMS = {"how", "where", "what", "which", "why"}
RETRIEVAL_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "those", "these", "into", "onto", "their",
    "then", "than", "does", "doesn", "keep", "brief", "answer", "briefly", "name", "main", "using",
    "used", "call", "calls", "called", "also", "just", "user", "users", "please", "normal", "versus",
    "oriented", "edit", "files", "file", "not", "dont", "do", "your", "its", "own",
}


@dataclass(slots=True)
class QueryProfile:
    raw_terms: set[str]
    retrieval_terms: set[str]
    path_hints: set[str]
    identifier_hints: set[str]
    wants_tests: bool
    wants_bench: bool
    wants_docs: bool
    wants_config: bool
    answer_only: bool
    navigation_question: bool
    implementation_task: bool


_PATH_HINT_RE = re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.(?:py|ts|tsx|js|jsx|rs|go|java|kt|rb|php|c|cc|cpp|h|hpp|cs|scala|md|toml|yaml|yml|json|sh)")
_IDENTIFIER_HINT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")


def _extract_path_hints(query: str) -> set[str]:
    return {match.group(0).strip().strip("`").lower() for match in _PATH_HINT_RE.finditer(query)}


def _extract_identifier_hints(query: str) -> set[str]:
    hints: set[str] = set()
    for match in _IDENTIFIER_HINT_RE.finditer(query):
        token = match.group(0)
        normalized = token.lower()
        if len(normalized) < 3 or normalized in RETRIEVAL_STOPWORDS:
            continue
        if "_" in token or any(char.isupper() for char in token[1:]):
            hints.add(normalized)
    return hints


def build_query_profile(query: str) -> QueryProfile:
    raw_terms = set(tokenize(query))
    retrieval_terms = {term for term in raw_terms if len(term) >= 3 and term not in RETRIEVAL_STOPWORDS}
    path_hints = _extract_path_hints(query)
    identifier_hints = _extract_identifier_hints(query)
    wants_tests = bool({"test", "tests", "spec", "failure"} & raw_terms)
    wants_bench = bool({"bench", "benchmark", "benchmarks", "perf", "performance"} & raw_terms)
    wants_docs = bool({"docs", "documentation", "readme", "guide"} & raw_terms)
    wants_config = bool({"config", "toml", "yaml", "yml", "json"} & raw_terms)
    negative_edit = "do not edit" in query.lower() or "do not edit files" in query.lower()
    implementation_task = bool(EDIT_TERMS & raw_terms) and not negative_edit
    answer_only = (
        (negative_edit or bool(QUESTION_TERMS & raw_terms))
        and not implementation_task
    )
    navigation_question = bool({"where", "which", "locate", "find"} & raw_terms) and answer_only
    return QueryProfile(
        raw_terms=raw_terms,
        retrieval_terms=retrieval_terms or raw_terms,
        path_hints=path_hints,
        identifier_hints=identifier_hints,
        wants_tests=wants_tests,
        wants_bench=wants_bench,
        wants_docs=wants_docs,
        wants_config=wants_config,
        answer_only=answer_only,
        navigation_question=navigation_question,
        implementation_task=implementation_task,
    )


def budget_for_query(budget: BudgetConfig, query: str) -> BudgetConfig:
    profile = build_query_profile(query)
    tuned = budget
    if profile.answer_only:
        tuned = replace(
            tuned,
            max_total_chars=min(tuned.max_total_chars, 4_200),
            max_file_chars=min(tuned.max_file_chars, 1_400),
            max_files=min(tuned.max_files, 3),
            max_snippets=min(tuned.max_snippets, 3),
        )
    if profile.navigation_question:
        tuned = replace(
            tuned,
            max_total_chars=min(tuned.max_total_chars, 3_000),
            max_file_chars=min(tuned.max_file_chars, 1_200),
            max_files=min(tuned.max_files, 2),
            max_snippets=min(tuned.max_snippets, 2),
        )
    if profile.path_hints:
        tuned = replace(
            tuned,
            max_total_chars=min(tuned.max_total_chars, 2_600),
            max_file_chars=min(tuned.max_file_chars, 1_600),
            max_files=min(tuned.max_files, max(1, len(profile.path_hints))),
            max_snippets=min(tuned.max_snippets, max(1, len(profile.path_hints))),
        )
    return tuned


def classify_query(query: str) -> QueryRoute:
    profile = build_query_profile(query)
    terms = profile.raw_terms
    reasons: list[str] = []
    external_hits = sorted(terms & EXTERNAL_TERMS)
    local_hits = sorted(terms & LOCAL_TERMS)
    if "http" in query or "www." in query:
        external_hits.append("url")
    if "/" in query or ".py" in query or ".ts" in query or "::" in query:
        local_hits.append("file-or-symbol")
    if external_hits:
        reasons.append(f"fresh/external terms: {', '.join(external_hits[:5])}")
    if local_hits:
        reasons.append(f"repo/code terms: {', '.join(local_hits[:5])}")
    if external_hits and local_hits:
        return QueryRoute(mode="hybrid", needs_web=True, reasons=reasons)
    if external_hits:
        return QueryRoute(mode="external", needs_web=True, reasons=reasons or ["explicit external/freshness cues"])
    return QueryRoute(mode="local", needs_web=False, reasons=reasons or ["no freshness cues detected"])


def _path_hint_score(path_hints: set[str], record: FileRecord) -> float:
    if not path_hints:
        return 0.0
    record_path = record.path.lower()
    record_name = Path(record.path).name.lower()
    score = 0.0
    for hint in path_hints:
        if hint == record_path:
            score += 80.0
        elif hint == record_name:
            score += 60.0
        elif record_path.endswith(hint):
            score += 42.0
        elif hint in record_path:
            score += 20.0
    return score


def _role_score(profile: QueryProfile, record: FileRecord) -> float:
    if record.role == "source":
        return 7.0
    if record.role == "test":
        return 7.0 if profile.wants_tests or profile.implementation_task else -14.0
    if record.role == "bench":
        return 6.0 if profile.wants_bench else -15.0
    if record.role == "docs":
        return 8.0 if profile.wants_docs else -12.0
    if record.role == "config":
        return 8.0 if profile.wants_config else -10.0
    if record.role == "script":
        return 4.0 if profile.implementation_task else -4.0
    return 0.0


def _file_score(profile: QueryProfile, record: FileRecord) -> float:
    query_terms = profile.retrieval_terms
    keywords = set(record.keywords)
    path_terms = set(tokenize(record.path))
    symbol_terms = set(tokenize(" ".join(symbol.name for symbol in record.symbols[:40])))
    import_terms = set(tokenize(" ".join(record.imports[:40])))
    score = 0.0
    score += _path_hint_score(profile.path_hints, record)
    score += 6.0 * len(query_terms & path_terms)
    score += 4.0 * len(query_terms & symbol_terms)
    score += 2.5 * len(query_terms & import_terms)
    score += 2.0 * len(query_terms & keywords)
    score += 6.0 * len(profile.identifier_hints & symbol_terms)
    score += _role_score(profile, record)
    if record.path.startswith("src/"):
        score += 3.0
    if record.path.startswith("tests/") and not profile.wants_tests:
        score -= 6.0
    if profile.answer_only and record.role != "source" and not profile.path_hints:
        score -= 4.0
    if record.language in {"typescript", "tsx", "javascript", "python", "rust", "go"}:
        score += 1.0
    return score


def _excerpt_by_terms(text: str, terms: set[str], max_chars: int) -> tuple[str, int, int]:
    if not text:
        return "", 1, 1
    if not terms:
        chunk = text[:max_chars]
        lines = chunk.splitlines() or [""]
        return chunk, 1, len(lines)
    lines = text.splitlines()
    best_line = -1
    best_score = -1
    for index, line in enumerate(lines):
        score = len(terms & set(tokenize(line)))
        if score > best_score:
            best_score = score
            best_line = index
    if best_score <= 0:
        chunk = text[:max_chars]
        preview_lines = chunk.splitlines() or [""]
        return chunk, 1, len(preview_lines)
    start_line = max(0, best_line - 8)
    end_line = min(len(lines), best_line + 16)
    chunk = "\n".join(lines[start_line:end_line])
    if len(chunk) > max_chars:
        chunk = chunk[:max_chars]
    line_start = start_line + 1
    line_end = line_start + chunk.count("\n")
    return chunk, line_start, line_end


def _symbol_score(query_terms: set[str], record: FileRecord) -> list[tuple[float, str]]:
    ranked: list[tuple[float, str]] = []
    for symbol in record.symbols:
        symbol_terms = set(tokenize(symbol.name))
        if symbol.name.startswith("test_") and "test" not in query_terms and "tests" not in query_terms:
            continue
        overlap = query_terms & symbol_terms
        score = 5.0 * len(overlap)
        if symbol.name == "main":
            score -= 2.0
        if symbol.name.startswith("_"):
            score -= 1.5
        if score > 0:
            ranked.append((score, symbol.name))
    ranked.sort(reverse=True)
    return ranked


def _extract_symbol_content(root: Path, record: FileRecord, symbol_name: str, max_chars: int) -> tuple[str, int, int]:
    text = (root / record.path).read_text(encoding="utf-8", errors="ignore")
    for symbol in record.symbols:
        if symbol.name != symbol_name:
            continue
        lines = text.splitlines()
        start = max(0, symbol.line_start - 1)
        end = min(len(lines), symbol.line_end)
        chunk = "\n".join(lines[start:end])
        if len(chunk) > max_chars:
            chunk = chunk[:max_chars]
        return chunk, symbol.line_start, min(symbol.line_end, symbol.line_start + chunk.count("\n"))
    return _excerpt_by_terms(text, set(tokenize(symbol_name)), max_chars)


def _should_skip_file(profile: QueryProfile, record: FileRecord, snippets: list[RetrievedSnippet], seen_directories: set[str]) -> bool:
    if not profile.answer_only:
        return False
    directory = Path(record.path).parent.as_posix()
    if directory == ".":
        return False
    if directory in seen_directories and not profile.path_hints:
        return True
    if snippets and profile.navigation_question and record.role != "source":
        return True
    return False


def retrieve_context(root: Path, index: ProjectIndex, query: str, budget: BudgetConfig) -> list[RetrievedSnippet]:
    profile = build_query_profile(query)
    query_terms = profile.retrieval_terms
    governor = BudgetGovernor(budget)
    ranked_files = sorted(
        ((record, _file_score(profile, record)) for record in index.files),
        key=lambda item: (item[1], item[0].mtime_ns),
        reverse=True,
    )
    snippets: list[RetrievedSnippet] = []
    seen_directories: set[str] = set()
    scan_limit = max(budget.max_files * 4, 8)
    for record, score in ranked_files[:scan_limit]:
        if len(snippets) >= budget.max_files:
            break
        if score <= 0 and snippets:
            break
        if score <= 0 and not snippets:
            continue
        if _should_skip_file(profile, record, snippets, seen_directories):
            continue
        granted = governor.allow(budget.max_file_chars)
        if granted <= 0:
            break
        reason = []
        symbols = _symbol_score(query_terms, record)
        if symbols and symbols[0][0] >= 8.5:
            symbol_name = symbols[0][1]
            content, line_start, line_end = _extract_symbol_content(root, record, symbol_name, granted)
            reason.append(f"symbol match: {symbol_name}")
            snippets.append(
                RetrievedSnippet(
                    path=record.path,
                    score=round(score, 2),
                    reason="; ".join(reason) or "high-scoring file",
                    content=content,
                    symbol=symbol_name,
                    line_start=line_start,
                    line_end=line_end,
                )
            )
            seen_directories.add(Path(record.path).parent.as_posix())
            continue
        text = (root / record.path).read_text(encoding="utf-8", errors="ignore")
        content, line_start, line_end = _excerpt_by_terms(text, query_terms, granted)
        overlap = sorted(query_terms & set(record.keywords))
        if overlap:
            reason.append(f"keyword overlap: {', '.join(overlap[:4])}")
        path_overlap = [hint for hint in sorted(profile.path_hints) if hint in record.path.lower()]
        if path_overlap:
            reason.append(f"path hint: {path_overlap[0]}")
        if not reason and score > 0:
            reason.append("path/summary overlap")
        if not reason:
            reason.append("recent fallback")
        snippets.append(
            RetrievedSnippet(
                path=record.path,
                score=round(score, 2),
                reason="; ".join(reason),
                content=content,
                line_start=line_start,
                line_end=line_end,
            )
        )
        seen_directories.add(Path(record.path).parent.as_posix())
    return snippets


def render_context(snippets: Iterable[RetrievedSnippet], budget: BudgetConfig) -> str:
    parts = []
    for snippet in snippets:
        label = f"{snippet.path}:{snippet.line_start}"
        if snippet.symbol:
            label += f"::{snippet.symbol}"
        parts.append(
            "\n".join(
                [
                    f"FILE {label}",
                    f"REASON {snippet.reason}",
                    snippet.content.strip(),
                ]
            )
        )
    blob = "\n\n".join(parts)
    if len(blob) > budget.max_total_chars:
        blob = blob[: budget.max_total_chars]
    return blob


def append_history(history_path: Path, entry: HistoryEntry) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")


def search_history(history_path: Path, query: str, limit: int = 5) -> list[HistoryEntry]:
    if not history_path.exists():
        return []
    query_terms = build_query_profile(query).retrieval_terms
    scored: list[tuple[float, HistoryEntry]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = HistoryEntry.from_dict(json.loads(line))
        hay = set(tokenize(entry.query))
        score = len(query_terms & hay)
        if score > 0:
            scored.append((float(score), entry))
    scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
    return [entry for _, entry in scored[:limit]]


def impact_analysis(index: ProjectIndex, changed_files: list[str], limit: int = 10) -> list[dict[str, object]]:
    changed_tokens = set()
    for file in changed_files:
        changed_tokens.update(tokenize(Path(file).stem))
    impacts: list[dict[str, object]] = []
    for record in index.files:
        imports = set(tokenize(" ".join(record.imports)))
        overlap = sorted(changed_tokens & imports)
        if overlap:
            impacts.append({
                "path": record.path,
                "reasons": overlap[:5],
                "score": len(overlap) + (2 if record.is_test else 0),
                "is_test": record.is_test,
            })
    impacts.sort(key=lambda item: (int(item["score"]), bool(item["is_test"])), reverse=True)
    return impacts[:limit]


def make_history_entry(query: str, route: QueryRoute, snippets: list[RetrievedSnippet], search_queries: list[str]) -> HistoryEntry:
    return HistoryEntry(
        created_at=datetime.now(timezone.utc).isoformat(),
        query=query,
        route=route.mode,
        files=[snippet.path for snippet in snippets],
        search_queries=search_queries,
    )


def plan_summary(route: QueryRoute, snippets: list[RetrievedSnippet], search_results: list[dict[str, object]], budget: BudgetConfig) -> dict[str, object]:
    return {
        "route": route.to_dict(),
        "snippets": [snippet.to_dict() for snippet in snippets],
        "search_results": search_results[: budget.max_search_results],
        "budget": {
            "max_total_chars": budget.max_total_chars,
            "max_file_chars": budget.max_file_chars,
            "max_files": budget.max_files,
            "input_tokens_estimate": estimate_tokens(render_context(snippets, budget)),
        },
    }
