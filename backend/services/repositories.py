"""Repository import, snapshots and source browsing.

Imports are copied into ``DATA_DIR/repos/<id>/snapshot`` so investigations never touch
the original. Git imports use ``git clone`` with hooks disabled (cloning executes no
repository code). Local imports are restricted to configured roots.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import Repository
from services.repo_analysis import SKIP_DIRS, list_files, profile_repository
from services.workspace import EditError, safe_relative

log = logging.getLogger(__name__)

_GIT_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d+)?/[A-Za-z0-9._~/-]+?(?:\.git)?/?$")
MAX_FILE_VIEW_BYTES = 400_000


class ImportError_(ValueError):
    pass


def _copy_tree(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(*SKIP_DIRS)
    shutil.copytree(src, dst, ignore=ignore, symlinks=True)


def _git_sha(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _snapshot_dir(repo_id: str) -> Path:
    return get_settings().data_dir / "repos" / repo_id / "snapshot"


def import_local(db: Session, path: str, name: str | None = None, source_type: str = "local") -> Repository:
    settings = get_settings()
    src = Path(path).expanduser().resolve()
    if not src.is_dir():
        raise ImportError_(f"Directory not found: {path}")
    allowed = [r.resolve() for r in settings.allowed_import_roots]
    if not any(src == root or root in src.parents for root in allowed):
        raise ImportError_(
            "Local imports are restricted to: "
            + ", ".join(str(r) for r in allowed)
            + " (set IMPORT_ALLOWED_ROOTS)"
        )
    repo_id = uuid.uuid4().hex
    snapshot = _snapshot_dir(repo_id)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree(src, snapshot)
    repo = Repository(
        id=repo_id,
        name=name or src.name,
        source_type=source_type,
        source=str(src),
        snapshot_path=str(snapshot),
        commit_sha=_git_sha(src),
        profile=profile_repository(snapshot),
    )
    db.add(repo)
    db.flush()
    return repo


def import_git(db: Session, url: str, name: str | None = None, ref: str | None = None) -> Repository:
    if not _GIT_URL.match(url):
        raise ImportError_("Only https:// Git URLs are supported")
    if ref and not re.match(r"^[A-Za-z0-9._/-]{1,100}$", ref):
        raise ImportError_("Invalid ref")
    repo_id = uuid.uuid4().hex
    base = get_settings().data_dir / "repos" / repo_id
    clone_dir = base / "clone"
    base.mkdir(parents=True, exist_ok=True)
    cmd = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "protocol.file.allow=never",
        "clone",
        "--depth",
        "1",
    ]
    if ref:
        cmd += ["--branch", ref]
    cmd += ["--", url, str(clone_dir)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, env={"GIT_TERMINAL_PROMPT": "0", **_git_env()}
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(base, ignore_errors=True)
        raise ImportError_("git clone timed out") from exc
    if proc.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        raise ImportError_(f"git clone failed: {proc.stderr.strip()[:300]}")
    sha = _git_sha(clone_dir)
    snapshot = base / "snapshot"
    _copy_tree(clone_dir, snapshot)
    shutil.rmtree(clone_dir, ignore_errors=True)
    repo = Repository(
        id=repo_id,
        name=name or url.rstrip("/").split("/")[-1].removesuffix(".git"),
        source_type="git",
        source=url,
        snapshot_path=str(snapshot),
        commit_sha=sha,
        profile=profile_repository(snapshot),
    )
    db.add(repo)
    db.flush()
    return repo


def _git_env() -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "TEMP", "TMP")
    return {k: v for k, v in os.environ.items() if k in keep}


def ensure_demo(db: Session) -> Repository | None:
    settings = get_settings()
    existing = db.query(Repository).filter_by(source_type="demo").first()
    if existing is not None:
        if Path(existing.snapshot_path).is_dir():
            return existing
        db.delete(existing)
        db.flush()
    if not settings.demo_repo_path.is_dir():
        return None
    return import_local(db, str(settings.demo_repo_path), name="order-management (demo)", source_type="demo")


def tree(repo: Repository) -> list[dict[str, Any]]:
    root = Path(repo.snapshot_path)
    out = []
    for rel in list_files(root):
        size = (root / rel).stat().st_size
        out.append({"path": rel, "size": size})
    return out


def read_file(repo: Repository, rel: str) -> dict[str, Any]:
    root = Path(repo.snapshot_path)
    try:
        path = safe_relative(root, rel)
    except EditError as exc:
        raise ImportError_(str(exc)) from exc
    if not path.is_file():
        raise ImportError_("File not found")
    size = path.stat().st_size
    data = path.read_bytes()[:MAX_FILE_VIEW_BYTES]
    if b"\x00" in data[:4096]:
        return {"path": rel, "size": size, "binary": True, "content": ""}
    return {
        "path": rel,
        "size": size,
        "binary": False,
        "truncated": size > MAX_FILE_VIEW_BYTES,
        "content": data.decode("utf-8", errors="replace"),
    }


def delete_repository(db: Session, repo: Repository) -> None:
    base = get_settings().data_dir / "repos" / repo.id
    db.delete(repo)
    db.flush()
    shutil.rmtree(base, ignore_errors=True)
