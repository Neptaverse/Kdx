from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from kdx.budget import estimate_tokens
from kdx.codex_home import prepared_codex_home
from kdx.config import KdxSettings, load_settings
from kdx.indexer import ensure_project_index, scan_project
from kdx.keiro import KeiroError
from kdx.models import ProjectIndex
from kdx.retrieval import (
    append_history,
    budget_for_query,
    build_query_profile,
    classify_query,
    make_history_entry,
    plan_summary,
    render_context,
    retrieve_context,
    search_history,
)
from kdx.search_service import execute_context_search, render_web_evidence_block
from kdx.ui import print_launch_panel, should_render_banner
from kdx.updates import (
    apply_update,
    check_for_updates,
    format_update_notice,
    should_auto_apply_updates,
    should_check_for_updates,
    update_settings,
)

STRONG_WEB_TERMS = {
    "latest",
    "current",
    "today",
    "recent",
    "release",
    "releases",
    "changelog",
    "docs",
    "documentation",
    "reference",
    "sdk",
    "manual",
    "github",
    "pypi",
    "npm",
    "news",
}
KDX_SESSION_INSTRUCTIONS = "\n".join(
    [
        "You are running under KDX, a Codex wrapper optimized for token efficiency and evidence-driven coding.",
        "Use the `kdx_repo` MCP tools for repo understanding before broad shell reads, starting with `repo_retrieve` and `repo_read`.",
        "Use the `kdx_web` MCP tools for external or fresh knowledge instead of guessing, starting with `keiro_context_search` and `keiro_fetch_best`.",
        "Prefer symbol-targeted reads, compact evidence, and the smallest sufficient context.",
        "Wait for the user's first task before taking action.",
    ]
)


def ensure_index(settings: KdxSettings) -> ProjectIndex:
    if settings.auto_init:
        return ensure_project_index(settings.repo_root, settings.index_path)
    if settings.index_path.exists():
        return ensure_project_index(settings.repo_root, settings.index_path)
    return scan_project(settings.repo_root, settings.index_path)


def initialize_workspace(settings: KdxSettings) -> ProjectIndex | None:
    if not settings.auto_init:
        return None
    return ensure_index(settings)


def _ensure_mcp_runtime() -> None:
    if importlib.util.find_spec("mcp") is not None:
        return
    raise RuntimeError(
        "Missing runtime dependency `mcp`. Bootstrap KDX first with "
        "`python bootstrap.py --setup-only`; that installs the global `kdx` command too."
    )


def maybe_keiro_search(settings: KdxSettings, query: str, enabled: bool) -> tuple[list[dict[str, Any]], list[str]]:
    if not enabled or not settings.keiro_api_key:
        return [], []
    try:
        result = execute_context_search(settings, query, limit=settings.budget.max_search_results)
    except KeiroError as exc:
        return [{"title": "keiro-error", "url": "", "snippet": str(exc)}], [query]
    plan = result.get("plan", {})
    return result.get("evidence", []), [str(plan.get("query", query))]


def should_preload_web(
    profile,
    route_mode: str,
    *,
    has_local_context: bool,
) -> bool:
    if route_mode == "external":
        return True
    if route_mode != "hybrid":
        return False
    if STRONG_WEB_TERMS & profile.raw_terms:
        return True
    if profile.path_hints or profile.identifier_hints:
        return False
    if profile.answer_only and has_local_context:
        return False
    return False


def should_auto_update_on_startup(
    query: str,
    *,
    exec_mode: bool,
    environ: dict[str, str] | None = None,
) -> bool:
    if exec_mode or query.strip():
        return False
    return should_auto_apply_updates(environ)


def build_bootstrap_prompt(
    query: str,
    route_mode: str,
    route_reasons: list[str],
    local_context: str,
    history_items: list[dict[str, Any]],
    search_results: list[dict[str, Any]],
    *,
    answer_only: bool = False,
) -> str:
    history_block = "\n".join(
        f"- {item['created_at']} | {item['route']} | {item['query']} | files={', '.join(item['files'][:4])}"
        for item in history_items[:5]
    )
    web_block = render_web_evidence_block(
        search_results,
        char_budget=420 if answer_only else 650,
        max_items=1 if answer_only else 2,
    )
    parts = [
        "KDX TASK CONTEXT",
        f"ROUTE: {route_mode}",
        *(f"- {reason}" for reason in route_reasons),
        "",
        "LOCAL CONTEXT:",
        local_context or "(none preloaded)",
    ]
    if answer_only:
        parts.extend(
            [
                "",
                "MODE: answer-only",
                "- Answer from the provided context first.",
                "- Avoid shell commands, extra file reads, or broad exploration unless the context is insufficient.",
                "- If evidence is missing, say exactly what is missing instead of wandering.",
            ]
        )
    if history_block:
        parts.extend(["", "RECENT TASK MEMORY:", history_block])
    if web_block:
        parts.extend(["", "WEB EVIDENCE:", web_block])
    parts.extend(["", "USER TASK:", query])
    return "\n".join(parts).strip()


