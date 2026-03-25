from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from kdx import __version__
from kdx.config import KdxSettings, load_settings

REPOSITORY_URL = "https://github.com/Neptaverse/Kdx"
GITHUB_RELEASES_API = "https://api.github.com/repos/Neptaverse/Kdx/releases/latest"
GITHUB_TAGS_API = "https://api.github.com/repos/Neptaverse/Kdx/tags?per_page=1"
GITHUB_REPO_API = "https://api.github.com/repos/Neptaverse/Kdx"
GITHUB_COMMIT_API_TEMPLATE = "https://api.github.com/repos/Neptaverse/Kdx/commits/{branch}"
UPDATE_CACHE_FILENAME = "update-check.json"
DEFAULT_TIMEOUT_SECONDS = 2
DEFAULT_TTL_SECONDS = 43_200
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}
_VERSION_RE = re.compile(r"\d+")
_SAFE_GENERATED_PREFIXES = (".kdx/", ".venv/", "src/kdx.egg-info/")
_SAFE_GENERATED_MARKERS = ("/__pycache__/", "__pycache__/")
_SAFE_GENERATED_SUFFIXES = (".pyc",)


def kdx_install_root() -> Path:
    return Path(__file__).resolve().parents[2]


def update_settings(base: KdxSettings | None = None) -> KdxSettings:
    root = kdx_install_root()
    if base is not None and base.repo_root == root:
        return base
    return load_settings(root)


def update_cache_path(settings: KdxSettings) -> Path:
    return settings.global_config_path.parent / UPDATE_CACHE_FILENAME


