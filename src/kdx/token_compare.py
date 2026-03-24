from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from kdx.codex_home import prepared_codex_home
from kdx.config import KdxSettings, load_settings
from kdx.wrapper import KDX_SESSION_INSTRUCTIONS, build_execution_plan


def parse_turn_usage(stdout: str) -> dict[str, int]:
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "turn.completed":
            continue
        raw = payload.get("usage", {})
        usage = {
            "input_tokens": int(raw.get("input_tokens", 0)),
            "cached_input_tokens": int(raw.get("cached_input_tokens", 0)),
            "output_tokens": int(raw.get("output_tokens", 0)),
            "total_tokens": int(raw.get("input_tokens", 0)) + int(raw.get("cached_input_tokens", 0)) + int(raw.get("output_tokens", 0)),
        }
    if usage["total_tokens"] <= 0:
        raise RuntimeError(f"no token usage found in output tail: {stdout[-1200:]}")
    return usage


def compare_prompt_tokens(
    prompt: str,
    *,
    settings: KdxSettings | None = None,
    model: str | None = None,
    use_web: bool = True,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    settings = settings or load_settings()
    prompts = [prompt]
    return _compare_prompts(prompts, settings=settings, model=model, use_web=use_web, timeout_seconds=timeout_seconds)


def compare_prompts_file(
    prompts_file: Path,
    *,
    settings: KdxSettings | None = None,
    model: str | None = None,
    use_web: bool = True,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    prompts = [line.strip() for line in prompts_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return _compare_prompts(prompts, settings=settings or load_settings(), model=model, use_web=use_web, timeout_seconds=timeout_seconds)


def _compare_prompts(
    prompts: list[str],
    *,
    settings: KdxSettings,
    model: str | None,
    use_web: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    active_model = model or settings.model
    rows: list[dict[str, Any]] = []
    for index, prompt in enumerate(prompts, start=1):
        kdx_plan = build_execution_plan(prompt, settings=settings, use_web=use_web)
        vanilla_usage = _run_vanilla(settings, prompt, model=active_model, timeout_seconds=timeout_seconds)
        kdx_usage = _run_kdx(
            settings,
            kdx_plan["prompt"],
            model=active_model,
            timeout_seconds=timeout_seconds,
        )
        delta_total_tokens = vanilla_usage["total_tokens"] - kdx_usage["total_tokens"]
        delta_percent = round((delta_total_tokens / vanilla_usage["total_tokens"] * 100.0), 1) if vanilla_usage["total_tokens"] else 0.0
        rows.append(
            {
                "index": index,
                "prompt": prompt,
                "vanilla": vanilla_usage,
                "kdx": kdx_usage,
                "delta_total_tokens": delta_total_tokens,
                "delta_percent": delta_percent,
                "kdx_prompt_tokens_estimate": int(kdx_plan["summary"]["budget"]["input_tokens_estimate"]),
                "kdx_snippets": len(kdx_plan["summary"]["snippets"]),
                "kdx_search_results": len(kdx_plan["summary"]["search_results"]),
            }
        )
    vanilla_total = sum(row["vanilla"]["total_tokens"] for row in rows)
    kdx_total = sum(row["kdx"]["total_tokens"] for row in rows)
    delta_total = vanilla_total - kdx_total
    delta_percent = round((delta_total / vanilla_total * 100.0), 1) if vanilla_total else 0.0
    return {
        "repo_root": str(settings.repo_root),
        "model": active_model,
        "prompts": rows,
        "totals": {
            "vanilla_total_tokens": vanilla_total,
            "kdx_total_tokens": kdx_total,
            "delta_total_tokens": delta_total,
            "delta_percent": delta_percent,
        },
    }


def _run_vanilla(settings: KdxSettings, prompt: str, *, model: str, timeout_seconds: int) -> dict[str, int]:
    config = textwrap.dedent(
        f'''
        model = "{model}"

        [projects."{settings.repo_root}"]
        trust_level = "trusted"
        '''
    ).strip()
    with _vanilla_codex_home(settings, config) as codex_home:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)
        env["CODEX_SQLITE_HOME"] = str(settings.base_codex_home)
        stdout = _run_codex_exec(settings, prompt, env=env, model=model, timeout_seconds=timeout_seconds)
    return parse_turn_usage(stdout)


def _run_kdx(
    settings: KdxSettings,
    prompt: str,
    *,
    model: str,
    timeout_seconds: int,
) -> dict[str, int]:
    package_src = str(Path(__file__).resolve().parents[1])
    with prepared_codex_home(settings, session_instructions=KDX_SESSION_INSTRUCTIONS) as codex_home:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)
        env["CODEX_SQLITE_HOME"] = str(settings.base_codex_home)
        env["KDX_PROJECT_ROOT"] = str(settings.repo_root)
        env["KDX_INDEX_PATH"] = str(settings.index_path)
        env["KDX_HISTORY_PATH"] = str(settings.history_path)
        env["KDX_KEIRO_BASE_URL"] = settings.keiro_base_url
        env["KDX_NO_BANNER"] = "1"
        if settings.keiro_api_key:
            env["KDX_KEIRO_API_KEY"] = settings.keiro_api_key
        env["PYTHONPATH"] = package_src if not env.get("PYTHONPATH") else f"{package_src}{os.pathsep}{env['PYTHONPATH']}"
        stdout = _run_codex_exec(settings, prompt, env=env, model=model, timeout_seconds=timeout_seconds)
    return parse_turn_usage(stdout)


def _run_codex_exec(
    settings: KdxSettings,
    prompt: str,
    *,
    env: dict[str, str],
    model: str,
    timeout_seconds: int,
) -> str:
    command = [
        settings.codex_binary,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-C",
        str(settings.repo_root),
        "--model",
        model,
        prompt,
    ]
    result = subprocess.run(
        command,
        cwd=str(settings.repo_root),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"codex exec failed: stderr={result.stderr[-1000:]} stdout={result.stdout[-1000:]}")
    return result.stdout


@contextmanager
def _vanilla_codex_home(settings: KdxSettings, config_text: str) -> Iterator[Path]:
    runtime_root = settings.data_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kdx-vanilla-codex-home-", dir=runtime_root) as temp_dir:
        temp_home = Path(temp_dir)
        for filename in ("auth.json", "models_cache.json", "version.json"):
            source = settings.base_codex_home / filename
            if source.exists():
                shutil.copy2(source, temp_home / filename)
        rules_dir = settings.base_codex_home / "rules"
        if rules_dir.exists():
            shutil.copytree(rules_dir, temp_home / "rules", dirs_exist_ok=True)
        (temp_home / "config.toml").write_text(config_text.strip() + "\n", encoding="utf-8")
        yield temp_home
