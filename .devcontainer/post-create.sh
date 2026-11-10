#!/usr/bin/env bash
set -euo pipefail

# Docker creates fresh volume mount points as root; hand them to vscode.
sudo chown -R vscode:vscode .venv /home/vscode/.claude

# Only build the venv if the volume doesn't already hold a working one.
if ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
  python -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
if [ -f requirements.txt ]; then
  .venv/bin/python -m pip install -r requirements.txt
fi

printf '\nReady. Run: claude\n'
