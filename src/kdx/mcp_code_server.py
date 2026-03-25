from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

from kdx.config import load_settings
from kdx.indexer import ensure_project_index, scan_project, tokenize
from kdx.models import ProjectIndex
from kdx.retrieval import classify_query, impact_analysis, retrieve_context, search_history

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - runtime dependency
    FastMCP = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


def _settings():
    root = Path(os.environ.get("KDX_PROJECT_ROOT", Path.cwd())).resolve()
    return load_settings(root)


def _ensure_index() -> ProjectIndex:
    settings = _settings()
    return ensure_project_index(settings.repo_root, settings.index_path)


def _read_target(path: Path, *, line_start: int | None = None, line_end: int | None = None, max_chars: int = 2200) -> tuple[str, int, int]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    if line_start is not None and line_end is not None:
        start_idx = max(0, line_start - 1)
        end_idx = min(len(lines), line_end)
        chunk = "\n".join(lines[start_idx:end_idx])
        if len(chunk) > max_chars:
            chunk = chunk[:max_chars]
        return chunk, line_start, min(line_end, line_start + chunk.count("\n"))
    chunk = text[:max_chars]
    return chunk, 1, 1 + chunk.count("\n")


def build_server() -> Any:
    if FastMCP is None:  # pragma: no cover - runtime dependency
        raise RuntimeError("Missing dependency: install with `python3 -m pip install mcp`") from IMPORT_ERROR
    mcp = FastMCP("kdx-repo")

    @mcp.tool()
    def repo_scan(project_root: str = "") -> dict[str, Any]:
        root = Path(project_root).resolve() if project_root else _settings().repo_root
        settings = load_settings(root)
        index = scan_project(settings.repo_root, settings.index_path)
        return {
            "ok": True,
            "root": str(settings.repo_root),
            "index_path": str(settings.index_path),
            "file_count": index.file_count,
            "generated_at": index.generated_at,
        }

    @mcp.tool()
    def repo_retrieve(query: str, top_files: int = 6, char_budget: int = 12000) -> dict[str, Any]:
        settings = _settings()
        index = _ensure_index()
        token_budget = max(250, char_budget // 4)
        budget = dataclasses.replace(settings.budget, max_files=max(1, min(12, top_files)), max_total_tokens=token_budget)
        snippets = retrieve_context(settings.repo_root, index, query, budget)
        route = classify_query(query)
        return {
            "ok": True,
            "route": route.to_dict(),
            "snippets": [snippet.to_dict() for snippet in snippets],
        }

    @mcp.tool()
    def repo_read(file: str, symbol: str = "", max_chars: int = 2200, query: str = "") -> dict[str, Any]:
        settings = _settings()
        index = _ensure_index()
        resolved_symbol = symbol
        resolved_file = file
        if "::" in file:
            resolved_file, resolved_symbol = file.split("::", 1)
        target = (settings.repo_root / resolved_file).resolve()
        try:
            target.relative_to(settings.repo_root.resolve())
        except ValueError:
            return {"ok": False, "error": "outside project root"}
        if not target.exists():
            return {"ok": False, "error": "file not found", "file": resolved_file}
        if resolved_symbol:
            record = next((item for item in index.files if item.path == resolved_file), None)
            if record is not None:
                match = next((item for item in record.symbols if item.name == resolved_symbol), None)
                if match is not None:
                    content, line_start, line_end = _read_target(target, line_start=match.line_start, line_end=match.line_end, max_chars=max_chars)
                    return {
                        "ok": True,
                        "file": resolved_file,
                        "symbol": resolved_symbol,
                        "line_start": line_start,
                        "line_end": line_end,
                        "content": content,
                    }
        content, line_start, line_end = _read_target(target, max_chars=max_chars)
        return {
            "ok": True,
            "file": resolved_file,
            "symbol": resolved_symbol,
            "query": query,
            "line_start": line_start,
            "line_end": line_end,
            "content": content,
        }

    @mcp.tool()
    def repo_memory(query: str, limit: int = 5) -> dict[str, Any]:
        settings = _settings()
        history = [entry.to_dict() for entry in search_history(settings.history_path, query, limit=limit)]
        return {"ok": True, "history": history}

    @mcp.tool()
    def repo_impact(changed_files: list[str]) -> dict[str, Any]:
        index = _ensure_index()
        impacts = impact_analysis(index, changed_files)
        return {"ok": True, "impacts": impacts}

    @mcp.tool()
    def repo_neighbors(file: str, limit: int = 12) -> dict[str, Any]:
        index = _ensure_index()
        target = next((item for item in index.files if item.path == file), None)
        if target is None:
            return {"ok": False, "error": "file not indexed", "file": file}
        target_terms = set(tokenize(target.path)) | set(tokenize(" ".join(target.imports)))
        neighbors: list[dict[str, Any]] = []
        for record in index.files:
            if record.path == file:
                continue
            score = len(target_terms & set(tokenize(record.path))) + len(target_terms & set(tokenize(" ".join(record.imports))))
            if score <= 0:
                continue
            neighbors.append({
                "path": record.path,
                "score": score,
                "is_test": record.is_test,
                "summary": record.summary,
            })
        neighbors.sort(key=lambda item: (int(item["score"]), bool(item["is_test"])), reverse=True)
        return {"ok": True, "neighbors": neighbors[:limit]}

    return mcp


def main() -> int:
    server = build_server()
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
