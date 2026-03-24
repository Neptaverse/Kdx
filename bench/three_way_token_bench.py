from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_FILE = ROOT / "bench" / "prompts_kdx_repo.txt"
KDX_PYTHON = ROOT / ".venv" / "bin" / "python"
DG_PYTHON = Path(os.environ.get("DG_VENV_PYTHON", str(Path.home() / ".dual-graph" / "venv" / "bin" / "python3")))
DG_GRAPH_BUILDER = Path("/home/manas/codex-pro/Codex-CLI-Compact/bin/graph_builder.py")
DG_MCP_SERVER = Path("/home/manas/codex-pro/Codex-CLI-Compact/bin/mcp_graph_server.py")
BASE_CODEX_HOME = Path.home() / ".codex"
MODEL = os.environ.get("KDX_BENCH_MODEL", "gpt-5.4")
REPO_SOURCE = Path(os.environ.get("KDX_BENCH_REPO", str(ROOT))).resolve()
WORK_ROOT = Path(os.environ.get("KDX_BENCH_WORKDIR", str(ROOT / ".bench" / "three-way"))).resolve()
MAX_PROMPTS = int(os.environ.get("KDX_BENCH_MAX_PROMPTS", "0"))


def log(message: str) -> None:
    print(f"[bench] {message}", file=sys.stderr, flush=True)


def load_prompts() -> list[str]:
    prompts = [line.strip() for line in PROMPTS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if MAX_PROMPTS > 0:
        return prompts[:MAX_PROMPTS]
    return prompts


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, text=True, capture_output=True, timeout=timeout)


def ensure_prereqs() -> None:
    missing: list[str] = []
    if not KDX_PYTHON.exists():
        missing.append(str(KDX_PYTHON))
    if not DG_PYTHON.exists():
        missing.append(str(DG_PYTHON))
    if not BASE_CODEX_HOME.joinpath("auth.json").exists():
        missing.append(str(BASE_CODEX_HOME / "auth.json"))
    if missing:
        raise RuntimeError(f"missing prerequisites: {missing}")


def find_free_port(start: int = 8800, end: int = 8899) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port found")


def wait_for_port(port: int, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"server on port {port} did not become ready")


