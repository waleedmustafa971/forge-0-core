# ruff: noqa: E501  (embedded HTML/CSS report template and command examples)
"""FORGE-0 evaluation harness: Baseline A (one-shot repair) vs System B (FORGE-0).

For every demo defect it runs both systems end to end, then performs an *independent*
evaluation of whatever patch each system claims fixes the defect: the patch is applied to a
fresh copy, the defect's hidden tests (never shown to either system) are added, and the full
suite is executed in the sandbox.

Usage (from the repository root; use backend/.venv/bin/python on Linux/macOS):

    backend/.venv/Scripts/python benchmarks/run_benchmark.py                       # mock (default config)
    backend/.venv/Scripts/python benchmarks/run_benchmark.py --config benchmarks/configs/muse-spark-1.3.json --dry-run
    backend/.venv/Scripts/python benchmarks/run_benchmark.py --config benchmarks/configs/muse-spark-1.3.json --yes

Real-provider configs refuse to run on the mock fallback, show a worst-case cost estimate and
require --yes before spending tokens. --dry-run checks configuration, sandbox and provider
connectivity (GET /models, no tokens) and exits.

Results are written to benchmarks/results/<run_id>.json and .html. Nothing is estimated or
filled in: a metric that was not measured is recorded as null.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
DEFAULT_CONFIG = ROOT / "benchmarks" / "configs" / "mock.json"

DISCLAIMER_MOCK = (
    "MOCK-ONLY EVALUATION. Model outputs were scripted fixtures authored for this demo: Baseline A "
    "receives the scripted 'first idea' patch, System B receives scripted hypotheses, experiments and "
    "patches. Sandbox executions, verification and hidden-test evaluation are real, but the comparison "
    "reflects how the fixtures were authored, not model capability. Re-run with a real-provider config "
    "for a real evaluation."
)
DISCLAIMER_REAL = (
    "Real-model evaluation: every model output came from the configured provider; all executions, "
    "verifications and hidden-test evaluations were run in the sandbox. Small sample (5 defects) - treat "
    "rates as indicative, not statistically significant."
)

# Worst-case prompt size per model request (observed FORGE-0 prompts are ~6-8k tokens).
PROMPT_TOKENS_UPPER_BOUND = 10_000
# Each model call may take one schema-repair round (a second request).
REQUESTS_PER_CALL_UPPER_BOUND = 2

CONFIG_ENV = {
    "provider": "AI_PROVIDER",
    "model": None,  # mapped per provider below
    "reasoning_effort": "META_REASONING_EFFORT",
    "structured_output": "META_STRUCTURED_OUTPUT",
    "max_tokens": "AI_MAX_TOKENS",
    "temperature": "AI_TEMPERATURE",
}
BUDGET_ENV = {
    "max_model_calls": "MAX_MODEL_CALLS",
    "max_experiments": "MAX_EXPERIMENTS",
    "max_repair_attempts": "MAX_REPAIR_ATTEMPTS",
    "max_experiment_rounds": "MAX_EXPERIMENT_ROUNDS",
    "time_budget_s": "INVESTIGATION_TIME_BUDGET_S",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="benchmark config (JSON)")
    parser.add_argument(
        "--provider", choices=["mock", "meta", "openai"], default=None, help="override config"
    )
    parser.add_argument("--defects", default="", help="comma-separated defect ids (overrides config)")
    parser.add_argument("--systems", default="", help="comma-separated systems (overrides config)")
    parser.add_argument(
        "--repeats", type=int, default=None, help="runs per defect and system (overrides config)"
    )
    parser.add_argument("--dry-run", action="store_true", help="validate setup and connectivity only")
    parser.add_argument("--yes", action="store_true", help="confirm a run that spends real API tokens")
    parser.add_argument(
        "--use-configured-db",
        action="store_true",
        help="record investigations in DATABASE_URL (visible in the dashboard) instead of a temporary SQLite DB",
    )
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> dict[str, Any]:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.provider:
        config["provider"] = args.provider
    if args.defects:
        config["defects"] = [d.strip() for d in args.defects.split(",") if d.strip()]
    if args.systems:
        config["systems"] = [s.strip() for s in args.systems.split(",") if s.strip()]
    if args.repeats is not None:
        config["repeats"] = args.repeats
    config.setdefault("name", args.config.stem)
    config.setdefault("provider", "mock")
    config.setdefault("systems", ["baseline", "forge"])
    config.setdefault("defects", [])
    config.setdefault("repeats", 1)
    config.setdefault("budgets", {})
    config.setdefault("require_real_provider", config["provider"] != "mock")
    unknown_systems = set(config["systems"]) - {"baseline", "forge"}
    if unknown_systems or config["repeats"] < 1:
        raise SystemExit(f"Invalid config: systems {sorted(unknown_systems)} / repeats {config['repeats']}")
    return config


def configure_environment(args: argparse.Namespace, config: dict[str, Any], workdir: Path) -> None:
    """Translates the config into the backend's environment variables (before importing it)."""
    if not args.use_configured_db:
        os.environ["DATABASE_URL"] = f"sqlite:///{(workdir / 'benchmark.db').as_posix()}"
        os.environ["DATA_DIR"] = str(workdir / "data")
    os.environ["AI_PROVIDER"] = config["provider"]
    if config.get("model"):
        os.environ["META_MODEL" if config["provider"] == "meta" else "OPENAI_COMPAT_MODEL"] = str(
            config["model"]
        )
    for key, env in CONFIG_ENV.items():
        if env and key != "provider" and config.get(key) not in (None, ""):
            os.environ[env] = str(config[key])
    for key, value in config["budgets"].items():
        if key in BUDGET_ENV:
            os.environ[BUDGET_ENV[key]] = str(value)
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ.setdefault("LOG_FORMAT", "text")


