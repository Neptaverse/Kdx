from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from kdx.budget import BudgetConfig


@dataclass(slots=True)
class KdxSettings:
    repo_root: Path
    data_dir: Path
    index_path: Path
    history_path: Path
    search_cache_path: Path
    global_config_path: Path
    keiro_api_key: str
    keiro_base_url: str
    codex_binary: str
    base_codex_home: Path
    model: str
    auto_init: bool
    budget: BudgetConfig

    @property
    def workspace_id(self) -> str:
        digest = hashlib.sha256(str(self.repo_root).encode("utf-8")).hexdigest()[:12]
        return f"kdx-{digest}"


def detect_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def default_global_config_path() -> Path:
    configured = os.environ.get("KDX_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()
    return (Path.home() / ".kdx" / "config.json").expanduser()


def load_persisted_config(config_path: Path | None = None) -> dict[str, str]:
    path = config_path or default_global_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def save_persisted_config(payload: dict[str, str], config_path: Path | None = None) -> Path:
    path = config_path or default_global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _tighten_permissions(path.parent, 0o700)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(serialized)
        handle.write("\n")
        temp_path = Path(handle.name)
    _tighten_permissions(temp_path, 0o600)
    temp_path.replace(path)
    _tighten_permissions(path, 0o600)
    return path


def set_keiro_api_key(api_key: str, config_path: Path | None = None) -> Path:
    current = load_persisted_config(config_path)
    current["keiro_api_key"] = api_key.strip()
    return save_persisted_config(current, config_path)


def clear_keiro_api_key(config_path: Path | None = None) -> Path:
    current = load_persisted_config(config_path)
    current.pop("keiro_api_key", None)
    return save_persisted_config(current, config_path)


def load_settings(repo_root: Path | None = None) -> KdxSettings:
    root = detect_repo_root(repo_root)
    data_dir = root / ".kdx"
    data_dir.mkdir(parents=True, exist_ok=True)
    global_config_path = default_global_config_path()
    persisted = load_persisted_config(global_config_path)
    keiro_key = os.environ.get("KDX_KEIRO_API_KEY") or os.environ.get("KEIRO_API_KEY") or persisted.get("keiro_api_key", "")
    return KdxSettings(
        repo_root=root,
        data_dir=data_dir,
        index_path=data_dir / "index.json",
        history_path=data_dir / "history.jsonl",
        search_cache_path=data_dir / "keiro-cache.json",
        global_config_path=global_config_path,
        keiro_api_key=keiro_key.strip(),
        keiro_base_url=os.environ.get("KDX_KEIRO_BASE_URL", "https://kierolabs.space/api").rstrip("/"),
        codex_binary=os.environ.get("KDX_CODEX_BINARY", "codex"),
        base_codex_home=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser(),
        model=os.environ.get("KDX_MODEL", "gpt-5.4"),
        auto_init=os.environ.get("KDX_AUTO_INIT", "1").strip().lower() not in {"0", "false", "no", "off"},
        budget=BudgetConfig(
            max_total_tokens=int(os.environ.get("KDX_MAX_TOTAL_TOKENS", "3000")),
            max_file_tokens=int(os.environ.get("KDX_MAX_FILE_TOKENS", "550")),
            max_files=int(os.environ.get("KDX_MAX_FILES", "6")),
            max_snippets=int(os.environ.get("KDX_MAX_SNIPPETS", "10")),
            max_search_results=int(os.environ.get("KDX_MAX_SEARCH_RESULTS", "5")),
        ),
    )


def _tighten_permissions(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        return
