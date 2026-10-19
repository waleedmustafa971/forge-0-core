"""SQLAlchemy engine/session management."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import BACKEND_DIR, get_settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _make_engine(url: str, pool_size: int = 10) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=pool_size,
        connect_args={"connect_timeout": 10},
    )


def configure_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    settings = get_settings()
    _engine = _make_engine(url or settings.database_url, settings.db_pool_size)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure_engine()
    assert _engine is not None
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        configure_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def wait_for_database(timeout_s: float = 90.0, interval_s: float = 2.0) -> None:
    """Blocks until the database accepts connections (it may still be starting, e.g. when the
    WSL distro hosting Docker was just woken up). Raises the last error after `timeout_s`."""
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while True:
        attempt += 1
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            if attempt > 1:
                log.info("database reachable", extra={"attempts": attempt})
            return
        except OperationalError:
            if time.monotonic() >= deadline:
                raise
            log.warning("database not reachable yet; retrying", extra={"attempt": attempt})
            time.sleep(interval_s)


def init_db() -> None:
    """Creates the schema: SQLite via metadata, PostgreSQL via Alembic migrations."""
    from core import models  # noqa: F401  (register mappers)

    engine = get_engine()
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        return
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    cfg.attributes["explicit_url"] = True
    cfg.attributes["skip_logging"] = True
    command.upgrade(cfg, "head")
    log.info("database migrated", extra={"dialect": engine.dialect.name})
