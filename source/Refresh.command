#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "First create the local environment: python3 -m venv .venv"
    echo "Then install requirements: .venv/bin/python -m pip install -r requirements.txt"
    exit 1
fi
exec .venv/bin/python scripts/refresh.py
