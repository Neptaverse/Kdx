from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from kdx.config import KdxSettings

DEFAULT_PROJECT_DOC_FILENAME = "AGENTS.md"
LOCAL_PROJECT_DOC_FILENAME = "AGENTS.override.md"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _strip_table_by_header(config_text: str, header: str) -> str:
    output: list[str] = []
    skipping = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped == header:
            skipping = True
            continue
        if skipping and stripped.startswith("["):
            skipping = False
        if not skipping:
            output.append(line)
    return "\n".join(output).strip() + "\n"


def _strip_tables_by_prefix(config_text: str, prefix: str) -> str:
    output: list[str] = []
    skipping = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            skipping = True
            continue
        if skipping:
            if stripped.startswith("["):
                if stripped.startswith(prefix):
                    skipping = True
                    continue
                skipping = False
            else:
                continue
        output.append(line)
    return "\n".join(output).strip() + "\n"


def _render_mcp_tables(settings: KdxSettings) -> str:
    python_bin = sys.executable
    return "\n".join(
        [
            "[mcp_servers.kdx_repo]",
            f'command = "{python_bin}"',
            'args = ["-m", "kdx.mcp_code_server"]',
            "startup_timeout_sec = 20",
            "tool_timeout_sec = 30",
            "",
            "[mcp_servers.kdx_web]",
            f'command = "{python_bin}"',
            'args = ["-m", "kdx.mcp_search_server"]',
            "startup_timeout_sec = 20",
            "tool_timeout_sec = 45",
            "",
            f'[projects."{settings.repo_root}"]',
            'trust_level = "trusted"',
            "",
        ]
    )


@contextmanager
def prepared_codex_home(
    settings: KdxSettings,
    *,
    session_instructions: str = "",
) -> Iterator[Path]:
    runtime_root = settings.data_dir / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kdx-codex-home-", dir=runtime_root) as temp_dir:
        temp_home = Path(temp_dir)
        temp_home.mkdir(parents=True, exist_ok=True)
        for filename in ("auth.json", "models_cache.json", "version.json"):
            source = settings.base_codex_home / filename
            if source.exists():
                shutil.copy2(source, temp_home / filename)
        rules_dir = settings.base_codex_home / "rules"
        if rules_dir.exists():
            shutil.copytree(rules_dir, temp_home / "rules", dirs_exist_ok=True)
        base_config = _read_text(settings.base_codex_home / "config.toml")
        base_config = _strip_tables_by_prefix(base_config, "[mcp_servers.")
        base_config = _strip_table_by_header(base_config, f'[projects."{settings.repo_root}"]')
        merged = (base_config.rstrip() + "\n\n" if base_config.strip() else "") + _render_mcp_tables(settings)
        (temp_home / "config.toml").write_text(merged, encoding="utf-8")
        instructions = _merge_session_instructions(settings.base_codex_home, session_instructions)
        if instructions:
            (temp_home / LOCAL_PROJECT_DOC_FILENAME).write_text(instructions, encoding="utf-8")
        yield temp_home


def _merge_session_instructions(base_codex_home: Path, session_instructions: str) -> str:
    parts: list[str] = []
    for filename in (LOCAL_PROJECT_DOC_FILENAME, DEFAULT_PROJECT_DOC_FILENAME):
        text = _read_text(base_codex_home / filename).strip()
        if text and text not in parts:
            parts.append(text)
    session_text = session_instructions.strip()
    if session_text:
        parts.append(session_text)
    return "\n\n---\n\n".join(parts).strip()
