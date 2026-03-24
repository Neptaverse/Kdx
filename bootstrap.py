#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
SCRIPTS_DIR = VENV_DIR / ("Scripts" if os.name == "nt" else "bin")
VENV_PYTHON = SCRIPTS_DIR / ("python.exe" if os.name == "nt" else "python")
TOOLCHAIN_CONSTRAINTS = ["pip<26", "setuptools<81", "wheel>=0.43,<0.46"]
STATE_FILE = VENV_DIR / ".kdx-bootstrap.json"


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PIP_DEFAULT_TIMEOUT", "120")
    env.setdefault("PIP_RETRIES", "5")
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    return env


def run(command: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(ROOT),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="Cross-platform KDX bootstrap and local runner",
    )
    parser.add_argument("--setup-only", action="store_true", help="create/update .venv and install KDX, then exit")
    parser.add_argument("--reset", action="store_true", help="delete .venv before reinstalling")
    parser.add_argument("--python", action="store_true", help="run the venv Python directly instead of launching KDX")
    parser.add_argument("kdx_args", nargs=argparse.REMAINDER, help="arguments to pass through to KDX")
    args = parser.parse_args(argv)

    python_bin = ensure_environment(reset=args.reset)
    if args.setup_only:
        print(f"KDX environment ready: {VENV_DIR}")
        print(f"Run with: {sys.executable} bootstrap.py")
        return 0

    kdx_args = list(args.kdx_args)
    if kdx_args and kdx_args[0] == "--":
        kdx_args = kdx_args[1:]
    command = [str(python_bin), *kdx_args] if args.python else [str(python_bin), "-m", "kdx.cli", *kdx_args]
    process = run(command, check=False)
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


if __name__ == "__main__":
    raise SystemExit(main())