def worst_case_cost(config: dict[str, Any], defects: int, runtime: Any, settings: Any) -> dict[str, Any]:
    calls_per_system = {"baseline": 1, "forge": runtime.max_model_calls}
    calls = sum(calls_per_system[s] for s in config["systems"]) * defects * config["repeats"]
    requests = calls * REQUESTS_PER_CALL_UPPER_BOUND
    input_tokens = requests * PROMPT_TOKENS_UPPER_BOUND
    output_tokens = requests * runtime.max_tokens
    usd = (
        input_tokens / 1e6 * settings.ai_price_input_per_m
        + output_tokens / 1e6 * settings.ai_price_output_per_m
    )
    return {
        "model_calls": calls,
        "requests": requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usd": round(usd, 2),
        "assumptions": f"every call hits the model-call budget, uses a schema-repair round, sends "
        f"{PROMPT_TOKENS_UPPER_BOUND:,} prompt tokens and fills max_completion_tokens; no cache discount",
    }


def main() -> int:
    args = parse_args()
    config = load_config(args)
    workdir = Path(tempfile.mkdtemp(prefix="forge0-bench-"))
    configure_environment(args, config, workdir)

    from agents.orchestrator import Orchestrator
    from core.config import get_settings
    from core.database import init_db, session_scope
    from core.logging import configure_logging
    from core.models import Investigation, Patch
    from core.schemas import SourceEdit
    from providers.registry import build_provider
    from sandbox.docker import WslKeepAlive, get_sandbox
    from sandbox.tap import find_test
    from services.repositories import import_local
    from services.settings_service import get_runtime_config
    from services.workspace import EditError, apply_edits

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    defects_dir = ROOT / "demo" / "defects"
    wanted = set(config["defects"])
    defects = [
        json.loads((d / "defect.json").read_text(encoding="utf-8"))
        for d in sorted(defects_dir.iterdir())
        if d.is_dir() and (not wanted or d.name in wanted)
    ]
    missing = wanted - {d["id"] for d in defects}
    if missing:
        print(f"Unknown defects in config: {sorted(missing)}", file=sys.stderr)
        return 2
    systems: list[str] = config["systems"]

    keepalive = WslKeepAlive(get_sandbox().docker)
    keepalive.start()
    try:
        init_db()
        with session_scope() as db:
            runtime = get_runtime_config(db)
        selection = build_provider(runtime)
        provider = selection.provider
        print(f"config: {config['name']} ({args.config})")
        print(
            f"provider: requested {config['provider']} -> active {provider.name}/{provider.model}"
            f"{' (SIMULATED)' if provider.simulated else ''}"
        )
        print(
            f"defects: {len(defects)} x systems {systems} x repeats {config['repeats']}; budgets: "
            f"{runtime.max_model_calls} model calls, {runtime.max_experiments} experiments, "
            f"{runtime.max_repair_attempts} repair attempts, max_tokens {runtime.max_tokens}"
        )
        if config["require_real_provider"] and provider.simulated:
            print(
                "ABORTED: this config requires a real provider but the backend fell back to the mock "
                f"provider ({selection.fallback_reason}). Configure the API key; mock results must "
                "never be reported as a real-model evaluation.",
                file=sys.stderr,
            )
            return 3

        status = get_sandbox().status(refresh=True)
        print(f"sandbox: {'ok' if status.available else 'UNAVAILABLE'} ({status.detail})")
        if not status.available:
            return 2

        estimate = None
        if not provider.simulated:
            check = provider.check(deep=False)
            print(f"connectivity (GET /models, no tokens): {json.dumps(check)}")
            if not check.get("ok"):
                return 3
            estimate = worst_case_cost(config, len(defects), runtime, settings)
            print(
                f"worst-case cost: ${estimate['usd']} ({estimate['requests']} requests; {estimate['assumptions']})"
            )
            cap = config.get("max_estimated_cost_usd")
            if cap is not None and estimate["usd"] > cap:
                print(f"ABORTED: worst-case estimate exceeds max_estimated_cost_usd={cap}", file=sys.stderr)
                return 4
        if args.dry_run:
            print("dry run: configuration valid, nothing executed")
            return 0
        if not provider.simulated and not args.yes:
            print("This run spends real API tokens. Re-run with --yes to confirm.", file=sys.stderr)
            return 4

        with session_scope() as db:
            repo = import_local(
                db, str(settings.demo_repo_path), name="order-management (benchmark)", source_type="local"
            )
            repo_id, snapshot = repo.id, Path(repo.snapshot_path)

        def evaluate(defect: dict[str, Any], edits: list[dict[str, Any]]) -> dict[str, Any]:
            """Independent evaluation on a fresh copy, including hidden tests."""
            target = f"{defect['failing_test']['name']}"
            copy = workdir / f"eval-{defect['id']}-{time.monotonic_ns()}"
            shutil.copytree(snapshot, copy)
            try:
                baseline_run = get_sandbox().run_tests(copy, "node_test", ["test/**/*.test.ts"])
                try:
                    apply_edits(
                        copy, [SourceEdit(**e) for e in edits], allow_test_files=False, allow_create=True
                    )
                except EditError as exc:
                    return {"applied": False, "error": str(exc), "actually_fixed": False, "regressions": 0}
                hidden_src = ROOT / defect["hidden_tests"]
                (copy / "test" / "hidden").mkdir(parents=True, exist_ok=True)
                shutil.copy(hidden_src, copy / "test" / "hidden" / hidden_src.name)
                run = get_sandbox().run_tests(copy, "node_test", ["test/**/*.test.ts"])
                if run.infra_error or not run.test_run:
                    return {
                        "applied": True,
                        "error": run.infra_error or "no test report",
                        "actually_fixed": False,
                    }
                before = (
                    {t.name: t.status for t in baseline_run.test_run.tests} if baseline_run.test_run else {}
                )
                after = {t.name: t.status for t in run.test_run.tests}
                regressions = [n for n, s in before.items() if s == "passed" and after.get(n) != "passed"]
                # node's TAP only reports `location` for failures, so hidden tests are matched by name
                # prefix; a hidden file that fails to load shows up as a failing test named after the file.
                hidden = [
                    t
                    for t in run.test_run.tests
                    if t.name.startswith("[hidden]") or (t.file or t.name).startswith("test/hidden/")
                ]
                hidden_ok = bool(hidden) and all(t.status == "passed" for t in hidden)
                target_result = find_test(run.test_run, target)
                target_ok = target_result is not None and target_result.status == "passed"
                return {
                    "applied": True,
                    "target_passed": target_ok,
                    "hidden_tests": len(hidden),
                    "hidden_tests_passed": hidden_ok,
                    "regressions": len(regressions),
                    "regression_names": regressions,
                    "actually_fixed": target_ok and hidden_ok and not regressions,
                }
            finally:
                shutil.rmtree(copy, ignore_errors=True)

        scenarios = []
        for repeat in range(1, config["repeats"] + 1):
            for defect in defects:
                target_name = defect["failing_test"]["name"]
                entry: dict[str, Any] = {
                    "defect": defect["id"],
                    "title": defect["title"],
                    "category": defect["category"],
                    "target_test": target_name,
                    "repeat": repeat,
                    "systems": {},
                }
                for system in systems:
                    label = f"[{defect['id']} #{repeat}] {system}"
                    print(f"{label} running ...", flush=True)
                    started = time.monotonic()
                    with session_scope() as db:
                        inv = Investigation(
                            repository_id=repo_id,
                            title=f"[benchmark {config['name']}] {defect['id']} #{repeat} - {system}",
                            target_test=target_name,
                            mode=system,
                            usage={},
                            budget={},
                        )
                        db.add(inv)
                        db.flush()
                        inv_id = inv.id
                    Orchestrator(inv_id).run()
                    duration = time.monotonic() - started
                    with session_scope() as db:
                        inv = db.get(Investigation, inv_id)
                        patches = (
                            db.query(Patch)
                            .filter_by(investigation_id=inv_id)
                            .order_by(Patch.created_at)
                            .all()
                        )
                        summary = inv.summary or {}
                        usage = inv.usage or {}
                        report = inv.investigation_report or {}
                        if system == "baseline":
                            claimed = next((p for p in patches if p.edits), None)
                        else:
                            claimed = next((p for p in patches if p.status == "verified"), None)
                        claimed_edits = list(claimed.edits) if claimed else []
                        verifier_verdict = (claimed.verification or {}).get("verdict") if claimed else None
                        metrics: dict[str, Any] = {
                            "investigation_id": inv_id,
                            "status": inv.status,
                            "verdict": inv.verdict,
                            "error": inv.error,
                            "reproduced": report.get("reproduction_confirmed"),
                            "claimed_fixed": bool(claimed),
                            "verifier_verdict": verifier_verdict,
                            "experiments": int(usage.get("experiments", 0)),
                            "patch_attempts": len(patches),
                            "duration_s": round(duration, 2),
                            "model_calls": int(usage.get("model_calls", 0)),
                            "failed_model_calls": int(usage.get("failed_model_calls", 0)),
                            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                            "completion_tokens": int(usage.get("completion_tokens", 0)),
                            "cached_tokens": int(usage.get("cached_tokens", 0)),
                            "reasoning_tokens": int(usage.get("reasoning_tokens", 0)),
                            "total_tokens": int(usage.get("total_tokens", 0)),
                            "tokens_estimated": bool(usage.get("tokens_estimated", False)),
                            "estimated_cost_usd": float(usage.get("estimated_cost_usd", 0.0)),
                            "simulated": inv.simulated,
                            "provider": inv.provider,
                            "model": inv.model,
                            "message": summary.get("message"),
                        }
                    if config["require_real_provider"] and metrics["simulated"]:
                        print(
                            "ABORTED: an investigation ran on simulated output during a real run",
                            file=sys.stderr,
                        )
                        return 3
                    if claimed_edits:
                        evaluation = evaluate(defect, claimed_edits)
                    else:
                        evaluation = {"applied": False, "actually_fixed": False, "regressions": 0}
                    metrics["evaluation"] = evaluation
                    metrics["hidden_tests_passed"] = (
                        evaluation.get("hidden_tests_passed") if claimed_edits else None
                    )
                    metrics["actually_fixed"] = bool(evaluation.get("actually_fixed"))
                    metrics["regressions"] = int(evaluation.get("regressions") or 0)
                    metrics["false_positive"] = metrics["claimed_fixed"] and not metrics["actually_fixed"]
                    entry["systems"][system] = metrics
                    print(
                        f"{label}: verdict={metrics['verdict']} claimed={metrics['claimed_fixed']} "
                        f"actually_fixed={metrics['actually_fixed']} experiments={metrics['experiments']} "
                        f"tokens={metrics['total_tokens']} time={metrics['duration_s']}s",
                        flush=True,
                    )
                scenarios.append(entry)

        def aggregate(system: str) -> dict[str, Any]:
            rows = [s["systems"][system] for s in scenarios if system in s["systems"]]
            n = len(rows) or 1
            claimed = [r for r in rows if r["claimed_fixed"]]
            return {
                "scenarios": len(rows),
                "reproduction_rate": round(sum(1 for r in rows if r["reproduced"]) / n, 4),
                "verified_repair_rate": round(sum(1 for r in rows if r["actually_fixed"]) / n, 4),
                "claimed_fixes": len(claimed),
                "false_positives": sum(1 for r in rows if r["false_positive"]),
                "false_positive_rate": round(sum(1 for r in claimed if r["false_positive"]) / len(claimed), 4)
                if claimed
                else 0.0,
                "regression_failures": sum(1 for r in claimed if r["regressions"] > 0),
                "mean_experiments": round(sum(r["experiments"] for r in rows) / n, 2),
                "total_duration_s": round(sum(r["duration_s"] for r in rows), 2),
                "total_model_calls": sum(r["model_calls"] for r in rows),
                "failed_model_calls": sum(r["failed_model_calls"] for r in rows),
                "total_tokens": sum(r["total_tokens"] for r in rows),
                "cached_tokens": sum(r["cached_tokens"] for r in rows),
                "reasoning_tokens": sum(r["reasoning_tokens"] for r in rows),
                "tokens_estimated": any(r["tokens_estimated"] for r in rows),
                "estimated_cost_usd": round(sum(r["estimated_cost_usd"] for r in rows), 6),
            }

        def per_defect(system: str) -> dict[str, dict[str, int]]:
            out: dict[str, dict[str, int]] = {}
            for s in scenarios:
                m = s["systems"].get(system)
                if m is None:
                    continue
                row = out.setdefault(s["defect"], {"runs": 0, "fixed": 0, "false_positives": 0})
                row["runs"] += 1
                row["fixed"] += int(m["actually_fixed"])
                row["false_positives"] += int(m["false_positive"])
            return out

        simulated = any(m["simulated"] for s in scenarios for m in s["systems"].values())
        provider_name = next((m["provider"] for s in scenarios for m in s["systems"].values()), provider.name)
        model = next((m["model"] for s in scenarios for m in s["systems"].values()), provider.model)
        run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + f"-{provider_name}"
        result = {
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "config": {k: v for k, v in config.items() if k != "notes"},
            "provider": provider_name,
            "model": model,
            "simulated": simulated,
            "disclaimer": DISCLAIMER_MOCK if simulated else DISCLAIMER_REAL,
            "repeats": config["repeats"],
            "sandbox": {"docker": " ".join(status.docker_command), "server_version": status.server_version},
            "pricing_usd_per_million": {
                "input": settings.ai_price_input_per_m,
                "cached_input": settings.ai_price_cached_input_per_m,
                "output": settings.ai_price_output_per_m,
                "note": "Muse Spark 1.3 standard-mode list price; for mock runs the cost is hypothetical",
            },
            "worst_case_estimate": estimate,
            "metric_definitions": {
                "reproduction_rate": "Share of runs whose target test failed again when re-run in isolation",
                "verified_repair_rate": "Share of runs whose claimed patch passes the target test, the hidden "
                "tests and every previously passing test on a fresh copy (independent evaluation)",
                "false_positive_rate": "Claimed fixes that the independent evaluation shows are not fixes, "
                "divided by claimed fixes",
                "regression_failures": "Claimed fixes that break at least one previously passing test",
                "claimed_fixed": "Baseline A always claims its one-shot patch; System B claims only "
                "verifier-approved patches",
            },
            "scenarios": scenarios,
            "aggregate": {system: aggregate(system) for system in systems},
            "per_defect": {system: per_defect(system) for system in systems},
        }
        out_dir = ROOT / "benchmarks" / "results"
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{run_id}.json"
        html_path = out_dir / f"{run_id}.html"
        for path, content in (
            (json_path, json.dumps(result, indent=2) + "\n"),
            (html_path, render_html(result)),
        ):
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        print(f"\nWrote {json_path.relative_to(ROOT)} and {html_path.relative_to(ROOT)}")
        for system, agg in result["aggregate"].items():
            print(f"  {system:9s} {json.dumps(agg)}")
        return 0
    finally:
        keepalive.stop()
        shutil.rmtree(workdir, ignore_errors=True)


