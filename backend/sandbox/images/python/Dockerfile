# Optional sandbox runtime for Python repositories (runner: pytest).
# Build: scripts/build_sandbox_images.sh  ->  forge0/sandbox-python:3.12
FROM python:3.12-alpine
RUN pip install --no-cache-dir "pytest>=8.3" \
    && adduser -D -u 1000 sandbox
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work
