"""Static repository analysis: languages, frameworks, tests, runtime and import graph.

Reads files only; never executes repository code.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from core.schemas import FileExcerpt, RuntimeProfile
from sandbox.runners import get_runner
from services.workspace import is_test_path

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    "coverage",
}
LANGUAGES = {
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mts": "TypeScript",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".py": "Python",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".json": "JSON",
    ".md": "Markdown",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
}
SOURCE_EXT = {".ts", ".tsx", ".mts", ".js", ".mjs", ".cjs", ".jsx", ".py"}
FRAMEWORK_HINTS = {
    "express": "Express",
    "fastify": "Fastify",
    "@nestjs/core": "NestJS",
    "react": "React",
    "next": "Next.js",
    "jest": "Jest",
    "vitest": "Vitest",
    "mocha": "Mocha",
    "typescript": "TypeScript compiler",
    "prisma": "Prisma",
    "pg": "node-postgres",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "pytest": "pytest",
}
_IMPORT_TS = re.compile(
    r"""(?:import|export)\s[^'"]*?from\s+['"](\.{1,2}/[^'"]+)['"]|import\(\s*['"](\.{1,2}/[^'"]+)['"]"""
)
_IMPORT_PY = re.compile(r"^\s*from\s+(\.+[\w.]*|[\w.]+)\s+import|^\s*import\s+([\w.]+)", re.MULTILINE)
_NODE_TEST_GLOB = re.compile(r"node\s+(?:--[\w-]+(?:=\S+)?\s+)*--test\b(?P<rest>.*)")


def list_files(root: Path, limit: int = 5000) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".cache"))
        for name in sorted(filenames):
            path = Path(dirpath, name)
            if path.is_symlink():
                continue
            files.append(path.relative_to(root).as_posix())
            if len(files) >= limit:
                return files
    return files


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def detect_runtime(root: Path, files: list[str]) -> RuntimeProfile:
    pkg = read_json(root / "package.json")
    notes: list[str] = []
    if pkg:
        script = (pkg.get("scripts") or {}).get("test", "")
        match = _NODE_TEST_GLOB.search(script)
        targets: list[str] = []
        if match:
            targets = [t.strip("'\"") for t in re.findall(r"""['"][^'"]+['"]|\S+""", match.group("rest"))]
            targets = [t for t in targets if not t.startswith("-")]
            notes.append(f"package.json test script uses the node:test runner: {script!r}")
        if not targets:
            test_files = [f for f in files if re.search(r"\.(test|spec)\.(ts|mts|js|mjs|cjs)$", f)]
            targets = test_files[:20]
            if script:
                notes.append(
                    f"Test script {script!r} is not a plain node --test invocation; FORGE-0 runs test files "
                    "directly with the allowlisted node_test runner."
                )
        runner = get_runner("node_test")
        return RuntimeProfile(
            runtime="node", runner="node_test", test_targets=targets, image=runner.image(), notes=notes
        )
    if (
        (root / "pyproject.toml").exists()
        or (root / "setup.py").exists()
        or any(f.endswith(".py") for f in files)
    ):
        tests = [f for f in files if re.search(r"(^|/)test_[^/]+\.py$|_test\.py$", f)]
        runner = get_runner("pytest")
        return RuntimeProfile(
            runtime="python",
            runner="pytest",
            test_targets=tests[:20] or ["tests/"],
            image=runner.image(),
            notes=["Python projects run with the pytest runner (sandbox image must be built locally)."],
        )
    return RuntimeProfile(runtime="unknown", runner=None, notes=["No supported runtime detected"])


def profile_repository(root: Path) -> dict[str, Any]:
    files = list_files(root)
    languages = Counter(LANGUAGES[Path(f).suffix] for f in files if Path(f).suffix in LANGUAGES)
    pkg = read_json(root / "package.json")
    deps: dict[str, str] = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    frameworks = sorted({label for dep, label in FRAMEWORK_HINTS.items() if dep in deps})
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8", errors="replace").lower()
        frameworks += sorted({label for dep, label in FRAMEWORK_HINTS.items() if f'"{dep}' in text})
    package_manager = None
    if (root / "package-lock.json").exists():
        package_manager = "npm"
    elif (root / "pnpm-lock.yaml").exists():
        package_manager = "pnpm"
    elif (root / "yarn.lock").exists():
        package_manager = "yarn"
    elif pkg:
        package_manager = "npm"
    elif pyproject.exists():
        package_manager = "pip"
    runtime = detect_runtime(root, files)
    if runtime.runtime == "node" and any(f.endswith(".ts") for f in files) and "typescript" not in deps:
        frameworks.append("TypeScript (type stripping)")
    if runtime.runner == "node_test":
        frameworks.append("node:test")
    source = [f for f in files if Path(f).suffix in SOURCE_EXT and not is_test_path(f)]
    tests = [f for f in files if Path(f).suffix in SOURCE_EXT and is_test_path(f)]
    return {
        "file_count": len(files),
        "languages": dict(languages.most_common()),
        "frameworks": sorted(set(frameworks)),
        "package_manager": package_manager,
        "dependencies": deps,
        "source_files": source,
        "test_files": tests,
        "runtime": runtime.model_dump(),
    }


def resolve_import(root: Path, from_file: str, spec: str) -> str | None:
    base = PurePosixPath(from_file).parent
    candidate = posixpath.normpath((base / spec).as_posix())
    if candidate.startswith(".."):
        return None
    options = [candidate]
    if not Path(candidate).suffix:
        options += [candidate + ext for ext in (".ts", ".js", ".mjs", ".tsx")] + [
            f"{candidate}/index.ts",
            f"{candidate}/index.js",
        ]
    elif candidate.endswith(".js"):
        options.append(candidate[:-3] + ".ts")
    for option in options:
        if (root / option).is_file():
            return option
    return None


def imports_of(root: Path, rel: str) -> list[str]:
    path = root / rel
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[str] = []
    if path.suffix in {".ts", ".tsx", ".mts", ".js", ".mjs", ".cjs", ".jsx"}:
        for match in _IMPORT_TS.finditer(text):
            spec = match.group(1) or match.group(2)
            resolved = resolve_import(root, rel, spec)
            if resolved and resolved not in found:
                found.append(resolved)
    return found


def collect_relevant_files(
    root: Path,
    seeds: list[tuple[str, str]],
    *,
    max_files: int = 14,
    max_total_chars: int = 60_000,
    per_file_chars: int = 12_000,
) -> list[FileExcerpt]:
    """Breadth-first walk from seed files through relative imports, bounded by size."""
    queue: list[tuple[str, str]] = list(seeds)
    seen: set[str] = set()
    excerpts: list[FileExcerpt] = []
    total = 0
    while queue and len(excerpts) < max_files and total < max_total_chars:
        rel, reason = queue.pop(0)
        if rel in seen or not (root / rel).is_file():
            continue
        seen.add(rel)
        try:
            content = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        truncated = len(content) > per_file_chars
        content = content[:per_file_chars]
        total += len(content)
        excerpts.append(FileExcerpt(path=rel, content=content, truncated=truncated, reason=reason))
        for dep in imports_of(root, rel):
            if dep not in seen:
                queue.append((dep, f"imported by {rel}"))
    return excerpts