def render_html(result: dict[str, Any]) -> str:
    agg = result["aggregate"]
    names = {"baseline": "Baseline A · one-shot", "forge": "System B · FORGE-0"}
    colors = {"baseline": "#8a929d", "forge": "#e8a33d"}

    def bars(label: str, key: str, fmt, maximum: float | None = None) -> str:
        values = {s: float(agg[s][key]) for s in agg}
        top = maximum or max(values.values()) or 1.0
        rows = "".join(
            f'<div class="row"><span>{names.get(s, s)}</span><div class="track"><div class="fill" '
            f'style="width:{min(100, v / top * 100):.1f}%;background:{colors.get(s, "#6ea8e6")}"></div></div>'
            f"<code>{fmt(v)}</code></div>"
            for s, v in values.items()
        )
        return f'<div class="metric"><div class="label">{html.escape(label)}</div>{rows}</div>'

    pct = lambda v: f"{v * 100:.0f}%"  # noqa: E731
    mark = lambda v: "—" if v is None else ("✔" if v else "✘")  # noqa: E731
    repeats = result.get("repeats", 1)
    rows = []
    for s in result["scenarios"]:
        run = f" #{s.get('repeat', 1)}" if repeats > 1 else ""
        for sys_, m in s["systems"].items():
            outcome = (
                "fixed" if m["actually_fixed"] else ("false positive" if m["false_positive"] else "not fixed")
            )
            css = "ok" if m["actually_fixed"] else ("bad" if m["false_positive"] else "")
            rows.append(
                f"<tr><td><code>{html.escape(s['defect'])}</code>{run}<br><small>{html.escape(s['title'])}</small></td>"
                f"<td>{names.get(sys_, sys_)}</td><td>{mark(m['reproduced'])}</td><td>{mark(m['claimed_fixed'])}</td>"
                f"<td>{html.escape(str(m['verifier_verdict'] or '—'))}</td><td>{mark(m['hidden_tests_passed'])}</td>"
                f"<td class='{css}'>{outcome}</td><td>{m['experiments']}</td><td>{m['patch_attempts']}</td>"
                f"<td>{m['duration_s']:.1f}s</td></tr>"
            )
    table = "".join(rows)
    tone = "#3a2a10" if result["simulated"] else "#132235"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FORGE-0 Evaluation {html.escape(result["run_id"])}</title>
