"""In-process background job runner for investigations."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime

from core.config import get_settings
from core.database import session_scope
from core.models import Event, Investigation

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, workers: int | None = None) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=workers or get_settings().worker_threads, thread_name_prefix="forge-job"
        )
        self._futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()

    def submit(self, investigation_id: str, fn: Callable[[], None]) -> None:
        def wrapped() -> None:
            try:
                fn()
            except Exception:  # pragma: no cover - orchestrator handles its own errors
                log.exception("job crashed", extra={"investigation": investigation_id})

        with self._lock:
            self._futures[investigation_id] = self._pool.submit(wrapped)

    def is_running(self, investigation_id: str) -> bool:
        with self._lock:
            future = self._futures.get(investigation_id)
            return future is not None and not future.done()

    def wait(self, investigation_id: str, timeout: float | None = None) -> None:
        with self._lock:
            future = self._futures.get(investigation_id)
        if future is not None:
            future.result(timeout=timeout)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def recover_interrupted() -> int:
    """Marks investigations left running by a previous process as failed."""
    count = 0
    with session_scope() as db:
        rows = (
            db.query(Investigation)
            .filter(Investigation.status.in_(["queued", "running", "cancelling"]))
            .all()
        )
        for inv in rows:
            inv.status = "failed"
            inv.phase = "failed"
            inv.active_agent = None
            inv.error = "Interrupted: the backend restarted while this investigation was in progress"
            inv.finished_at = datetime.now(UTC)
            db.add(
                Event(
                    investigation_id=inv.id,
                    agent="orchestrator",
                    type="error",
                    message=inv.error,
                    data={},
                )
            )
            count += 1
    return count


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner
