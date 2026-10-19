"""Parser for the TAP 13 stream emitted by ``node --test --test-reporter=tap``."""

from __future__ import annotations

import re

from core.schemas import TestCaseResult, TestRunSummary

_SUBTEST = re.compile(r"^(?P<indent>\s*)# Subtest: (?P<name>.*)$")
_RESULT = re.compile(
    r"^(?P<indent>\s*)(?P<not>not )?ok (?P<num>\d+)(?: - (?P<name>.*?))?"
    r"(?: # (?P<directive>SKIP|TODO)\b.*)?$",
    re.IGNORECASE,
)
_YAML_KEY = re.compile(r"^(?P<key>[A-Za-z_]+):\s?(?P<value>.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("\\\\", "\\").replace("''", "'") if value[0] == "'" else inner
    return value


def _parse_yaml_block(lines: list[str]) -> dict[str, str]:
    """Parses the flat YAML diagnostics node emits (scalars and `|-` blocks)."""
    data: dict[str, str] = {}
    i = 0
    base = len(lines[0]) - len(lines[0].lstrip()) if lines else 0
    while i < len(lines):
        line = lines[i]
        stripped = line[base:] if len(line) >= base else line.lstrip()
        match = _YAML_KEY.match(stripped)
        if not match or line[:base].strip():
            i += 1
            continue
        key, value = match.group("key"), match.group("value")
        if value in ("|-", "|", ">-", ">"):
            block: list[str] = []
            i += 1
            while i < len(lines) and (len(lines[i]) - len(lines[i].lstrip()) > base or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            data[key] = "\n".join(block).strip()
            continue
        if value.startswith("'") and not (len(value) > 1 and value.endswith("'")):
            # multi-line single-quoted scalar
            parts = [value]
            i += 1
            while i < len(lines):
                parts.append(lines[i].strip())
                if lines[i].rstrip().endswith("'"):
                    break
                i += 1
            value = " ".join(parts)
        data[key] = _unquote(value)
        i += 1
    return data


def _file_from_location(location: str | None) -> str | None:
    if not location:
        return None
    loc = location.replace("\\\\", "/").replace("\\", "/")
    loc = re.sub(r":\d+:\d+$", "", loc)
    for marker in ("/work/",):
        if marker in loc:
            return loc.split(marker, 1)[1]
    return loc


def parse_tap(output: str) -> TestRunSummary:
    lines = output.splitlines()
    names_by_level: dict[int, str] = {}
    results: list[TestCaseResult] = []
    saw_plan_or_result = False
    i = 0
    while i < len(lines):
        line = lines[i]
        sub = _SUBTEST.match(line)
        if sub:
            level = len(sub.group("indent")) // 4
            names_by_level[level] = sub.group("name").strip()
            for deeper in [k for k in names_by_level if k > level]:
                del names_by_level[deeper]
            i += 1
            continue
        res = _RESULT.match(line)
        if not res:
            if re.match(r"^\s*1\.\.\d+", line):
                saw_plan_or_result = True
            i += 1
            continue
        saw_plan_or_result = True
        level = len(res.group("indent")) // 4
        name = (res.group("name") or names_by_level.get(level) or f"test {res.group('num')}").strip()
        diag: dict[str, str] = {}
        if i + 1 < len(lines) and lines[i + 1].strip() == "---":
            j = i + 2
            block: list[str] = []
            while j < len(lines) and lines[j].strip() != "...":
                block.append(lines[j])
                j += 1
            diag = _parse_yaml_block(block)
            i = j + 1
        else:
            i += 1
        if diag.get("type") == "suite":
            continue
        directive = (res.group("directive") or "").upper()
        if directive == "SKIP":
            status = "skipped"
        elif directive == "TODO":
            status = "todo"
        else:
            status = "failed" if res.group("not") else "passed"
        parents = [names_by_level[k] for k in sorted(names_by_level) if k < level]
        full_name = " > ".join([*parents, name])
        duration = diag.get("duration_ms")
        results.append(
            TestCaseResult(
                name=full_name,
                file=_file_from_location(diag.get("location")),
                status=status,  # type: ignore[arg-type]
                duration_ms=float(duration) if duration and re.match(r"^[\d.]+$", duration) else None,
                failure_type=diag.get("failureType"),
                error=diag.get("error"),
                error_name=diag.get("name"),
                error_code=diag.get("code"),
                stack=diag.get("stack"),
                location=diag.get("location"),
            )
        )
    summary = TestRunSummary(tests=results, parse_ok=saw_plan_or_result)
    summary.total = len(results)
    summary.passed = sum(1 for r in results if r.status == "passed")
    summary.failed = sum(1 for r in results if r.status == "failed")
    summary.skipped = sum(1 for r in results if r.status in ("skipped", "todo"))
    return summary


def leaf_name(full_name: str) -> str:
    return full_name.split(" > ")[-1]


def find_test(summary: TestRunSummary, name: str) -> TestCaseResult | None:
    """Finds a test by its full name, or by its leaf name when unambiguous."""
    for test in summary.tests:
        if test.name == name:
            return test
    matches = [t for t in summary.tests if leaf_name(t.name) == leaf_name(name)]
    return matches[0] if len(matches) == 1 else None