<style>
:root{{--bg:#0c0e11;--card:#12151a;--border:#242a32;--text:#e4e7eb;--muted:#8a929d}}
@media (prefers-color-scheme: light){{:root{{--bg:#f6f7f9;--card:#fff;--border:#e1e4e8;--text:#16191d;--muted:#5b6470}}}}
body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 Inter,system-ui,sans-serif;padding:24px 16px}}
main{{max-width:1100px;margin:0 auto}} h1{{font-size:20px;margin:0 0 4px}} .muted{{color:var(--muted)}}
.note{{background:{tone};border:1px solid #e8a33d55;border-radius:8px;padding:10px 14px;margin:16px 0;color:#f3e3c4}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px}}
.metric{{margin-bottom:14px}} .label{{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin-bottom:6px}}
.row{{display:grid;grid-template-columns:170px 1fr 70px;gap:10px;align-items:center;margin:4px 0}}
.track{{height:10px;background:var(--border);border-radius:3px;overflow:hidden}} .fill{{height:100%}}
table{{width:100%;border-collapse:collapse;margin-top:16px}} th,td{{text-align:left;padding:8px;border-bottom:1px solid var(--border);vertical-align:top}}
th{{font-size:11px;text-transform:uppercase;color:var(--muted)}} .ok{{color:#4fb38b}} .bad{{color:#e5675f}}
.wrap{{overflow-x:auto}} code{{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px}}
</style></head><body><main>
<h1>FORGE-0 evaluation</h1>
<div class="muted">run <code>{html.escape(result["run_id"])}</code> · provider {html.escape(result["provider"])}/{html.escape(result["model"])} · {len(result["scenarios"])} defect runs</div>
<div class="note">{html.escape(result["disclaimer"])}</div>
<div class="grid"><div class="card">
{bars("Verified repair rate (hidden-test confirmed)", "verified_repair_rate", pct, 1)}
{bars("Reproduction rate", "reproduction_rate", pct, 1)}
{bars("False-positive repair rate", "false_positive_rate", pct, 1)}
{bars("Claimed fixes with regressions", "regression_failures", lambda v: f"{v:.0f}")}
</div><div class="card">
{bars("Mean experiments per defect", "mean_experiments", lambda v: f"{v:.1f}")}
{bars("Total wall time (s)", "total_duration_s", lambda v: f"{v:.0f}")}
{bars("Total tokens" + (" (estimated)" if result["simulated"] else ""), "total_tokens", lambda v: f"{v:,.0f}")}
{bars("Estimated API cost (USD" + (", hypothetical" if result["simulated"] else "") + ")", "estimated_cost_usd", lambda v: f"${v:.4f}")}
</div></div>
<div class="card wrap"><table><thead><tr><th>Defect</th><th>System</th><th>Reproduced</th><th>Claimed</th><th>Verifier</th>
<th>Hidden tests</th><th>Outcome</th><th>Experiments</th><th>Patches</th><th>Time</th></tr></thead><tbody>{table}</tbody></table></div>
</main></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
