"""Allowlisted experiment runners.

Models never supply shell commands. They choose a runner by name and a list of test
targets; this module validates the targets and builds the exact argv executed inside
the sandbox container.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from core.config import get_settings


class RunnerValidationError(ValueError):
    pass


_TARGET = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./*\-]{0,200}$")
_PATTERN_MAX = 200


def validate_target(target: str, extensions: tuple[str, ...]) -> str:
    target = target.strip().replace("\\", "/")
    if target.startswith("./"):
        target = target[2:]
    if not _TARGET.match(target) or ".." in target.split("/") or "//" in target:
        raise RunnerValidationError(f"Illegal test target: {target!r}")
    if not target.endswith(extensions) and not target.endswith("/"):
        raise RunnerValidationError(f"Test target {target!r} must end with one of {extensions}")
    return target


def validate_pattern(pattern: str | None) -> str | None:
    if pattern is None or pattern == "":
        return None
    if len(pattern) > _PATTERN_MAX or "\n" in pattern or "\x00" in pattern:
        raise RunnerValidationError("Illegal test name pattern")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise RunnerValidationError(f"Invalid test name pattern: {exc}") from exc
    return pattern


@dataclass(frozen=True)
class Runner:
    name: str
    runtime: str
    extensions: tuple[str, ...]
    description: str

    def image(self) -> str:
        settings = get_settings()
        return settings.sandbox_node_image if self.runtime == "node" else settings.sandbox_python_image

    def argv(self, targets: list[str], test_name_pattern: str | None = None) -> list[str]:
        if not targets:
            raise RunnerValidationError("At least one test target is required")
        if len(targets) > 20:
            raise RunnerValidationError("Too many test targets")
        safe = [validate_target(t, self.extensions) for t in targets]
        pattern = validate_pattern(test_name_pattern)
        if self.name == "node_test":
            argv = ["node", "--test", "--test-reporter=tap", "--test-concurrency=1"]
            if pattern:
                argv.append(f"--test-name-pattern={pattern}")
            return argv + safe
        if self.name == "pytest":
            argv = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short"]
            if pattern:
                argv += ["-k", pattern]
            return argv + safe
        raise RunnerValidationError(f"Unknown runner {self.name}")

    def shell_script(self, argv: list[str], timeout_s: int) -> str:
        """POSIX script run by `sh -c` in the container: unpack workspace, then exec the runner."""
        quoted = " ".join(shlex.quote(a) for a in argv)
        return f"tar -xf - -C /work && cd /work && exec timeout -s KILL {int(timeout_s)} {quoted}"


RUNNERS: dict[str, Runner] = {
    "node_test": Runner(
        name="node_test",
        runtime="node",
        extensions=(".ts", ".mts", ".js", ".mjs", ".cjs"),
        description="Node.js built-in test runner (node --test) with TAP output; "
        "TypeScript via type stripping",
    ),
    "pytest": Runner(
        name="pytest",
        runtime="python",
        extensions=(".py",),
        description="pytest inside the python sandbox image (build with scripts/build_sandbox_images.sh)",
    ),
}


def get_runner(name: str) -> Runner:
    try:
        return RUNNERS[name]
    except KeyError as exc:
        raise RunnerValidationError(f"Runner {name!r} is not allowlisted") from exc
