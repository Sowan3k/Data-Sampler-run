#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Install Python 3.11 or 3.12 first.'; exit 1; }
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if [ ! -f .venv/installed.flag ]; then .venv/bin/python -m pip install -r requirements.txt; touch .venv/installed.flag; fi
exec .venv/bin/python run.py
