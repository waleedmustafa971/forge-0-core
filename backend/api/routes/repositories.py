from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.deps import get_db, require_auth
from api.schemas import RepositoryCreate, RepositoryOut
from core.models import Repository
from core.schemas import RuntimeProfile
from sandbox.docker import get_sandbox
from services import repositories as repo_service

router = APIRouter(prefix="/api/repositories", tags=["repositories"], dependencies=[Depends(require_auth)])


def _get(db: Session, repo_id: str) -> Repository:
    repo = db.get(Repository, repo_id)
    if repo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found")
    return repo


@router.post("", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
def create_repository(body: RepositoryCreate, db: Session = Depends(get_db)) -> Repository:
    try:
        if body.source_type == "local":
            assert body.path
            return repo_service.import_local(db, body.path, body.name)
        assert body.url
        return repo_service.import_git(db, body.url, body.name, body.ref)
    except repo_service.ImportError_ as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("", response_model=list[RepositoryOut])
def list_repositories(db: Session = Depends(get_db)) -> list[Repository]:
    return db.query(Repository).order_by(Repository.created_at.desc()).all()


@router.get("/{repo_id}", response_model=RepositoryOut)
def get_repository(repo_id: str, db: Session = Depends(get_db)) -> Repository:
    return _get(db, repo_id)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repository(repo_id: str, db: Session = Depends(get_db)) -> None:
    repo_service.delete_repository(db, _get(db, repo_id))


@router.get("/{repo_id}/tree")
def repository_tree(repo_id: str, db: Session = Depends(get_db)) -> dict:
    repo = _get(db, repo_id)
    return {"repository_id": repo.id, "files": repo_service.tree(repo)}


@router.get("/{repo_id}/file")
def repository_file(
    repo_id: str, path: str = Query(..., max_length=1000), db: Session = Depends(get_db)
) -> dict:
    try:
        return repo_service.read_file(_get(db, repo_id), path)
    except repo_service.ImportError_ as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{repo_id}/scan")
def scan_repository(repo_id: str, db: Session = Depends(get_db)) -> dict:
    """Runs the repository's test suite in the sandbox and records which tests fail."""
    repo = _get(db, repo_id)
    runtime = RuntimeProfile.model_validate(
        repo.profile.get("runtime", {"runtime": "unknown", "runner": None})
    )
    if not runtime.runner or not runtime.test_targets:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No supported test runner detected for this repository"
        )
    result = get_sandbox().run_tests(Path(repo.snapshot_path), runtime.runner, runtime.test_targets)
    if result.infra_error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, result.infra_error)
    tr = result.test_run
    scan = {
        "scanned_at": datetime.now(UTC).isoformat(),
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
        "command": result.command,
        "image": result.image,
        "total": tr.total if tr else 0,
        "passed": tr.passed if tr else 0,
        "failed": tr.failed if tr else 0,
        "tests": [
            {"name": t.name, "file": t.file, "status": t.status, "error": (t.error or "")[:300]}
            for t in (tr.tests if tr else [])
        ],
    }
    repo.last_scan = scan
    return scan
