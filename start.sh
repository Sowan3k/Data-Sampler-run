#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Install Python 3.11, 3.12 or 3.13 first.'; exit 1; }
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
# Reinstall whenever requirements.txt changes.
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  .venv/bin/python -m pip install -r requirements.txt
  cp requirements.txt .venv/installed-requirements.txt
fi
exec .venv/bin/python run.py
