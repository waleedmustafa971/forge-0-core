"""Test configuration: isolated SQLite database and data directory per session."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="forge0-tests-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "DATA_DIR": str(_TMP / "data"),
        "AI_PROVIDER": "mock",
        "META_API_KEY": "",
        "MODEL_API_KEY": "",
        "AUTH_MODE": "local",
        "SEED_DEMO": "true",
        "LOG_FORMAT": "text",
        "LOG_LEVEL": "WARNING",
        "SANDBOX_WSL_KEEPALIVE": "false",
    }
)

from core.config import REPO_ROOT, get_settings  # noqa: E402
from core.database import configure_engine, init_db  # noqa: E402

get_settings.cache_clear()
configure_engine(os.environ["DATABASE_URL"])
init_db()

DEMO = REPO_ROOT / "demo" / "order-management"


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture
def demo_copy(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(DEMO, target, ignore=shutil.ignore_patterns("node_modules"))
    return target


_docker_status: bool | None = None


def docker_available() -> bool:
    global _docker_status
    if _docker_status is None:
        from sandbox.docker import DockerSandbox

        _docker_status = DockerSandbox().status(refresh=True).available
    return _docker_status


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    pg_url = os.environ.get("TEST_POSTGRES_URL")
    for item in items:
        if "docker" in item.keywords and not docker_available():
            item.add_marker(pytest.mark.skip(reason="Docker sandbox not available"))
        if "postgres" in item.keywords and not pg_url:
            item.add_marker(pytest.mark.skip(reason="TEST_POSTGRES_URL not set"))