def build_execution_plan(query: str, settings: KdxSettings | None = None, use_web: bool | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    if not query.strip():
        route = classify_query("interactive startup")
        route.mode = "startup"
        route.needs_web = False
        route.reasons = ["interactive startup without a preloaded task"]
        summary = plan_summary(route, [], [], settings.budget)
        summary["budget"]["input_tokens_estimate"] = 0
        return {
            "query": query,
            "route": route,
            "snippets": [],
            "history": [],
            "search_results": [],
            "search_queries": [],
            "prompt": "",
            "summary": summary,
        }
    profile = build_query_profile(query)
    budget = budget_for_query(settings.budget, query)
    index = ensure_index(settings)
    route = classify_query(query)
    snippets = [] if route.mode == "external" else retrieve_context(settings.repo_root, index, query, budget)
    web_enabled = (
        should_preload_web(profile, route.mode, has_local_context=bool(snippets))
        if use_web is None
        else use_web
    )
    context_blob = render_context(snippets, budget)
    history = [entry.to_dict() for entry in search_history(settings.history_path, query, limit=5)]
    search_results, search_queries = maybe_keiro_search(settings, query, enabled=web_enabled)
    prompt = build_bootstrap_prompt(
        query,
        route.mode,
        route.reasons,
        context_blob,
        history,
        search_results,
        answer_only=profile.answer_only,
    )
    summary = plan_summary(route, snippets, search_results, budget)
    summary["budget"]["input_tokens_estimate"] = estimate_tokens(prompt)
    return {
        "query": query,
        "route": route,
        "snippets": snippets,
        "history": history,
        "search_results": search_results,
        "search_queries": search_queries,
        "prompt": prompt,
        "summary": summary,
    }


def run_codex(query: str, *, exec_mode: bool = False, use_web: bool | None = None, model: str | None = None) -> int:
    _ensure_mcp_runtime()
    settings = load_settings()
    updater_settings = update_settings(settings)
    env = os.environ.copy()
    update_notice = ""
    if should_check_for_updates(env):
        status = check_for_updates(updater_settings, environ=env)
        should_auto_update = (
            should_auto_update_on_startup(query, exec_mode=exec_mode, environ=env)
            and bool(status.get("update_available"))
        )
        if should_auto_update:
            try:
                apply_update(updater_settings)
                updater_settings = update_settings(updater_settings)
                status = check_for_updates(updater_settings, environ=env)
                update_notice = "UPDATE: new update installed automatically."
            except Exception as exc:
                update_notice = f"UPDATE: new update available (auto-update skipped: {exc}) | run `kdx update`"
        if not update_notice:
            update_notice = format_update_notice(status)
    index = initialize_workspace(settings)
    plan = build_execution_plan(query, settings=settings, use_web=use_web)
    if query.strip():
        append_history(
            settings.history_path,
            make_history_entry(query, plan["route"], plan["snippets"], plan["search_queries"]),
        )
    with prepared_codex_home(settings, session_instructions=KDX_SESSION_INSTRUCTIONS) as codex_home:
        env["CODEX_HOME"] = str(codex_home)
        env["CODEX_SQLITE_HOME"] = str(settings.base_codex_home)
        env["KDX_PROJECT_ROOT"] = str(settings.repo_root)
        env["KDX_INDEX_PATH"] = str(settings.index_path)
        env["KDX_HISTORY_PATH"] = str(settings.history_path)
        env["KDX_KEIRO_BASE_URL"] = settings.keiro_base_url
        if settings.keiro_api_key:
            env["KDX_KEIRO_API_KEY"] = settings.keiro_api_key
        package_src = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = package_src if not env.get("PYTHONPATH") else f"{package_src}{os.pathsep}{env['PYTHONPATH']}"
        command = [settings.codex_binary]
        if exec_mode:
            command.append("exec")
        if model or settings.model:
            command.extend(["--model", model or settings.model])
        if plan["prompt"]:
            command.append(plan["prompt"])
        if should_render_banner(exec_mode=exec_mode, environ=env):
            print_launch_panel(
                settings.repo_root,
                file_count=index.file_count if index is not None else None,
                keiro_configured=bool(settings.keiro_api_key),
                update_notice=update_notice,
                environ=env,
            )
        process = subprocess.run(command, cwd=settings.repo_root, env=env, check=False)
        return int(process.returncode)


def format_plan(query: str, *, settings: KdxSettings | None = None, use_web: bool | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    plan = build_execution_plan(query, settings=settings, use_web=use_web)
    return {
        "query": query,
        "route": plan["route"].to_dict(),
        "summary": plan["summary"],
        "history": plan["history"],
        "prompt_preview": plan["prompt"][:4000],
    }


def shell_preview(query: str, exec_mode: bool = False) -> str:
    subcommand = "exec " if exec_mode else ""
    return f"kdx will run: {shlex.join(['codex', *(['exec'] if exec_mode else []), query])}"
