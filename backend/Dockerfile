# Build context: repository root (needed to bundle the demo repository and benchmarks).
FROM docker:29-cli AS dockercli

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI only (no daemon): used to launch isolated experiment containers.
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app/backend
COPY backend/pyproject.toml ./
RUN pip install --upgrade pip && pip install \
      "fastapi>=0.115" "uvicorn[standard]>=0.32" "sqlalchemy>=2.0.36" "psycopg[binary]>=3.2.3" \
      "alembic>=1.14" "pydantic>=2.9" "pydantic-settings>=2.6" "httpx>=0.28"

COPY backend/ ./
COPY demo/ /app/demo/
COPY benchmarks/ /app/benchmarks/

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/system/health')"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
