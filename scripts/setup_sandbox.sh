#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ -S "$HOME/.colima/minioj/docker.sock" ]; then
  export DOCKER_CONTEXT=colima-minioj
fi
if ! command -v docker >/dev/null; then
  echo 'Install Docker, or on macOS: brew install colima docker' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  if command -v colima >/dev/null; then
    colima start minioj --vm-type vz --cpu 2 --memory 2 --disk 8 --mount-type virtiofs
  else
    echo 'Start your Docker daemon first.' >&2
    exit 1
  fi
fi
docker build -t minioj-sandbox:1 .
