from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from kdx.config import clear_keiro_api_key, load_settings, set_keiro_api_key
from kdx.indexer import scan_project
from kdx.keiro import KeiroClient, KeiroError, normalize_results
from kdx.token_compare import compare_prompt_tokens, compare_prompts_file
from kdx.updates import apply_update, check_for_updates, update_actions
from kdx.wrapper import build_execution_plan, format_plan, run_codex

SUBCOMMANDS = {"scan", "plan", "search", "run", "keiro", "tokens", "update"}


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _cmd_scan(args: argparse.Namespace) -> int:
    settings = load_settings(Path(args.path).resolve() if args.path else None)
    index = scan_project(settings.repo_root, settings.index_path)
    payload = {
        "root": str(settings.repo_root),
        "index_path": str(settings.index_path),
        "generated_at": index.generated_at,
        "file_count": index.file_count,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"scanned {payload['file_count']} files into {payload['index_path']}")
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    plan = format_plan(args.query, use_web=not args.no_web)
    if args.json:
        _print_json(plan)
        return 0
    route = plan["route"]
    summary = plan["summary"]
    print(f"route: {route['mode']} | needs_web={route['needs_web']}")
    for reason in route["reasons"]:
        print(f"- {reason}")
    print(f"snippets: {len(summary['snippets'])} | search_results: {len(summary['search_results'])}")
    print(f"estimated input tokens: {summary['budget']['input_tokens_estimate']}")
    print("\nprompt preview:\n")
    print(plan["prompt_preview"])
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    settings = load_settings()
    client = KeiroClient(api_key=settings.keiro_api_key, base_url=settings.keiro_base_url)
    if not client.configured():
        raise KeiroError("Missing KEIRO API key. Set KEIRO_API_KEY or KDX_KEIRO_API_KEY.")
    if args.mode == "search":
        payload = client.search(args.query, cache_search=not args.no_cache, included_urls=args.include)
    elif args.mode == "search-pro":
        payload = client.search_pro(args.query, cache_search=not args.no_cache, included_urls=args.include)
    elif args.mode == "research":
        payload = client.research(args.query, cache_search=not args.no_cache, included_urls=args.include)
    elif args.mode == "research-pro":
        payload = client.research_pro(args.query, cache_search=not args.no_cache, included_urls=args.include)
    elif args.mode == "answer":
        payload = client.answer(args.query)
    else:
        payload = client.search_engine(
            args.query,
            content_type=args.content_type,
            language=args.language,
            region=args.region,
            time_range=args.time_range,
            top_n=args.top_n,
        )
    normalized = normalize_results(payload, limit=args.limit)
    result = {"mode": args.mode, "normalized": normalized, "raw": payload if args.raw else None}
    if args.json:
        _print_json(result)
    else:
        for item in normalized:
            print(f"- {item['title']}")
            if item["url"]:
                print(f"  {item['url']}")
            if item["snippet"]:
                print(f"  {item['snippet']}")
    return 0


def _cmd_keiro(args: argparse.Namespace) -> int:
    settings = load_settings()
    if args.clear:
        path = clear_keiro_api_key(settings.global_config_path)
        payload = {
            "configured": False,
            "config_path": str(path),
            "message": "cleared persisted Keiro API key",
        }
    elif args.api_key:
        path = set_keiro_api_key(args.api_key, settings.global_config_path)
        payload = {
            "configured": True,
            "config_path": str(path),
            "message": "stored Keiro API key",
        }
    else:
        payload = {
            "configured": bool(settings.keiro_api_key),
            "config_path": str(settings.global_config_path),
            "message": "Keiro API key configured" if settings.keiro_api_key else "Keiro API key not configured",
        }
    if args.json:
        _print_json(payload)
    else:
        print(payload["message"])
        print(payload["config_path"])
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if args.print_plan:
        plan = build_execution_plan(args.query, use_web=not args.no_web)
        _print_json({
            "route": plan["route"].to_dict(),
            "summary": plan["summary"],
            "prompt": plan["prompt"],
        })
        return 0
    return run_codex(args.query, exec_mode=args.exec_mode, use_web=not args.no_web, model=args.model)


