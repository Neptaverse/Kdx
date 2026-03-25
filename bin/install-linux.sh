#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${KDX_REPO_URL:-https://github.com/Neptaverse/Kdx.git}"
BRANCH="${KDX_BRANCH:-main}"
INSTALL_ROOT="${KDX_INSTALL_ROOT:-$HOME/.kdx/src}"
REPO_DIR="${KDX_REPO_DIR:-$INSTALL_ROOT/Kdx}"

log() {
  printf '[kdx-install] %s\n' "$*"
}

fail() {
  printf '[kdx-install] ERROR: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

is_final_python() {
  local py="$1"
  "$py" -c 'import sys; raise SystemExit(0 if sys.version_info.releaselevel == "final" else 1)' >/dev/null 2>&1
}

pick_python() {
  local candidates=()
  if [[ -n "${KDX_PYTHON:-}" ]]; then
    candidates+=("${KDX_PYTHON}")
  fi
  candidates+=("python3.12" "python3.11" "python3")
  local py
  for py in "${candidates[@]}"; do
    if ! command -v "$py" >/dev/null 2>&1; then
      continue
    fi
    if is_final_python "$py"; then
      printf '%s\n' "$py"
      return 0
    fi
  done
  return 1
}

sync_repo() {
  mkdir -p "$INSTALL_ROOT"
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "cloning KDX into $REPO_DIR"
    git clone "$REPO_URL" "$REPO_DIR"
    return 0
  fi
  log "using existing clone at $REPO_DIR"
  if [[ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null || true)" ]]; then
    log "local changes detected; skipping git pull"
    return 0
  fi
  git -C "$REPO_DIR" remote set-url origin "$REPO_URL" || true
  git -C "$REPO_DIR" fetch --depth=1 origin "$BRANCH" >/dev/null 2>&1 || git -C "$REPO_DIR" fetch origin
  git -C "$REPO_DIR" checkout "$BRANCH" >/dev/null 2>&1 || true
  git -C "$REPO_DIR" pull --ff-only || true
}

print_path_hint() {
  local py="$1"
  local bin_dir
  bin_dir="$("$py" -c 'import site, pathlib; print(pathlib.Path(site.getuserbase()) / "bin")')"
  log "kdx is installed but not on PATH."
  log "add this to your shell profile:"
  printf 'export PATH="%s:$PATH"\n' "$bin_dir"
}

main() {
  need_cmd git
  local py
  if ! py="$(pick_python)"; then
    fail "no stable python found (need Python 3.11 or 3.12 final). Install python3 and retry."
  fi
  log "using Python: $("$py" --version 2>&1)"
  sync_repo
  (cd "$REPO_DIR" && "$py" bootstrap.py --setup-only)
  if command -v kdx >/dev/null 2>&1; then
    log "install complete. run: kdx"
  else
    print_path_hint "$py"
  fi
}

main "$@"