def should_check_for_updates(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("KDX_NO_UPDATE_CHECK", "").strip().lower() not in _TRUTHY


def should_auto_apply_updates(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    if env.get("KDX_NO_AUTO_UPDATE", "").strip().lower() in _TRUTHY:
        return False
    value = env.get("KDX_AUTO_UPDATE", "1").strip().lower()
    return value not in _FALSY


def check_for_updates(
    settings: KdxSettings,
    *,
    force: bool = False,
    environ: dict[str, str] | None = None,
    fetcher: Callable[[], dict[str, str]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    cache_file = update_cache_path(settings)
    ttl_seconds = _ttl_seconds(environ)
    repo_commit = current_commit(settings)
    cached = _load_cache(cache_file)
    if not force and _is_cache_fresh(cached, current_time, ttl_seconds):
        merged = dict(cached)
        merged["current_commit"] = repo_commit
        return _finalize_status(merged, current_version=__version__, cached=True)

    try:
        fetched = (fetcher or _fetch_latest_release)()
    except Exception as exc:
        if cached:
            stale = dict(cached)
            stale["error"] = str(exc)
            stale["current_commit"] = repo_commit
            return _finalize_status(stale, current_version=__version__, cached=True)
        return {
            "ok": False,
            "current_version": __version__,
            "latest_version": "",
            "current_commit": repo_commit,
            "latest_commit": "",
            "update_available": False,
            "cached": False,
            "checked_at": current_time.isoformat(),
            "release_url": "",
            "error": str(exc),
        }

    payload = {
        "checked_at": current_time.isoformat(),
        "latest_version": fetched.get("latest_version", ""),
        "latest_commit": fetched.get("latest_commit", ""),
        "release_url": fetched.get("release_url", ""),
        "source": fetched.get("source", ""),
        "current_commit": repo_commit,
    }
    _save_cache(cache_file, payload)
    return _finalize_status(payload, current_version=__version__, cached=False)


def format_update_notice(status: dict[str, Any]) -> str:
    if not status.get("update_available"):
        return ""
    current = status.get("current_version", __version__)
    latest = status.get("latest_version", "")
    if latest:
        return f"UPDATE: {latest} available (current {current}) | run `kdx update`"
    if status.get("latest_commit"):
        return "UPDATE: new update available | run `kdx update`"
    return ""


def update_actions(status: dict[str, Any]) -> dict[str, str]:
    latest = str(status.get("latest_version") or "").strip()
    current = str(status.get("current_version") or __version__).strip()
    return {
        "update": "git pull --ff-only && python bootstrap.py --setup-only",
        "rollback": f"git fetch --tags && git checkout v{current.lstrip('v')} && python bootstrap.py --setup-only",
        "install_latest_tag": f"git fetch --tags && git checkout v{latest.lstrip('v')} && python bootstrap.py --setup-only" if latest else "",
    }


def apply_update(settings: KdxSettings, *, rollback_ref: str = "") -> dict[str, Any]:
    if not (settings.repo_root / ".git").exists():
        raise RuntimeError("auto update requires a git clone")
    safe_dirty, unsafe_dirty = _partition_dirty_paths(_dirty_paths(settings))
    if safe_dirty:
        _cleanup_safe_generated_paths(settings, safe_dirty)
        safe_dirty, unsafe_dirty = _partition_dirty_paths(_dirty_paths(settings))
    if unsafe_dirty:
        preview = ", ".join(unsafe_dirty[:4])
        if len(unsafe_dirty) > 4:
            preview += ", ..."
        raise RuntimeError(f"refusing to update because the install repo has local changes: {preview}")
    _run(settings, ["git", "-C", str(settings.repo_root), "fetch", "--tags", "--prune"])
    if rollback_ref.strip():
        _run(settings, ["git", "-C", str(settings.repo_root), "checkout", rollback_ref.strip()])
    else:
        _run(settings, ["git", "-C", str(settings.repo_root), "pull", "--ff-only"])
    _run(settings, [sys.executable, str(settings.repo_root / "bootstrap.py"), "--setup-only"])
    return {
        "repo_root": str(settings.repo_root),
        "rollback_ref": rollback_ref.strip(),
        "current_commit": current_commit(settings),
    }


def _ttl_seconds(environ: dict[str, str] | None) -> int:
    env = os.environ if environ is None else environ
    raw = env.get("KDX_UPDATE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)).strip()
    try:
        return max(300, int(raw))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_cache_fresh(payload: dict[str, Any], current_time: datetime, ttl_seconds: int) -> bool:
    checked_at = _parse_timestamp(str(payload.get("checked_at", "")))
    if checked_at is None:
        return False
    return checked_at + timedelta(seconds=ttl_seconds) > current_time


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _finalize_status(payload: dict[str, Any], *, current_version: str, cached: bool) -> dict[str, Any]:
    latest = str(payload.get("latest_version", "")).strip()
    release_url = str(payload.get("release_url", "")).strip()
    current_commit = str(payload.get("current_commit", "")).strip()
    latest_commit = str(payload.get("latest_commit", "")).strip()
    update_available = bool(latest and _compare_versions(latest, current_version) > 0)
    if not update_available and current_commit and latest_commit:
        update_available = current_commit != latest_commit
    return {
        "ok": True,
        "current_version": current_version,
        "latest_version": latest,
        "current_commit": current_commit,
        "latest_commit": latest_commit,
        "update_available": update_available,
        "cached": cached,
        "checked_at": str(payload.get("checked_at", "")),
        "release_url": release_url,
        "source": str(payload.get("source", "")),
        "error": str(payload.get("error", "")),
    }


def _fetch_latest_release() -> dict[str, str]:
    try:
        payload = _get_json(GITHUB_RELEASES_API)
        tag = normalize_version_tag(str(payload.get("tag_name", "")))
        if tag:
            return {
                "latest_version": tag,
                "release_url": str(payload.get("html_url") or f"{REPOSITORY_URL}/releases/tag/{tag}"),
                "source": "release",
            }
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(f"GitHub release check failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub release check failed: {exc.reason}") from exc
    payload = _get_json(GITHUB_TAGS_API)
    if isinstance(payload, list) and payload:
        first = payload[0] if isinstance(payload[0], dict) else {}
        tag = normalize_version_tag(str(first.get("name", "")))
        if tag:
            return {
                "latest_version": tag,
                "release_url": f"{REPOSITORY_URL}/tree/{tag}",
                "source": "tag",
            }
    repo_payload = _get_json(GITHUB_REPO_API)
    if not isinstance(repo_payload, dict):
        raise RuntimeError("GitHub update check returned an invalid repository payload")
    default_branch = str(repo_payload.get("default_branch", "")).strip() or "main"
    commit_payload = _get_json(GITHUB_COMMIT_API_TEMPLATE.format(branch=default_branch))
    if not isinstance(commit_payload, dict):
        raise RuntimeError("GitHub update check returned an invalid commit payload")
    latest_commit = str(commit_payload.get("sha", "")).strip()
    release_url = str(commit_payload.get("html_url") or f"{REPOSITORY_URL}/commits/{default_branch}")
    if not latest_commit:
        raise RuntimeError("GitHub update check returned no tags or commit SHA")
    return {
        "latest_version": "",
        "latest_commit": latest_commit,
        "release_url": release_url,
        "source": "commit",
    }


def _get_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"KDX/{__version__}",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        text = response.read().decode("utf-8", errors="ignore")
    return json.loads(text)


def normalize_version_tag(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith("refs/tags/"):
        raw = raw[len("refs/tags/") :]
    if raw.startswith("v"):
        raw = raw[1:]
    return raw


def _compare_versions(left: str, right: str) -> int:
    left_key = _version_key(normalize_version_tag(left))
    right_key = _version_key(normalize_version_tag(right))
    if left_key > right_key:
        return 1
    if left_key < right_key:
        return -1
    return 0


def _version_key(value: str) -> tuple[int, ...]:
    parts = [int(piece) for piece in _VERSION_RE.findall(value)]
    return tuple(parts or [0])


def current_commit(settings: KdxSettings) -> str:
    if not (settings.repo_root / ".git").exists():
        return ""
    result = subprocess.run(
        ["git", "-C", str(settings.repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _dirty_paths(settings: KdxSettings) -> list[str]:
    output = _git_output(settings, ["status", "--porcelain", "--untracked-files=normal"])
    paths: list[str] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1].strip()
        normalized = raw_path.replace("\\", "/")
        if normalized:
            paths.append(normalized)
    return paths


def _partition_dirty_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    safe: list[str] = []
    unsafe: list[str] = []
    for path in paths:
        if _is_safe_generated_path(path):
            safe.append(path)
        else:
            unsafe.append(path)
    return safe, unsafe


def _is_safe_generated_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith(_SAFE_GENERATED_PREFIXES):
        return True
    if any(marker in normalized for marker in _SAFE_GENERATED_MARKERS):
        return True
    return normalized.endswith(_SAFE_GENERATED_SUFFIXES)


def _cleanup_safe_generated_paths(settings: KdxSettings, paths: list[str]) -> None:
    for path in sorted(set(paths)):
        _restore_or_remove_path(settings, path)


def _restore_or_remove_path(settings: KdxSettings, path: str) -> None:
    target = (settings.repo_root / path).resolve()
    try:
        target.relative_to(settings.repo_root.resolve())
    except ValueError:
        return
    if not target.exists():
        return
    tracked = _git_path_is_tracked(settings, path)
    if tracked:
        _run(settings, ["git", "-C", str(settings.repo_root), "restore", "--worktree", "--staged", "--", path])
        return
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        try:
            target.unlink()
        except OSError:
            return


def _git_path_is_tracked(settings: KdxSettings, path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(settings.repo_root), "ls-files", "--error-unmatch", "--", path],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _git_output(settings: KdxSettings, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(settings.repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def _run(settings: KdxSettings, command: list[str]) -> None:
    result = subprocess.run(
        command,
        cwd=str(settings.repo_root),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}")
