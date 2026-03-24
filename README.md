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

## Quick Start

```bash
git clone https://github.com/Neptaverse/Kdx.git
cd Kdx

./bin/setup-venv.sh

.venv/bin/kdx /keiro keiro_your_api_key_here
.venv/bin/kdx
```

On the first run, KDX will initialize its local workspace data automatically.

This avoids Conda or shell aliases hijacking `pip` or `python`.

## Common Commands

```bash
.venv/bin/kdx
.venv/bin/kdx "fix the auth retry path and check the latest SDK docs"
.venv/bin/kdx scan
.venv/bin/kdx plan "where is the Keiro client implemented?"
.venv/bin/kdx search "latest FastMCP docs"
.venv/bin/kdx tokens "where is the Keiro client implemented? reply with the path only."
```

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

KDX can read the Keiro API key from either:

- `~/.kdx/config.json`
- `KEIRO_API_KEY`
- `KDX_KEIRO_API_KEY`

The easiest setup is:

```bash
.venv/bin/kdx /keiro keiro_your_api_key_here
```

The persisted config is stored outside the repo and is written with private file permissions.

## Local State

KDX writes local runtime data to:

- `.kdx/` inside the repo
- `~/.kdx/config.json` for the persisted Keiro key

The repo-local `.kdx/` directory is intentionally ignored and should not be committed.

## Token Comparison

KDX includes a direct benchmark against vanilla Codex:

```bash
.venv/bin/kdx tokens "where is the Keiro client implemented? reply with the path only."
.venv/bin/kdx tokens --prompts-file bench/prompts_kdx_repo.txt --json
```

This uses real `codex exec --json` runs and reads `turn.completed.usage`, so the numbers come from actual model usage rather than local estimates.

## Development

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall src/kdx
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

## Notes Before Open Source

- Add a license before publishing
- Keep `.kdx/`, `.bench/`, and `.venv/` out of the repo
- Treat the token benchmark as a real measurement tool, not a marketing number

If KDX says it is cheaper or better, it should be able to prove it on prompts you actually care about
