"""Disposable working copies, safe file edits and unified diffs.

Edits are applied only to throw-away copies under ``DATA_DIR/workspaces``; the imported
repository snapshot is never modified. Nothing here executes repository code.
"""

from __future__ import annotations

import difflib
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core.config import get_settings
from core.schemas import ExperimentFile, SourceEdit

IGNORED = shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".venv", ".pytest_cache")
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|\.(test|spec)\.[A-Za-z]+$|(^|/)test_[^/]+\.py$")
MAX_EDIT_FILE_BYTES = 1_000_000


class EditError(ValueError):
    pass


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH.search(path.replace("\\", "/")))


def safe_relative(root: Path, rel: str) -> Path:
    """Resolves `rel` under `root`, refusing absolute paths, traversal and symlink escapes."""
    rel = rel.strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise EditError(f"Path must be relative to the repository root: {rel!r}")
    parts = PurePosixPath(rel).parts
    if any(p in ("..", "") for p in parts) or parts[0] in (".git", "node_modules"):
        raise EditError(f"Illegal path: {rel!r}")
    target = (root / Path(*parts)).resolve()
    root_resolved = root.resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise EditError(f"Path escapes the workspace: {rel!r}")
    return target


@dataclass
class FileChange:
    path: str
    before: str
    after: str
    created: bool = False

    @property
    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile="/dev/null" if self.created else f"a/{self.path}",
                tofile=f"b/{self.path}",
                n=3,
            )
        )

    def stats(self) -> dict[str, int | str | bool]:
        added = removed = 0
        for line in self.diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
        return {"path": self.path, "added": added, "removed": removed, "created": self.created}


@dataclass
class EditResult:
    changes: list[FileChange] = field(default_factory=list)

    @property
    def diff(self) -> str:
        parts = []
        for change in self.changes:
            d = change.diff
            if d and not d.endswith("\n"):
                d += "\n"
            parts.append(d)
        return "".join(parts)

    def files_changed(self) -> list[dict[str, int | str | bool]]:
        return [c.stats() for c in self.changes]


def _locate(content: str, search: str) -> tuple[int, int] | None:
    """Finds `search` exactly once; falls back to a trailing-whitespace/CRLF tolerant match."""
    count = content.count(search)
    if count == 1:
        start = content.index(search)
        return start, start + len(search)
    if count > 1:
        raise EditError("Search text matches more than once; include more surrounding context")
    norm_lines = [line.rstrip() for line in search.replace("\r\n", "\n").split("\n")]
    pattern = r"[ \t]*\r?\n".join(re.escape(line) for line in norm_lines)
    matches = list(re.finditer(pattern, content))
    if len(matches) == 1:
        return matches[0].start(), matches[0].end()
    if len(matches) > 1:
        raise EditError("Search text matches more than once; include more surrounding context")
    return None


def apply_edits(
    root: Path, edits: list[SourceEdit], *, allow_test_files: bool, allow_create: bool
) -> EditResult:
    """Applies search/replace edits in-place under `root` (a disposable copy)."""
    if not edits:
        raise EditError("No edits supplied")
    originals: dict[str, str] = {}
    current: dict[str, str] = {}
    created: set[str] = set()
    for edit in edits:
        rel = edit.file.strip().replace("\\", "/").removeprefix("./")
        if not allow_test_files and is_test_path(rel):
            raise EditError(f"Repairs may not modify test files: {rel}")
        target = safe_relative(root, rel)
        if rel not in current:
            if target.exists():
                if target.stat().st_size > MAX_EDIT_FILE_BYTES:
                    raise EditError(f"File too large to edit: {rel}")
                # newline="" preserves CRLF so patches never rewrite a file's line endings
                with target.open(encoding="utf-8", newline="") as handle:
                    text = handle.read()
            elif allow_create and edit.search == "":
                text = ""
                created.add(rel)
            else:
                raise EditError(f"File does not exist: {rel}")
            originals[rel] = text
            current[rel] = text
        text = current[rel]
        if edit.search == "":
            if text and rel not in created:
                raise EditError(f"Empty search text is only allowed when creating a new file: {rel}")
            current[rel] = edit.replace
            continue
        span = _locate(text, edit.search)
        if span is None:
            raise EditError(f"Search text not found in {rel}: {edit.search[:120]!r}")
        current[rel] = text[: span[0]] + edit.replace + text[span[1] :]
    result = EditResult()
    for rel, after in current.items():
        if after == originals[rel]:
            continue
        target = safe_relative(root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(after, encoding="utf-8", newline="")
        result.changes.append(FileChange(rel, originals[rel], after, created=rel in created))
    if not result.changes:
        raise EditError("Edits produced no change")
    return result


def add_files(root: Path, files: list[ExperimentFile], *, max_files: int = 5) -> list[str]:
    """Adds new experiment files; existing files may never be overwritten."""
    if len(files) > max_files:
        raise EditError(f"At most {max_files} experiment files are allowed")
    written = []
    for item in files:
        rel = item.path.strip().replace("\\", "/").removeprefix("./")
        target = safe_relative(root, rel)
        if target.exists():
            raise EditError(f"Experiment files must be new; {rel} already exists")
        if len(item.content) > 200_000:
            raise EditError(f"Experiment file too large: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8", newline="")
        written.append(rel)
    return written


class WorkspaceManager:
    def __init__(self, base: Path | None = None) -> None:
        self.base = base or get_settings().data_dir / "workspaces"

    def create(self, snapshot: Path, investigation_id: str, label: str) -> Path:
        safe_label = re.sub(r"[^A-Za-z0-9_.-]", "_", label)[:60]
        target = self.base / investigation_id / f"{safe_label}-{uuid.uuid4().hex[:6]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        # symlinks=True copies links as links (never their targets); the sandbox tar skips them.
        shutil.copytree(snapshot, target, ignore=IGNORED, symlinks=True)
        return target

    def cleanup(self, investigation_id: str) -> None:
        shutil.rmtree(self.base / investigation_id, ignore_errors=True)

    def discard(self, path: Path) -> None:
        if self.base.resolve() in path.resolve().parents:
            shutil.rmtree(path, ignore_errors=True)