def _cmd_tokens(args: argparse.Namespace) -> int:
    model = args.model or None
    if args.prompts_file:
        result = compare_prompts_file(
            Path(args.prompts_file),
            model=model,
            use_web=not args.no_web,
            timeout_seconds=args.timeout,
        )
    else:
        result = compare_prompt_tokens(
            args.query,
            model=model,
            use_web=not args.no_web,
            timeout_seconds=args.timeout,
        )
    if args.json:
        _print_json(result)
        return 0
    prompts = result["prompts"]
    print(f"repo: {result['repo_root']}")
    print(f"model: {result['model']}")
    print(f"prompt_count: {len(prompts)}")
    for row in prompts:
        print("")
        print(f"prompt {row['index']}: {row['prompt']}")
        print(f"  vanilla: in={row['vanilla']['input_tokens']} cached={row['vanilla']['cached_input_tokens']} out={row['vanilla']['output_tokens']} total={row['vanilla']['total_tokens']}")
        print(f"  kdx:     in={row['kdx']['input_tokens']} cached={row['kdx']['cached_input_tokens']} out={row['kdx']['output_tokens']} total={row['kdx']['total_tokens']}")
        print(f"  delta:   {row['delta_total_tokens']} tokens ({row['delta_percent']}%) | est_prompt={row['kdx_prompt_tokens_estimate']}")
    totals = result["totals"]
    print("")
    print(f"total vanilla: {totals['vanilla_total_tokens']}")
    print(f"total kdx:     {totals['kdx_total_tokens']}")
    print(f"delta total:   {totals['delta_total_tokens']} tokens ({totals['delta_percent']}%)")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    settings = load_settings()
    status = check_for_updates(settings, force=args.check_now or args.check)
    actions = update_actions(status)
    if args.check or args.json:
        payload = {
            "status": status,
            "actions": actions,
        }
        if args.json:
            _print_json(payload)
        else:
            print(f"current: {status['current_version']}")
            if status.get("latest_version"):
                print(f"latest:  {status['latest_version']}")
            elif status.get("latest_commit"):
                print(f"latest commit: {status['latest_commit'][:12]}")
            if status.get("update_available"):
                print("status:  update available")
            elif status.get("ok"):
                print("status:  up to date")
            else:
                print("status:  could not check")
            if status.get("release_url"):
                print(f"source:  {status['release_url']}")
            if status.get("error"):
                print(f"note:    {status['error']}")
            print("")
            print("update:")
            print(f"  {actions['update']}")
            print("rollback:")
            print(f"  {actions['rollback']}")
        return 0
    if args.rollback:
        result = apply_update(settings, rollback_ref=args.rollback)
        print(f"rolled back KDX in {result['repo_root']} to {args.rollback}")
        return 0
    if not status.get("update_available"):
        print("KDX is already up to date.")
        return 0
    result = apply_update(settings)
    latest = status.get("latest_version") or status.get("latest_commit", "")[:12]
    print(f"updated KDX in {result['repo_root']}")
    if latest:
        print(f"target: {latest}")
    print("restart with: kdx")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kdx", description="Token-efficient Codex wrapper with repo indexing and Keiro search")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="scan the current repo into .kdx/index.json")
    scan.add_argument("path", nargs="?", help="path to the repo root")
    scan.add_argument("--json", action="store_true")
    scan.set_defaults(func=_cmd_scan)

    plan = subparsers.add_parser("plan", help="show KDX routing, retrieval, and prompt plan")
    plan.add_argument("query")
    plan.add_argument("--no-web", action="store_true")
    plan.add_argument("--json", action="store_true")
    plan.set_defaults(func=_cmd_plan)

    search = subparsers.add_parser("search", help="run a direct Keiro search")
    search.add_argument("query")
    search.add_argument("--mode", choices=["search", "search-pro", "research", "research-pro", "answer", "search-engine"], default="search-pro")
    search.add_argument("--include", action="append", default=[], help="restrict to specific domains or URLs")
    search.add_argument("--no-cache", action="store_true")
    search.add_argument("--content-type", default="general")
    search.add_argument("--language", default="en")
    search.add_argument("--region")
    search.add_argument("--time-range", choices=["day", "week", "month", "year"])
    search.add_argument("--top-n", type=int, default=10)
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--raw", action="store_true")
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=_cmd_search)

    keiro = subparsers.add_parser("keiro", help="store or inspect the persisted Keiro API key")
    keiro.add_argument("api_key", nargs="?", help="Keiro API key to store")
    keiro.add_argument("--clear", action="store_true", help="remove the persisted Keiro API key")
    keiro.add_argument("--json", action="store_true")
    keiro.set_defaults(func=_cmd_keiro)

    run = subparsers.add_parser("run", help="launch the real Codex CLI with KDX context and MCP tools")
    run.add_argument("query", nargs="?", default="", help="optional initial task; omit to open interactive Codex with KDX attached")
    run.add_argument("--exec-mode", action="store_true", help="run codex exec instead of interactive codex")
    run.add_argument("--no-web", action="store_true")
    run.add_argument("--model")
    run.add_argument("--print-plan", action="store_true", help="print the generated prompt and exit")
    run.set_defaults(func=_cmd_run)

    tokens = subparsers.add_parser("tokens", help="compare exact Codex token usage for vanilla Codex vs KDX")
    tokens.add_argument("query", nargs="?", help="single prompt to compare")
    tokens.add_argument("--prompts-file", help="path to a file with one prompt per line")
    tokens.add_argument("--no-web", action="store_true", help="disable KDX web preload during comparison")
    tokens.add_argument("--model", help="override model for both variants")
    tokens.add_argument("--timeout", type=int, default=900, help="timeout per variant run in seconds")
    tokens.add_argument("--json", action="store_true")
    tokens.set_defaults(func=_cmd_tokens)

    update = subparsers.add_parser("update", help="update the current KDX git clone from GitHub")
    update.add_argument("--check", action="store_true", help="check for updates without applying them")
    update.add_argument("--check-now", action="store_true", help="ignore the local update cache and check GitHub now")
    update.add_argument("--rollback", help="checkout a git ref or tag and reinstall KDX there")
    update.add_argument("--json", action="store_true")
    update.set_defaults(func=_cmd_update)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "help":
        argv = ["--help"]
    elif argv and argv[0] == "/keiro":
        argv = ["keiro", *argv[1:]]
    elif argv and argv[0] not in SUBCOMMANDS and argv[0] not in {"-h", "--help"}:
        argv = ["run", *argv]
    elif not argv:
        argv = ["run"]
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) == "tokens" and not getattr(args, "query", None) and not getattr(args, "prompts_file", None):
        parser.error("tokens requires a query or --prompts-file")
    try:
        return int(args.func(args))
    except KeiroError as exc:
        parser.exit(2, f"kdx: {exc}\n")
    except RuntimeError as exc:
        parser.exit(2, f"kdx: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
