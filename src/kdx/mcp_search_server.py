from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from kdx.config import load_settings
from kdx.keiro import KeiroClient, KeiroError, normalize_results
from kdx.search_service import execute_context_search, render_web_evidence_block

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


def _client() -> KeiroClient:
    settings = _settings()
    return KeiroClient(api_key=settings.keiro_api_key, base_url=settings.keiro_base_url)


def _wrap(payload: dict[str, Any], limit: int = 5) -> dict[str, Any]:
    return {
        "ok": True,
        "normalized": normalize_results(payload, limit=limit),
        "raw": payload,
    }


def build_server() -> Any:
    if FastMCP is None:  # pragma: no cover - runtime dependency
        raise RuntimeError("Missing dependency: install with `python3 -m pip install mcp`") from IMPORT_ERROR
    mcp = FastMCP("kdx-web")

    @mcp.tool()
    def keiro_health() -> dict[str, Any]:
        try:
            return _client().health()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @mcp.tool()
    def keiro_context_search(query: str, limit: int = 3) -> dict[str, Any]:
        settings = _settings()
        result = execute_context_search(settings, query, limit=limit)
        evidence = result.get("evidence", [])
        return {
            "ok": True,
            "plan": result.get("plan", {}),
            "evidence": evidence,
            "compact": render_web_evidence_block(evidence, char_budget=900, max_items=min(limit, 3)),
        }

    @mcp.tool()
    def keiro_fetch_best(query: str) -> dict[str, Any]:
        settings = _settings()
        result = execute_context_search(settings, query, limit=1)
        evidence = result.get("evidence", [])
        return {
            "ok": True,
            "plan": result.get("plan", {}),
            "best": evidence[0] if evidence else None,
        }

    @mcp.tool()
    def keiro_search(query: str, cache_search: bool = True, included_urls: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
        payload = _client().search(query, cache_search=cache_search, included_urls=included_urls)
        return _wrap(payload, limit=limit)

    @mcp.tool()
    def keiro_search_pro(query: str, cache_search: bool = True, included_urls: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
        payload = _client().search_pro(query, cache_search=cache_search, included_urls=included_urls)
        return _wrap(payload, limit=limit)

    @mcp.tool()
    def keiro_research(query: str, cache_search: bool = True, included_urls: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
        payload = _client().research(query, cache_search=cache_search, included_urls=included_urls)
        return _wrap(payload, limit=limit)

    @mcp.tool()
    def keiro_research_pro(query: str, cache_search: bool = True, included_urls: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
        payload = _client().research_pro(query, cache_search=cache_search, included_urls=included_urls)
        return _wrap(payload, limit=limit)

    @mcp.tool()
    def keiro_answer(query: str) -> dict[str, Any]:
        payload = _client().answer(query)
        return _wrap(payload, limit=5)

    @mcp.tool()
    def keiro_crawl(url: str, limit: int = 3) -> dict[str, Any]:
        payload = _client().crawl(url)
        return _wrap(payload, limit=limit)

    @mcp.tool()
    def keiro_search_engine(
        query: str,
        content_type: str = "general",
        language: str = "en",
        region: str = "",
        time_range: str = "",
        top_n: int = 10,
        limit: int = 5,
    ) -> dict[str, Any]:
        payload = _client().search_engine(
            query,
            content_type=content_type,
            language=language,
            region=region or None,
            time_range=time_range or None,
            top_n=top_n,
        )
        return _wrap(payload, limit=limit)

    @mcp.tool()
    def keiro_memory_search(query: str, workspace_id: str = "", task_type: str = "web_search", limit: int = 5) -> dict[str, Any]:
        settings = _settings()
        payload = _client().memory_search(query, workspace_id=workspace_id or settings.workspace_id, task_type=task_type)
        return _wrap(payload, limit=limit)

    return mcp


def main() -> None:
    try:
        server = build_server()
        server.run()
    except KeiroError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