def copy_repo(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    exclude = shutil.ignore_patterns(
        ".git",
        "node_modules",
        "target",
        ".venv",
        ".kdx",
        ".dual-graph",
        ".bench",
        "__pycache__",
        ".pytest_cache",
        "*.pyc",
        "*.pyo",
    )
    shutil.copytree(src, dest, ignore=exclude)


def prompt_usage(stdout: str) -> tuple[dict[str, int], str]:
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    answer = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "item.completed":
            item = obj.get("item", {})
            if item.get("type") == "agent_message":
                answer = str(item.get("text", "")).strip()
        if obj.get("type") == "turn.completed":
            raw = obj.get("usage", {})
            usage = {
                "input_tokens": int(raw.get("input_tokens", 0)),
                "cached_input_tokens": int(raw.get("cached_input_tokens", 0)),
                "output_tokens": int(raw.get("output_tokens", 0)),
                "total_tokens": int(raw.get("input_tokens", 0)) + int(raw.get("cached_input_tokens", 0)) + int(raw.get("output_tokens", 0)),
            }
    if usage["total_tokens"] <= 0:
        raise RuntimeError(f"no token usage found in output tail: {stdout[-1200:]}")
    return usage, answer


def create_codex_home(config_text: str) -> tempfile.TemporaryDirectory[str]:
    temp = tempfile.TemporaryDirectory(prefix="kdx-bench-codex-home-", dir=str(WORK_ROOT))
    home = Path(temp.name)
    for filename in ("auth.json", "models_cache.json", "version.json"):
        source = BASE_CODEX_HOME / filename
        if source.exists():
            shutil.copy2(source, home / filename)
    rules_dir = BASE_CODEX_HOME / "rules"
    if rules_dir.exists():
        shutil.copytree(rules_dir, home / "rules", dirs_exist_ok=True)
    (home / "config.toml").write_text(config_text.strip() + "\n", encoding="utf-8")
    return temp


def base_config(project_dir: Path) -> str:
    return textwrap.dedent(
        f'''
        model = "{MODEL}"

        [projects."{project_dir}"]
        trust_level = "trusted"
        '''
    )


def run_vanilla(project_dir: Path, prompt: str) -> tuple[dict[str, int], str]:
    config = base_config(project_dir)
    temp = create_codex_home(config)
    try:
        env = os.environ.copy()
        env["CODEX_HOME"] = temp.name
        env["CODEX_SQLITE_HOME"] = str(BASE_CODEX_HOME)
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-C", str(project_dir), "--model", MODEL, prompt]
        res = run(cmd, env=env, cwd=project_dir)
        if res.returncode != 0:
            raise RuntimeError(f"vanilla failed: stderr={res.stderr[-1000:]} stdout={res.stdout[-1000:]}")
        return prompt_usage(res.stdout)
    finally:
        temp.cleanup()


def ensure_dual_graph_policy(project_dir: Path) -> None:
    policy = textwrap.dedent(
        '''
        # Dual-Graph Context Policy

        Use the local dual-graph MCP server for efficient code navigation.

        Rules:
        - Always call graph_continue first before broad exploration.
        - Prefer graph_read on recommended files over broad search.
        - Keep answers concise and do not modify files.
        '''
    ).strip() + "\n"
    (project_dir / "CODEX.md").write_text(policy, encoding="utf-8")
    gitignore = project_dir / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = {line for line in existing.splitlines() if line.strip()}
    lines.update({".dual-graph/", ".dual-graph-context/"})
    gitignore.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")


@contextmanager
def dual_graph_server(project_dir: Path) -> Iterator[str]:
    data_dir = project_dir / ".dual-graph"
    data_dir.mkdir(parents=True, exist_ok=True)
    log(f"building dual-graph index for {project_dir}")
    scan = run([str(DG_PYTHON), str(DG_GRAPH_BUILDER), "--root", str(project_dir), "--out", str(data_dir / "info_graph.json")], cwd=project_dir)
    if scan.returncode != 0:
        raise RuntimeError(f"dual-graph scan failed: {scan.stderr[-1000:]}")
    port = find_free_port()
    env = os.environ.copy()
    env["DG_DATA_DIR"] = str(data_dir)
    env["DUAL_GRAPH_PROJECT_ROOT"] = str(project_dir)
    env["DG_BASE_URL"] = f"http://127.0.0.1:{port}"
    env["PORT"] = str(port)
    proc = subprocess.Popen(
        [str(DG_PYTHON), str(DG_MCP_SERVER)],
        cwd=str(project_dir),
        env=env,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_port(port)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def run_graperoot(project_dir: Path, prompt: str, mcp_url: str) -> tuple[dict[str, int], str]:
    ensure_dual_graph_policy(project_dir)
    config = base_config(project_dir) + textwrap.dedent(
        f'''

        [mcp_servers.dual_graph]
        url = "{mcp_url}"
        '''
    )
    temp = create_codex_home(config)
    try:
        env = os.environ.copy()
        env["CODEX_HOME"] = temp.name
        env["CODEX_SQLITE_HOME"] = str(BASE_CODEX_HOME)
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-C", str(project_dir), "--model", MODEL, prompt]
        res = run(cmd, env=env, cwd=project_dir)
        if res.returncode != 0:
            raise RuntimeError(f"graperoot failed: stderr={res.stderr[-1000:]} stdout={res.stdout[-1000:]}")
        return prompt_usage(res.stdout)
    finally:
        temp.cleanup()


def kdx_prompt_and_env(project_dir: Path, prompt: str) -> tuple[str, dict[str, str], str]:
    env = os.environ.copy()
    env["KDX_PROJECT_ROOT"] = str(project_dir)
    env["KDX_KEIRO_BASE_URL"] = os.environ.get("KDX_KEIRO_BASE_URL", "https://kierolabs.space/api")
    if os.environ.get("KEIRO_API_KEY"):
        env["KDX_KEIRO_API_KEY"] = os.environ["KEIRO_API_KEY"]
    helper = textwrap.dedent(
        f'''
        import json
        import os
        import sys
        from pathlib import Path
        sys.path.insert(0, {str(ROOT / 'src')!r})
        from kdx.config import load_settings
        from kdx.indexer import scan_project
        from kdx.wrapper import build_execution_plan

        root = Path({str(project_dir)!r})
        settings = load_settings(root)
        scan_project(settings.repo_root, settings.index_path)
        plan = build_execution_plan({prompt!r}, settings=settings, use_web=False)
        print(json.dumps({{
            "prompt": plan["prompt"],
            "index_path": str(settings.index_path),
            "history_path": str(settings.history_path),
        }}))
        '''
    )
    res = run([str(KDX_PYTHON), "-c", helper], env=env, cwd=project_dir)
    if res.returncode != 0:
        raise RuntimeError(f"kdx prompt build failed: {res.stderr[-1000:]}")
    payload = json.loads(res.stdout.strip())
    return str(payload["prompt"]), env, str(payload["index_path"])


def run_kdx(project_dir: Path, prompt: str) -> tuple[dict[str, int], str]:
    prompt_text, env, index_path = kdx_prompt_and_env(project_dir, prompt)
    config = base_config(project_dir) + textwrap.dedent(
        f'''

        [mcp_servers.kdx_code]
        command = "{KDX_PYTHON}"
        args = ["-m", "kdx.mcp_code_server"]
        startup_timeout_sec = 20
        tool_timeout_sec = 45

        [mcp_servers.kdx_search]
        command = "{KDX_PYTHON}"
        args = ["-m", "kdx.mcp_search_server"]
        startup_timeout_sec = 20
        tool_timeout_sec = 45
        '''
    )
    temp = create_codex_home(config)
    try:
        env = dict(env)
        env["CODEX_HOME"] = temp.name
        env["CODEX_SQLITE_HOME"] = str(BASE_CODEX_HOME)
        env["KDX_PROJECT_ROOT"] = str(project_dir)
        env["KDX_INDEX_PATH"] = index_path
        env["KDX_HISTORY_PATH"] = str(project_dir / ".kdx" / "history.jsonl")
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "-C", str(project_dir), "--model", MODEL, prompt_text]
        res = run(cmd, env=env, cwd=project_dir)
        if res.returncode != 0:
            raise RuntimeError(f"kdx failed: stderr={res.stderr[-1000:]} stdout={res.stdout[-1000:]}")
        return prompt_usage(res.stdout)
    finally:
        temp.cleanup()


def main() -> int:
    ensure_prereqs()
    prompts = load_prompts()
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    baseline_dir = WORK_ROOT / "baseline"
    graph_dir = WORK_ROOT / "graperoot"
    kdx_dir = WORK_ROOT / "kdx"
    log(f"preparing benchmark repo copies under {WORK_ROOT}")
    copy_repo(REPO_SOURCE, baseline_dir)
    copy_repo(REPO_SOURCE, graph_dir)
    copy_repo(REPO_SOURCE, kdx_dir)

    results: list[dict[str, Any]] = []
    with dual_graph_server(graph_dir) as mcp_url:
        for index, prompt in enumerate(prompts, start=1):
            log(f"prompt {index}/{len(prompts)}: vanilla")
            vanilla_usage, vanilla_answer = run_vanilla(baseline_dir, prompt)
            log(f"prompt {index}/{len(prompts)}: graperoot")
            graph_usage, graph_answer = run_graperoot(graph_dir, prompt, mcp_url)
            log(f"prompt {index}/{len(prompts)}: kdx")
            kdx_usage, kdx_answer = run_kdx(kdx_dir, prompt)
            row = {
                "index": index,
                "prompt": prompt,
                "vanilla": vanilla_usage,
                "graperoot": graph_usage,
                "kdx": kdx_usage,
                "saved_vs_vanilla": {
                    "graperoot": vanilla_usage["total_tokens"] - graph_usage["total_tokens"],
                    "kdx": vanilla_usage["total_tokens"] - kdx_usage["total_tokens"],
                },
                "answers": {
                    "vanilla": vanilla_answer[:180],
                    "graperoot": graph_answer[:180],
                    "kdx": kdx_answer[:180],
                },
            }
            print(json.dumps(row, ensure_ascii=True))
            results.append(row)

    total_vanilla = sum(item["vanilla"]["total_tokens"] for item in results)
    total_graph = sum(item["graperoot"]["total_tokens"] for item in results)
    total_kdx = sum(item["kdx"]["total_tokens"] for item in results)
    summary = {
        "prompt_count": len(results),
        "repo_source": str(REPO_SOURCE),
        "model": MODEL,
        "totals": {
            "vanilla": total_vanilla,
            "graperoot": total_graph,
            "kdx": total_kdx,
        },
        "saved_tokens_vs_vanilla": {
            "graperoot": total_vanilla - total_graph,
            "kdx": total_vanilla - total_kdx,
        },
        "saved_percent_vs_vanilla": {
            "graperoot": round(((total_vanilla - total_graph) / total_vanilla * 100.0), 1) if total_vanilla else 0.0,
            "kdx": round(((total_vanilla - total_kdx) / total_vanilla * 100.0), 1) if total_vanilla else 0.0,
        },
    }
    print("SUMMARY " + json.dumps(summary, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
