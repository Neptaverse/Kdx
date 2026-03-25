# KDX

KDX is a thin wrapper around the Codex CLI.

The goal is simple: keep Codex focused on the right parts of the repo, give it a clean way to reach fresh information through Keiro, and avoid wasting context on broad file reads when a smaller, better-targeted prompt will do.

KDX is not a fork of Codex. It launches the real `codex` binary, builds a temporary `CODEX_HOME`, attaches KDX-native MCP servers, and keeps just enough local state to make repo lookups and web-backed answers faster and more reliable.

Repository: `https://github.com/Neptaverse/Kdx.git`

## What It Does

- Builds an incremental repo index in `.kdx/index.json`
- Prefers source files and symbol-level matches over noisy broad reads
- Routes questions as `local`, `external`, or `hybrid`
- Uses Keiro for docs, release notes, research, and other freshness-sensitive lookups
- Starts Codex with KDX repo and web MCP tools already attached
- Includes a `kdx tokens` command to compare KDX against vanilla Codex on real prompts
- Checks GitHub for newer tagged releases and shows a cached startup notice when one is available

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
kdx
kdx "fix the auth retry path and check the latest SDK docs"
kdx scan
kdx plan "where is the Keiro client implemented?"
kdx search "latest FastMCP docs"
kdx tokens "where is the Keiro client implemented? reply with the path only."
kdx update
```

## What’s Different

Compared with plain Codex CLI, KDX adds a few opinionated pieces:

- a repo-local index that biases the model toward source files and symbol matches
- a separate web path for freshness-sensitive work through Keiro
- explicit local/external/hybrid routing instead of one generic prompt shape
- token benchmarking against vanilla Codex on the same prompts
- GitHub-backed update checks for the KDX wrapper itself
- a cross-platform bootstrap that installs a real user-level `kdx` command

## How It Works

### Repo index

KDX scans the current repository, extracts symbols and imports, and stores a compact index under `.kdx/`. That index is refreshed automatically when files change.

### Retrieval

For local questions, KDX ranks files using:

- path hints
- identifier hints
- symbol overlap
- imports
- file role

Source files are preferred by default. Tests, docs, config, and bench files are down-ranked unless the query clearly asks for them.

### Web search

For external or freshness-sensitive questions, KDX calls Keiro through its own MCP server. Search planning is intent-based: docs, release notes, error lookups, research, and general web queries do not all take the same path.

### Codex runtime

KDX launches the real `codex` binary with:

- a temporary `CODEX_HOME`
- KDX MCP servers injected into `config.toml`
- your existing Codex auth and rules copied forward
- a small set of session instructions tuned for evidence-first repo work

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

## Updates

KDX can check GitHub for newer versions of the project and update the current clone:

```bash
kdx update
kdx update --check
kdx update --check-now
```

`kdx update` applies the update by default.

Interactive startup also performs a cached update check and shows a short notice when a newer version is available.

The check is intentionally lightweight:

- GitHub-backed
- cached locally in `~/.kdx/update-check.json`
- disabled with `KDX_NO_UPDATE_CHECK=1`

Rollback stays explicit:

```bash
kdx update --rollback v0.1.0
```

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
  wrapper.py          Codex launch flow
  codex_home.py       temporary CODEX_HOME generation
  indexer.py          repo scan and symbol extraction
  retrieval.py        local retrieval and budgeting
  search_service.py   Keiro search planning and evidence ranking
  mcp_code_server.py  repo MCP server
  mcp_search_server.py web MCP server
  token_compare.py    KDX vs vanilla Codex token benchmarking
```

## Status

KDX is early, but the core loop is working:

- repo indexing
- local retrieval
- Keiro-backed web search
- Codex launch integration
- token benchmarking

What is still deliberately simple:

- language parsing outside Python is mostly heuristic
- verification loops are not fully built out yet
- retrieval tuning is still benchmark-driven and evolving

## Release Readiness

- MIT licensed
- Cross-platform CI on Linux, macOS, and Windows
- Reproducible bootstrap flow for the global `kdx` launcher
- Package build validated through `python -m build`
- Repo-local runtime state stays out of source control

KDX still needs real-world benchmark tuning and broader parser coverage, but the repo is now structured for public releases and repeatable validation.
