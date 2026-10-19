#!/usr/bin/env bash
# Starts the FORGE-0 development stack on Linux/macOS (or inside WSL).
#   API http://127.0.0.1:8010 · UI http://127.0.0.1:5173 · PostgreSQL 127.0.0.1:5433
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example"; }
mkdir -p data

docker compose up -d db
echo "Waiting for PostgreSQL..."
for _ in $(seq 1 40); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' forge0-db-1)" = "healthy" ] && break
  sleep 2
done

cd backend
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8010 > ../data/backend.log 2>&1 &
BACKEND_PID=$!
echo "Backend pid $BACKEND_PID (log: data/backend.log)"

cd ../frontend
[ -d node_modules ] || npm ci --no-audit --no-fund
trap 'kill $BACKEND_PID 2>/dev/null' EXIT
npm run dev -- --host 127.0.0.1
