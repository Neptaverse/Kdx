#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
"$ROOT/.venv/bin/python" -m pip install --upgrade "pip<26" "setuptools<81" "wheel>=0.43,<0.46"
"$ROOT/.venv/bin/python" -m pip install -e .

echo "KDX virtualenv ready: $ROOT/.venv"
echo "Run with: $ROOT/.venv/bin/kdx"
echo "Or activate with: source $ROOT/.venv/bin/activate"
