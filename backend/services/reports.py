"""Evidence-backed investigation reports (JSON and Markdown)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.models import Event, Investigation, ModelCall

# Events that make up the evidence timeline: every observation, belief change and decision.
TIMELINE_EVENTS = [
    "reproduction",
    "hypotheses",
    "experiment_rejected",
    "experiment_result",
    "belief_update",
    "patch_proposed",
    "patch_apply_failed",
    "patch_empty",
    "verification",
    "decision",
    "review",
    "warning",
    "budget_exhausted",
    "completed",
]

VERDICT_TEXT = {
    "verified_fix": "Verified fix — the proposed patch passed independent verification",
    "no_verified_fix": "No verified fix — every candidate patch was rejected by the verifier",
    "inconclusive": "Inconclusive — evidence or budget was insufficient to propose a verified repair",
    "no_failure_observed": "No failure observed — the test suite passed or the target test did not fail",
}


def _hypothesis(h: Any) -> dict[str, Any]:
    return {
        "key": h.key,
        "title": h.title,
        "explanation": h.explanation,
        "status": h.status,
        "prior": h.prior,
        "confidence": round(h.confidence, 4),
        "rank": h.rank,
        "suspected_locations": h.suspected_locations,
        "supporting_evidence": h.supporting_evidence,
        "contradicting_evidence": h.contradicting_evidence,
        "history": h.history,
    }


def _experiment(e: Any) -> dict[str, Any]:
    result = e.result or {}
    test_run = result.get("test_run") or {}
    return {
        "key": e.key,
        "round": e.round,
        "designed_by": e.designed_by,
        "kind": e.kind,
        "objective": e.objective,
        "status": e.status,
        "outcome": e.outcome,
        "predictions": e.predictions,
        "evaluation": e.evaluation,
        "run": e.spec.get("run"),
        "test_name_pattern": e.spec.get("test_name_pattern"),
        "discriminating": e.spec.get("discriminating"),
        "intervention": bool(e.spec.get("source_edits")),
        "files": [f.get("path") for f in e.spec.get("files", [])],
        "execution": {
            "exit_code": result.get("exit_code"),
            "duration_ms": result.get("duration_ms"),
            "timed_out": result.get("timed_out"),
            "image": result.get("image"),
            "command": result.get("command"),
            "sandbox": result.get("sandbox"),
            "tests": {k: test_run.get(k) for k in ("total", "passed", "failed")} if test_run else None,
        },
    }


def build_report(db: Session, inv: Investigation) -> dict[str, Any]:
    hypotheses = sorted(inv.hypotheses, key=lambda h: h.rank)
    patches = list(inv.patches)
    verified = next((p for p in patches if p.status == "verified"), None)
    calls = db.query(ModelCall).filter_by(investigation_id=inv.id).all()
    decisions = (
        db.query(Event)
        .filter(
            Event.investigation_id == inv.id,
            Event.type.in_(TIMELINE_EVENTS),
        )
        .order_by(Event.id)
        .all()
    )
    report_data = inv.investigation_report or {}
    target = report_data.get("target_failure")
    return {
        "investigation": {
            "id": inv.id,
            "title": inv.title,
            "repository": inv.repository.name if inv.repository else None,
            "mode": inv.mode,
            "status": inv.status,
            "verdict": inv.verdict,
            "verdict_text": VERDICT_TEXT.get(inv.verdict or "", inv.verdict),
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "finished_at": inv.finished_at.isoformat() if inv.finished_at else None,
            "error": inv.error,
        },
        "provider": {
            "name": inv.provider,
            "model": inv.model,
            "simulated": inv.simulated,
            "note": inv.provider_note,
            "disclaimer": (
                "Model outputs in this investigation were scripted mock fixtures, not real inference. "
                "Sandbox executions and verification results are real."
                if inv.simulated
                else None
            ),
        },
        "symptom": inv.symptom,
        "target_failure": target,
        "reproduced": report_data.get("reproduction_confirmed"),
        "repository_profile": {
            k: report_data.get(k) for k in ("languages", "frameworks", "file_count", "package_manager")
        }
        | {"runtime": report_data.get("runtime")},
        "root_cause": inv.root_cause,
        "hypotheses": [_hypothesis(h) for h in hypotheses],
        "rejected_hypotheses": [_hypothesis(h) for h in hypotheses if h.status in ("refuted", "weakened")],
        "experiments": [_experiment(e) for e in inv.experiments],
        "patches": [
            {
                "key": p.key,
                "summary": p.summary,
                "rationale": p.rationale,
                "status": p.status,
                "review_status": p.review_status,
                "files_changed": p.files_changed,
                "diff": p.diff,
                "verification": {
                    k: (p.verification or {}).get(k)
                    for k in (
                        "verdict",
                        "reasons",
                        "target_baseline",
                        "target_patched",
                        "target_repeat_runs",
                        "fixed",
                        "regressions",
                        "still_failing",
                        "unchanged_passing",
                        "baseline_summary",
                        "patched_summary",
                    )
                },
            }
            for p in patches
        ],
        "proposed_fix": verified.key if verified else None,
        "decisions": [{"ts": d.ts.isoformat(), "type": d.type, "message": d.message} for d in decisions],
        "usage": inv.usage,
        "budget": inv.budget,
        "model_calls": len(calls),
        "summary": inv.summary,
    }


def render_markdown(report: dict[str, Any]) -> str:
    inv = report["investigation"]
    prov = report["provider"]
    lines = [f"# FORGE-0 Evidence Report — {inv['title']}", ""]
    lines += [
        f"- **Repository:** {inv['repository']}",
        "- **Mode:** "
        + ("System B — hypothesis-driven" if inv["mode"] == "forge" else "Baseline A — one-shot repair"),
        f"- **Verdict:** {inv['verdict_text']}",
        f"- **Provider:** {prov['name']} / {prov['model']}"
        + (" (**SIMULATED**)" if prov["simulated"] else ""),
    ]
    if prov.get("disclaimer"):
        lines += ["", f"> {prov['disclaimer']}"]
    if prov.get("note"):
        lines += ["", f"> {prov['note']}"]
    target = report.get("target_failure") or {}
    lines += ["", "## Observed failure", ""]
    if target:
        lines += [
            f"`{target.get('test_name')}` in `{target.get('file')}`",
            "",
            "```",
            str(target.get("error") or ""),
            "```",
            "",
            f"Reproduced in isolation: **{report.get('reproduced')}**",
        ]
    else:
        lines.append("No failing test observed.")
    lines += ["", "## Suspected root cause", "", report.get("root_cause") or "_Not established._"]
    lines += [
        "",
        "## Hypotheses",
        "",
        "| Key | Hypothesis | Prior | Final confidence | Status |",
        "|---|---|---|---|---|",
    ]
    for h in report["hypotheses"]:
        lines.append(
            f"| {h['key']} | {h['title']} | {h['prior']:.2f} | {h['confidence']:.2f} | {h['status']} |"
        )
    lines += ["", "## Experiments", ""]
    for e in report["experiments"]:
        lines.append(f"### {e['key']} · {e['kind']} · {str(e['outcome']).upper()}")
        lines.append("")
        lines.append(e["objective"])
        ev = e.get("evaluation") or {}
        if ev.get("detail"):
            lines.append(f"\n_Result:_ {ev['detail']}")
        for p in ev.get("predictions") or []:
            mark = "✔" if p["matched"] else "✘"
            lines.append(f"- {mark} {p['hypothesis']}: {p['reason']}")
        if ev.get("errors"):
            lines.append(f"- rejected before execution: {'; '.join(ev['errors'])}")
        ex = e["execution"]
        if ex.get("command"):
            lines.append(
                f"\n`{' '.join(ex['command'])}` — exit {ex.get('exit_code')}, {ex.get('duration_ms')} ms"
            )
        lines.append("")
    lines += ["## Candidate patches", ""]
    for p in report["patches"]:
        v = p["verification"] or {}
        lines += [f"### {p['key']} — {p['summary']} ({p['status']})", "", p["rationale"], ""]
        if v.get("reasons"):
            lines += [f"**Verifier:** {v.get('verdict')} — " + "; ".join(v["reasons"]), ""]
        if v.get("regressions"):
            lines += ["Regressions:", *[f"- {r}" for r in v["regressions"]], ""]
        if p["diff"]:
            lines += ["```diff", p["diff"].rstrip(), "```", ""]
    if report.get("decisions"):
        lines += ["## Evidence timeline", ""]
        for d in report["decisions"]:
            lines.append(f"- `{d['ts'][11:19]}` **{d['type']}** {d['message']}")
        lines.append("")
    usage = report.get("usage") or {}
    lines += [
        "## Budget and usage",
        "",
        f"- Model calls: {usage.get('model_calls')}",
        f"- Experiments: {usage.get('experiments')} · sandbox runs: {usage.get('sandbox_runs')}",
        f"- Tokens: {usage.get('total_tokens')}" + (" (estimated)" if usage.get("tokens_estimated") else ""),
        f"- Estimated cost (USD, list price): {usage.get('estimated_cost_usd')}"
        + (" — hypothetical, mock mode made no API calls" if prov["simulated"] else ""),
        f"- Elapsed: {usage.get('elapsed_s')} s",
        "",
        "## Human review",
        "",
        "FORGE-0 never applies patches to the source repository. "
        "A verified patch is a proposal for human review.",
    ]
    return "\n".join(lines) + "\n"
