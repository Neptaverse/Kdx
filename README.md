# KDX

<div align="center">

[![Stars](https://img.shields.io/github/stars/Neptaverse/Kdx?style=for-the-badge&logo=github&logoColor=white&labelColor=0d1117&color=58a6ff)](https://github.com/Neptaverse/Kdx/stargazers)
[![Forks](https://img.shields.io/github/forks/Neptaverse/Kdx?style=for-the-badge&logo=git&logoColor=white&labelColor=0d1117&color=8b949e)](https://github.com/Neptaverse/Kdx/network/members)
[![Issues](https://img.shields.io/github/issues/Neptaverse/Kdx?style=for-the-badge&logo=github&logoColor=white&labelColor=0d1117&color=f85149)](https://github.com/Neptaverse/Kdx/issues)
[![License](https://img.shields.io/github/license/Neptaverse/Kdx?style=for-the-badge&labelColor=0d1117&color=3fb950)](https://github.com/Neptaverse/Kdx/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=0d1117)](https://www.python.org)

</div>

KDX is a system-level wrapper around the Codex CLI that makes it genuinely smarter about your codebase.

It builds a deep, multi-language index of your repository — extracting symbols, signatures, decorators, docstrings, visibility, and a full cross-file dependency graph — then uses that knowledge to inject precisely targeted context into every session. Combined with Keiro-backed web search and token-aware budget governance, KDX keeps the model focused, grounded, and efficient.

KDX is not a fork of Codex. It launches the real `codex` binary, builds a temporary `CODEX_HOME`, attaches KDX-native MCP servers, and keeps just enough local state to make repo lookups and web-backed answers faster and more reliable.

Repository: `https://github.com/Neptaverse/Kdx.git`

<div align="center">

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Neptaverse/Kdx&type=Date)](https://star-history.com/#Neptaverse/Kdx&Date)

</div>

## What It Does

### Deep Codebase Indexing

- **12-language symbol extraction** — Python (full AST), JavaScript/TypeScript, Rust, Go, Java, Kotlin, C/C++, C#, Ruby, PHP
- **Signatures, decorators, bases, docstrings, visibility** — not just names, but the full shape of every symbol
- **Cross-file dependency graph** — `imported_by` lists and `import_score` centrality ranking so structurally important files surface first
- **Semantic role detection** — `entry`, `handler`, `middleware`, `model`, `test`, `config`, `docs` roles auto-classified per file

### System-Level Retrieval

- **Import-score centrality boosting** — files imported by many others automatically rank higher (capped at +12)
- **Decorator/docstring/signature matching** — queries about "route", "handler", etc. boost files with matching decorators
- **Visibility-aware filtering** — private symbols score 0.5×, internal 0.75×
- **Token-based budget governance** — 3,000 total tokens / 550 per file (not character-based; matches Codex/tiktoken heuristics)
- **Workspace tree injection** — compact directory tree + top-8 key files injected at session start for instant model orientation
- **Compact context format** — ~30% fewer header tokens per snippet vs verbose formats

### Smart Routing & Web Search

- Routes queries as `local`, `external`, or `hybrid` with intent analysis
- Uses Keiro for docs, release notes, research, and freshness-sensitive lookups via dedicated MCP server
- Disables Codex native web search; all web lookups stay on the Keiro path

### Bulletproof Auto-Updates

- **Stash-and-reset update strategy** — `git stash` + `git reset --hard` + `git stash pop` on every update
- Auto-checks and auto-applies updates on every `kdx` invocation (not just interactive startup)
- Cross-platform: Linux, macOS, Windows
- Disable with `KDX_NO_AUTO_UPDATE=1`

## Quick Start

Use the 2-line installer for your OS.

### Linux (2 lines)

```bash
curl -fsSL https://raw.githubusercontent.com/Neptaverse/Kdx/main/bin/install-linux.sh | bash
kdx
```

Manual fallback:

```bash
git clone https://github.com/Neptaverse/Kdx.git
cd Kdx
python3 bootstrap.py --setup-only
kdx
```

If `python3 -m venv` is missing on Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
```

### macOS (2 lines)

```bash
curl -fsSL https://raw.githubusercontent.com/Neptaverse/Kdx/main/bin/install-macos.sh | bash
kdx
```

Manual fallback:

```bash
git clone https://github.com/Neptaverse/Kdx.git
cd Kdx
python3 bootstrap.py --setup-only
kdx
```

If you hit toolchain errors:

```bash
xcode-select --install
```

If `python3` is prerelease (for example `3.12.0rc1`), use stable 3.11 and reset:

```bash
python3.11 bootstrap.py --reset --setup-only
```

If `kdx` is installed but not found, add the launcher bin dir printed by Python:

```bash
BIN_DIR="$(python3.11 -c 'import site, pathlib; print(pathlib.Path(site.getuserbase()) / "bin")')"
export PATH="$BIN_DIR:$PATH"
echo "export PATH=\"$BIN_DIR:\$PATH\"" >> ~/.zprofile
```

### Windows (PowerShell, 2 lines)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Neptaverse/Kdx/main/bin/install-windows.ps1 | iex"
kdx
```

Manual fallback:

```powershell
git clone https://github.com/Neptaverse/Kdx.git
cd Kdx
py -3.12 bootstrap.py --setup-only
kdx
```

If `py -3.12` is not available, use `py -3.11` or `py -3`.

The bootstrap step creates the local `.venv`, installs KDX, and installs a user-level `kdx` launcher. After setup, use `kdx` directly from any directory.

If you are inside Conda and install misbehaves, run `conda deactivate` first and retry.

If you already have a broken environment, reset it fully:

```bash
python3 bootstrap.py --reset --setup-only
```

Windows reset:

```powershell
py -3.12 bootstrap.py --reset --setup-only
```

`bootstrap.py` intentionally keeps the packaging toolchain below the current `pip 26` line because that release has caused editable-install failures in some environments.

If setup fails with a PyPI `ReadTimeoutError`, run the same setup command again. The bootstrap flow already uses longer timeout and retries.

## Common Commands

```bash
kdx                                     # interactive session
kdx "fix the auth retry path"           # task with preloaded context
kdx scan                                # rebuild repo index
kdx plan "where is the Keiro client?"   # show routing + retrieval plan
kdx search "latest FastMCP docs"        # Keiro web search
kdx tokens "explain the budget system"  # benchmark KDX vs vanilla Codex
kdx update                              # pull latest from GitHub
```

## How It Works

### Repo Index (v5)

KDX scans the current repository using language-specific parsers:

| Language | Extraction Method |
|----------|------------------|
| Python | Full AST — decorators, bases, docstrings, signatures, visibility, parent classes |
| JavaScript/TypeScript | Arrow functions, hooks, React components, default exports, enums |
| Rust | `pub(crate)`, macros, derives, async/unsafe markers |
| Go | Method receivers, interfaces, const/var blocks |
| Java/Kotlin | Classes, methods, interfaces, annotations |
| C/C++/C# | Classes, structs, functions, methods |
| Ruby/PHP | Classes, modules, methods, functions |

The index includes a **cross-file dependency graph**: every file tracks which other files import it (`imported_by`) and receives an `import_score` based on centrality (direct + 0.5× transitive importers).

### Retrieval Engine

For every query, KDX scores files using a multi-signal ranking:

| Signal | Weight | Description |
|--------|--------|-------------|
| Path hint exact match | +80 | `retrieval.py` matches `retrieval.py` |
| Path overlap | +6/term | Query terms in file path |
| Symbol name match | +4/term | Function/class names |
| Decorator match | +3/term | `@route`, `@handler`, etc. |
| Docstring match | +1.5/term | Documentation content |
| Signature match | +1/term | Function parameter names/types |
| Import score (centrality) | up to +12 | Files imported by many others |
| Semantic role | +3 to +8 | Entry, handler, middleware, model, source |
| Visibility | 0.5× to 1× | Private symbols deprioritized |

Budget governance operates in **tokens** (not characters) — 3,000 total / 550 per file, matching industry-standard `len(text) // 4` heuristics.

### Workspace Orientation

At session start, KDX injects into the bootstrap prompt:

1. **Workspace tree** — compact `tree` output (depth 2, noisy dirs filtered)
2. **Key files** — top 8 files ranked by import-score centrality with symbol counts and role
3. **Local context** — symbol-targeted or keyword-targeted excerpts from the highest-scoring files

This gives the model instant codebase orientation without burning tokens on `ls` or `find`.

### Web Search

For external or freshness-sensitive questions, KDX calls Keiro through its own MCP server. Search planning is intent-based: docs, release notes, error lookups, research, and general web queries each take optimized paths. Codex native web search is disabled in KDX sessions so web lookups stay on the Keiro path.

### Codex Runtime

KDX launches the real `codex` binary with:

- a temporary `CODEX_HOME`
- KDX MCP servers injected into `config.toml`
- your existing Codex auth and rules copied forward
- Codex launch overrides that keep native `web_search` disabled in KDX sessions
- a small set of session instructions tuned for evidence-first repo work

### Auto-Updates

KDX auto-updates on every invocation:

1. Checks GitHub for newer tags (cached, TTL-based)
2. If update available: `git stash` → `git reset --hard origin/main` → `git stash pop`
3. Works even when local files (`.venv`, `__pycache__`) exist in the install directory

```bash
kdx update            # manual update
kdx update --check    # check only, don't apply
kdx update --rollback v0.1.0  # pin to a specific version
```

| Environment Variable | Effect |
|---------------------|--------|
| `KDX_NO_AUTO_UPDATE=1` | Disable auto-updates |
| `KDX_NO_UPDATE_CHECK=1` | Disable update checks entirely |
| `KDX_UPDATE_TTL_SECONDS` | Cache duration for update checks |

## Keiro Setup

If you want web search and doc lookups, get a Keiro key from `https://www.keirolabs.cloud`.

KDX can read the Keiro API key from either:

- `~/.kdx/config.json`
- `KEIRO_API_KEY`
- `KDX_KEIRO_API_KEY`

The easiest setup is:

```bash
kdx /keiro keiro_your_api_key_here
```

The persisted config is stored outside the repo and is written with private file permissions.

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `KDX_MAX_TOTAL_TOKENS` | `3000` | Total token budget for retrieved context |
| `KDX_MAX_FILE_TOKENS` | `550` | Per-file token budget |
| `KDX_MAX_FILES` | `6` | Maximum files in context |
| `KDX_MAX_SNIPPETS` | `10` | Maximum snippets |
| `KDX_MAX_SEARCH_RESULTS` | `5` | Maximum Keiro search results |
| `KDX_MODEL` | `gpt-5.4` | Model to use with Codex |
| `KDX_AUTO_INIT` | `1` | Auto-initialize index on startup |

## Local State

KDX writes local runtime data to:

- `.kdx/` inside the repo
- `~/.kdx/config.json` for the persisted Keiro key

The repo-local `.kdx/` directory is intentionally ignored and should not be committed.

## Uninstall

### Linux and macOS

Remove the launcher, user-level config/cache, and repo-local runtime data:

```bash
rm -f "$(python3 -c 'import site, pathlib; print(pathlib.Path(site.getuserbase()) / "bin" / "kdx")')"
rm -rf ~/.kdx
rm -rf .kdx .venv
```

Then delete the cloned repository directory when you are done.

### Windows (PowerShell)

```powershell
$base = py -3 -c "import site; print(site.getuserbase())"
Remove-Item "$base\Scripts\kdx.cmd" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\.kdx" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item ".kdx",".venv" -Recurse -Force -ErrorAction SilentlyContinue
```

Then delete the cloned repository directory when you are done.

## Token Comparison

KDX includes a direct benchmark against vanilla Codex:

```bash
kdx tokens "where is the Keiro client implemented? reply with the path only."
kdx tokens --prompts-file bench/prompts_kdx_repo.txt --json
```

This uses real `codex exec --json` runs and reads `turn.completed.usage`, so the numbers come from actual model usage rather than local estimates.

## Development

```bash
python bootstrap.py --setup-only
python bootstrap.py --python -m unittest discover -s tests -v
python bootstrap.py --python -m compileall src/kdx
python bootstrap.py --python -m pip install build
python bootstrap.py --python -m build
```

## Project Layout

```text
src/kdx/
  cli.py              CLI entrypoint
  wrapper.py          Codex launch flow + workspace tree injection
  codex_home.py       temporary CODEX_HOME generation
  indexer.py          12-language deep symbol extraction + dependency graph
  retrieval.py        token-aware retrieval, scoring, impact analysis
  budget.py           token-based budget governance
  models.py           data models (SymbolRecord, FileRecord, ProjectIndex)
  search_service.py   Keiro search planning and evidence ranking
  mcp_code_server.py  repo MCP server (scan, retrieve, read)
  mcp_search_server.py web MCP server (Keiro endpoints)
  updates.py          auto-update mechanism (stash + reset)
  config.py           settings, env vars, persisted config
  token_compare.py    KDX vs vanilla Codex token benchmarking
```

## Status

KDX core is production-grade:

- **Index v5** — deep 12-language symbol extraction with cross-file dependency graph
- **Token-aware retrieval** — multi-signal scoring with centrality, decorators, docstrings, signatures, visibility
- **Workspace orientation** — tree + key files injected at session start
- **Bulletproof updates** — stash-and-reset across all platforms
- **65 tests passing** — full coverage of indexing, retrieval, budget, routing, updates, UI

## Release Readiness

- MIT licensed
- Cross-platform CI on Linux, macOS, and Windows
- Reproducible bootstrap flow for the global `kdx` launcher
- Package build validated through `python -m build`
- Repo-local runtime state stays out of source control
