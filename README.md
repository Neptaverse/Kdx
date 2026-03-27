# KDX

<div align="center">

[![Stars](https://img.shields.io/github/stars/Neptaverse/Kdx?style=for-the-badge&logo=github&logoColor=white&labelColor=0d1117&color=58a6ff)](https://github.com/Neptaverse/Kdx/stargazers)
[![Forks](https://img.shields.io/github/forks/Neptaverse/Kdx?style=for-the-badge&logo=git&logoColor=white&labelColor=0d1117&color=8b949e)](https://github.com/Neptaverse/Kdx/network/members)
[![Issues](https://img.shields.io/github/issues/Neptaverse/Kdx?style=for-the-badge&logo=github&logoColor=white&labelColor=0d1117&color=f85149)](https://github.com/Neptaverse/Kdx/issues)
[![License](https://img.shields.io/github/license/Neptaverse/Kdx?style=for-the-badge&labelColor=0d1117&color=3fb950)](https://github.com/Neptaverse/Kdx/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=0d1117)](https://www.python.org)

</div>

kdx wraps the codex cli and makes it actually understand your codebase.

it builds a full multi-language index of your repo — symbols, signatures, decorators, docstrings, cross-file dependency graphs — and injects exactly the right context into every session. web search goes through keiro. budget governance is token-aware. the model stays focused because it gets precisely what it needs and nothing else.

kdx is not a fork. it launches the real `codex` binary, builds a temp `CODEX_HOME`, attaches its own MCP servers, and keeps minimal local state for fast repo lookups and web-backed answers.

repo: `https://github.com/Neptaverse/Kdx.git`

<div align="center">

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Neptaverse/Kdx&type=Date)](https://star-history.com/#Neptaverse/Kdx&Date)

</div>

## what it does

**indexing** — 12-language symbol extraction (python full AST, js/ts, rust, go, java, kotlin, c/c++, c#, ruby, php). grabs signatures, decorators, bases, docstrings, visibility. builds a cross-file dependency graph with `imported_by` lists and `import_score` centrality. auto-classifies file roles (entry, handler, middleware, model, test, config, docs).

**retrieval** — multi-signal scoring: path hints, symbol names, decorator/docstring/signature matching, import-score centrality boosting (capped at +12), visibility-aware filtering. token-based budget governance (3k total / 550 per file). workspace tree + top-8 key files injected at session start so the model knows the codebase before it does anything.

**web search** — routes queries as local/external/hybrid with intent analysis. uses keiro for docs, release notes, research, error lookups via a dedicated MCP server. disables codex native web search so everything goes through keiro.

**auto-updates** — stash-and-reset strategy on every invocation. works across linux, macos, windows. disable with `KDX_NO_AUTO_UPDATE=1`.

## install

### linux

```bash
curl -fsSL https://raw.githubusercontent.com/Neptaverse/Kdx/main/bin/install-linux.sh | bash
kdx
```

### macos

```bash
curl -fsSL https://raw.githubusercontent.com/Neptaverse/Kdx/main/bin/install-macos.sh | bash
kdx
```

if you hit toolchain errors: `xcode-select --install`

if `python3` is a prerelease build, use stable 3.11:

```bash
python3.11 bootstrap.py --reset --setup-only
```

### windows (powershell)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Neptaverse/Kdx/main/bin/install-windows.ps1 | iex"
kdx
```

### manual install (any os)

```bash
git clone https://github.com/Neptaverse/Kdx.git
cd Kdx
python3 bootstrap.py --setup-only
kdx
```

if `python3 -m venv` is missing on debian/ubuntu: `sudo apt-get install -y python3-venv`

if `kdx` isn't found after install, add the bin dir to your PATH:

```bash
BIN_DIR="$(python3 -c 'import site, pathlib; print(pathlib.Path(site.getuserbase()) / "bin")')"
export PATH="$BIN_DIR:$PATH"
```

broken environment? nuke it: `python3 bootstrap.py --reset --setup-only`

if setup fails with `ReadTimeoutError`, just run it again. bootstrap already uses longer timeouts and retries.

conda users: `conda deactivate` first.

## usage

```bash
kdx                                     # interactive session
kdx "fix the auth retry path"           # task with preloaded context
kdx scan                                # rebuild repo index
kdx plan "where is the Keiro client?"   # show routing + retrieval plan
kdx search "latest FastMCP docs"        # keiro web search
kdx tokens "explain the budget system"  # benchmark kdx vs vanilla codex
kdx update                              # pull latest from github
```

## how it works

### indexing (v5)

scans the repo using language-specific parsers:

| language | what it extracts |
|----------|-----------------|
| python | full AST — decorators, bases, docstrings, signatures, visibility, parent classes |
| js/ts | arrow functions, hooks, react components, default exports, enums |
| rust | `pub(crate)`, macros, derives, async/unsafe markers |
| go | method receivers, interfaces, const/var blocks |
| java/kotlin | classes, methods, interfaces, annotations |
| c/c++/c# | classes, structs, functions, methods |
| ruby/php | classes, modules, methods, functions |

every file gets a cross-file dependency graph — `imported_by` lists and an `import_score` based on centrality (direct + 0.5× transitive importers).

### retrieval

per query, files get scored across multiple signals:

| signal | weight | what it does |
|--------|--------|-------------|
| path hint exact match | +80 | `retrieval.py` matches `retrieval.py` |
| path overlap | +6/term | query terms in file path |
| symbol name match | +4/term | function/class names |
| decorator match | +3/term | `@route`, `@handler`, etc. |
| docstring match | +1.5/term | docs content |
| signature match | +1/term | param names/types |
| import score | up to +12 | structural centrality |
| semantic role | +3 to +8 | entry, handler, middleware, model |
| visibility | 0.5× to 1× | private symbols deprioritized |

budget is in tokens, not characters — 3,000 total / 550 per file, using `len(text) // 4` heuristic.

### workspace orientation

at session start, the bootstrap prompt gets:

1. compact directory tree (depth 2, noise filtered)
2. top 8 files by import-score centrality with symbol counts and role
3. targeted excerpts from the highest-scoring files

model gets instant codebase orientation without burning tokens on `ls` or `find`.

### web search

external/freshness-sensitive questions go through keiro via a dedicated MCP server. search planning is intent-based — docs, release notes, error lookups, research, and general web queries each take optimized paths. codex native web search stays disabled in kdx sessions.

### codex runtime

kdx launches the real `codex` binary with:

- a temp `CODEX_HOME`
- kdx MCP servers injected into `config.toml`
- your existing codex auth and rules copied in
- native `web_search` disabled
- session instructions tuned for evidence-first repo work

### auto-updates

every invocation:

1. checks github for newer tags (cached, TTL-based)
2. if update available: `git stash` → `git reset --hard origin/main` → `git stash pop`
3. works even when local files (`.venv`, `__pycache__`) exist in the install dir

```bash
kdx update            # manual update
kdx update --check    # check only
kdx update --rollback v0.1.0  # pin to a version
```

| env var | effect |
|---------|--------|
| `KDX_NO_AUTO_UPDATE=1` | disable auto-updates |
| `KDX_NO_UPDATE_CHECK=1` | disable update checks entirely |
| `KDX_UPDATE_TTL_SECONDS` | cache duration for update checks |

## keiro setup

get a key from `https://www.keirolabs.cloud`.

kdx reads the keiro API key from:
- `~/.kdx/config.json`
- `KEIRO_API_KEY`
- `KDX_KEIRO_API_KEY`

easiest setup:

```bash
kdx /keiro keiro_your_api_key_here
```

config is stored outside the repo with private file permissions.

## configuration

| env var | default | description |
|---------|---------|-------------|
| `KDX_MAX_TOTAL_TOKENS` | `3000` | total token budget for retrieved context |
| `KDX_MAX_FILE_TOKENS` | `550` | per-file token budget |
| `KDX_MAX_FILES` | `6` | max files in context |
| `KDX_MAX_SNIPPETS` | `10` | max snippets |
| `KDX_MAX_SEARCH_RESULTS` | `5` | max keiro search results |
| `KDX_MODEL` | `gpt-5.4` | model to use with codex |
| `KDX_AUTO_INIT` | `1` | auto-initialize index on startup |

## local state

kdx writes runtime data to:
- `.kdx/` inside the repo (ignored, don't commit)
- `~/.kdx/config.json` for the persisted keiro key

## token comparison

kdx includes a direct benchmark against vanilla codex:

```bash
kdx tokens "where is the Keiro client implemented? reply with the path only."
kdx tokens --prompts-file bench/prompts_kdx_repo.txt --json
```

uses real `codex exec --json` runs and reads `turn.completed.usage` — numbers come from actual model usage, not local estimates.

## uninstall

### linux / macos

```bash
rm -f "$(python3 -c 'import site, pathlib; print(pathlib.Path(site.getuserbase()) / "bin" / "kdx")')"
rm -rf ~/.kdx
rm -rf .kdx .venv
```

then delete the cloned repo directory.

### windows (powershell)

```powershell
$base = py -3 -c "import site; print(site.getuserbase())"
Remove-Item "$base\Scripts\kdx.cmd" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\.kdx" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item ".kdx",".venv" -Recurse -Force -ErrorAction SilentlyContinue
```

then delete the cloned repo directory.

## development

```bash
python bootstrap.py --setup-only
python bootstrap.py --python -m unittest discover -s tests -v
python bootstrap.py --python -m compileall src/kdx
python bootstrap.py --python -m pip install build
python bootstrap.py --python -m build
```

## project layout

```
src/kdx/
  cli.py              cli entrypoint
  wrapper.py          codex launch flow + workspace tree injection
  codex_home.py       temporary CODEX_HOME generation
  indexer.py          12-language symbol extraction + dependency graph
  retrieval.py        token-aware retrieval, scoring, impact analysis
  budget.py           token-based budget governance
  models.py           data models (SymbolRecord, FileRecord, ProjectIndex)
  search_service.py   keiro search planning and evidence ranking
  mcp_code_server.py  repo MCP server (scan, retrieve, read)
  mcp_search_server.py  web MCP server (keiro endpoints)
  updates.py          auto-update mechanism (stash + reset)
  config.py           settings, env vars, persisted config
  token_compare.py    kdx vs vanilla codex token benchmarking
```

## status

core is production-grade:

- index v5 — deep 12-language symbol extraction with cross-file dependency graph
- token-aware retrieval — multi-signal scoring with centrality, decorators, docstrings, signatures, visibility
- workspace orientation — tree + key files injected at session start
- bulletproof updates — stash-and-reset across all platforms
- 65 tests passing

## license

MIT
