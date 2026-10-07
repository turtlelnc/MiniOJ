#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec .venv/bin/python -m uvicorn minioj.app:app --host 127.0.0.1 --port "${MINIOJ_PORT:-8000}" --ws-max-size 65536 --ws-max-queue 8
