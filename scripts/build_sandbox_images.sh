#!/usr/bin/env bash
# Pulls/builds the sandbox runtime images used for experiments.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker pull node:24-alpine
docker build -t forge0/sandbox-python:3.12 "$ROOT/backend/sandbox/images/python"
echo "Sandbox images ready."
