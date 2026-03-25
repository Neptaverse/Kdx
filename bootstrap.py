#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
SCRIPTS_DIR = VENV_DIR / ("Scripts" if os.name == "nt" else "bin")
VENV_PYTHON = SCRIPTS_DIR / ("python.exe" if os.name == "nt" else "python")
TOOLCHAIN_CONSTRAINTS = ["pip<26", "setuptools>=77,<81", "wheel>=0.43,<0.46"]
STATE_FILE = VENV_DIR / ".kdx-bootstrap.json"
_SKIP_GLOBAL_INSTALL = {"1", "true", "yes", "on"}


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PIP_DEFAULT_TIMEOUT", "120")
    env.setdefault("PIP_RETRIES", "5")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    return env


def _python_runtime_guard_error(version_info: Any | None = None) -> str:
    info = version_info or sys.version_info
    release_level = str(getattr(info, "releaselevel", "final"))
    if release_level == "final":
        return ""
    major = int(getattr(info, "major", 0))
    minor = int(getattr(info, "minor", 0))
    micro = int(getattr(info, "micro", 0))
    serial = int(getattr(info, "serial", 0))
    suffix_map = {"alpha": "a", "beta": "b", "candidate": "rc"}
    suffix = suffix_map.get(release_level, release_level)
    detected = f"{major}.{minor}.{micro}{suffix}{serial if serial else ''}"
    return (
        "KDX bootstrap requires a stable Python release. "
        f"Detected prerelease interpreter: {detected}.\n"
        "Use Python 3.11 or 3.12 final, then rerun bootstrap."
    )


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    cwd: Path | None = ROOT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=None if cwd is None else str(cwd),
        env=env,
        check=check,
        text=True,
    )


def ensure_environment(*, reset: bool = False) -> Path:
    if reset and VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    created = False
    if not VENV_PYTHON.exists():
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
        created = True
    env = build_env()
    if created or _needs_install():
        run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", *TOOLCHAIN_CONSTRAINTS], env=env)
        run([str(VENV_PYTHON), "-m", "pip", "install", "-e", str(ROOT)], env=env)
        _write_state()
    return VENV_PYTHON


def default_global_bin_dir() -> Path:
    return Path(site.getuserbase()) / ("Scripts" if os.name == "nt" else "bin")


def global_launcher_path(bin_dir: Path | None = None, *, platform_name: str | None = None) -> Path:
    target_dir = bin_dir or default_global_bin_dir()
    platform_name = os.name if platform_name is None else platform_name
    return target_dir / ("kdx.cmd" if platform_name == "nt" else "kdx")


def install_global_launcher(
    *,
    python_executable: Path | None = None,
    bootstrap_path: Path | None = None,
    bin_dir: Path | None = None,
) -> dict[str, str | bool]:
    target_dir = (bin_dir or default_global_bin_dir()).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    launcher_path = global_launcher_path(target_dir)
    python_path = (python_executable or Path(sys.executable)).expanduser().resolve()
    bootstrap = (bootstrap_path or (ROOT / "bootstrap.py")).expanduser().resolve()
    content = _render_launcher_content(python_path, bootstrap)
    previous = launcher_path.read_text(encoding="utf-8") if launcher_path.exists() else ""
    launcher_path.write_text(content, encoding="utf-8", newline="\r\n" if os.name == "nt" else "\n")
    if os.name != "nt":
        launcher_path.chmod(0o755)
    on_path = _path_contains(target_dir)
    if previous == content:
        status = "unchanged"
    elif previous:
        status = "updated"
    else:
        status = "created"
    return {
        "status": status,
        "launcher_path": str(launcher_path),
        "bin_dir": str(target_dir),
        "on_path": on_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="Cross-platform KDX bootstrap and launcher installer",
    )
    parser.add_argument("--setup-only", action="store_true", help="create/update .venv, install KDX, and install the global kdx command")
    parser.add_argument("--reset", action="store_true", help="delete .venv before reinstalling")
    parser.add_argument("--python", action="store_true", help="run the venv Python directly instead of launching KDX")
    args, passthrough = parser.parse_known_args(argv)

    runtime_error = _python_runtime_guard_error()
    if runtime_error:
        print(runtime_error, file=sys.stderr)
        return 2

    python_bin = ensure_environment(reset=args.reset)
    launcher_info = None
    if os.environ.get("KDX_SKIP_GLOBAL_INSTALL", "").strip().lower() not in _SKIP_GLOBAL_INSTALL:
        launcher_info = install_global_launcher()

    if args.setup_only:
        print(f"KDX environment ready: {VENV_DIR}")
        if launcher_info is not None:
            _print_launcher_notice(launcher_info)
        print("Run with: kdx")
        return 0

    if launcher_info is not None and launcher_info["status"] in {"created", "updated"}:
        _print_launcher_notice(launcher_info)

    kdx_args = list(passthrough)
    if kdx_args and kdx_args[0] == "--":
        kdx_args = kdx_args[1:]
    command = [str(python_bin), *kdx_args] if args.python else [str(python_bin), "-m", "kdx.cli", *kdx_args]
    process = run(command, check=False, cwd=Path.cwd())
    return int(process.returncode)


def _needs_install() -> bool:
    if not STATE_FILE.exists():
        return True
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        return True
    try:
        stat = pyproject.stat()
    except OSError:
        return True
    return (
        payload.get("pyproject_mtime_ns") != stat.st_mtime_ns
        or payload.get("pyproject_size") != stat.st_size
    )


def _write_state() -> None:
    pyproject = ROOT / "pyproject.toml"
    stat = pyproject.stat()
    payload = {
        "pyproject_mtime_ns": stat.st_mtime_ns,
        "pyproject_size": stat.st_size,
    }
    STATE_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_launcher_content(
    python_executable: Path,
    bootstrap_path: Path,
    *,
    platform_name: str | None = None,
) -> str:
    platform_name = os.name if platform_name is None else platform_name
    python_text = str(python_executable)
    bootstrap_text = str(bootstrap_path)
    if platform_name == "nt":
        return f'@echo off\n"{python_text}" "{bootstrap_text}" -- %*\n'
    return f'#!/usr/bin/env sh\nexec "{python_text}" "{bootstrap_text}" -- "$@"\n'


def _path_contains(directory: Path, path_value: str | None = None, *, platform_name: str | None = None) -> bool:
    platform_name = os.name if platform_name is None else platform_name
    raw_path = os.environ.get("PATH", "") if path_value is None else path_value
    candidate = str(directory)
    if platform_name == "nt":
        candidate = candidate.lower()
    separator = ";" if platform_name == "nt" else os.pathsep
    for entry in raw_path.split(separator):
        normalized = entry.strip().strip('"')
        if not normalized:
            continue
        if platform_name == "nt":
            normalized = normalized.lower()
        if normalized == candidate:
            return True
    return False


def _print_launcher_notice(launcher_info: dict[str, str | bool]) -> None:
    print(f"Installed global kdx launcher: {launcher_info['launcher_path']}")
    if not launcher_info["on_path"]:
        print(f"Add this directory to PATH: {launcher_info['bin_dir']}")


if __name__ == "__main__":
    raise SystemExit(main())
