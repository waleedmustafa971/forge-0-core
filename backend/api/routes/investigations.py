from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from agents.base import InvestigationContext, build_budget, dump
from agents.orchestrator import Orchestrator
from agents.verifier import IndependentVerifier
from api.deps import get_db, require_auth
from api.schemas import (
    EventOut,
    ExperimentOut,
    HypothesisOut,
    InvestigationCreate,
    InvestigationDetail,
    InvestigationOut,
    PatchOut,
    PatchReview,
    VerifyRequest,
)
from core.database import session_scope
from core.models import Event, Experiment, Hypothesis, Investigation, Patch, Repository
from core.schemas import InvestigationReport, SourceEdit
from providers.mock import MockProvider
from sandbox.docker import get_sandbox
from services.jobs import get_runner
from services.reports import build_report, render_markdown
from services.settings_service import get_runtime_config
from services.workspace import WorkspaceManager

router = APIRouter(
    prefix="/api/investigations", tags=["investigations"], dependencies=[Depends(require_auth)]
)
TERMINAL = {"completed", "failed", "cancelled"}


def _get(db: Session, inv_id: str) -> Investigation:
    inv = db.get(Investigation, inv_id)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation not found")
    return inv


def start_investigation(inv_id: str) -> None:
    get_runner().submit(inv_id, Orchestrator(inv_id).run)


@router.post("", response_model=InvestigationOut, status_code=status.HTTP_202_ACCEPTED)
def create_investigation(body: InvestigationCreate, db: Session = Depends(get_db)) -> Investigation:
    repo = db.get(Repository, body.repository_id)
    if repo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found")
    title = body.title or (
        f"{repo.name}: {body.target_test.split(' > ')[-1]}"
        if body.target_test
        else f"{repo.name}: failing tests"
    )
    inv = Investigation(
        repository_id=repo.id,
        title=title[:300],
        symptom=body.symptom,
        target_test=body.target_test,
        mode=body.mode,
        status="queued",
        phase="queued",
        usage={},
        budget={},
    )
    db.add(inv)
    db.flush()
    db.add(
        Event(
            investigation_id=inv.id,
            agent="orchestrator",
            type="queued",
            message="Investigation queued",
            data={},
        )
    )
    db.commit()
    start_investigation(inv.id)
    return inv


@router.get("", response_model=list[InvestigationOut])
def list_investigations(
    status_filter: str | None = Query(default=None, alias="status"),
    repository_id: str | None = None,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
) -> list[Investigation]:
    q = db.query(Investigation)
    if status_filter:
        q = q.filter(Investigation.status == status_filter)
    if repository_id:
        q = q.filter(Investigation.repository_id == repository_id)
    return q.order_by(Investigation.created_at.desc()).limit(limit).all()


@router.get("/{inv_id}", response_model=InvestigationDetail)
def get_investigation(inv_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    inv = _get(db, inv_id)
    data = InvestigationOut.model_validate(inv).model_dump()
    data["investigation_report"] = inv.investigation_report
    data["repository_name"] = inv.repository.name if inv.repository else None
    data["counts"] = {
        "hypotheses": len(inv.hypotheses),
        "experiments": len(inv.experiments),
        "patches": len(inv.patches),
        "events": db.query(Event).filter_by(investigation_id=inv.id).count(),
    }
    return data


@router.delete("/{inv_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investigation(inv_id: str, db: Session = Depends(get_db)) -> None:
    inv = _get(db, inv_id)
    if inv.status not in TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cancel the investigation before deleting it")
    db.delete(inv)


@router.post("/{inv_id}/cancel", response_model=InvestigationOut)
def cancel_investigation(inv_id: str, db: Session = Depends(get_db)) -> Investigation:
    inv = _get(db, inv_id)
    if inv.status in TERMINAL:
        return inv
    inv.status = "cancelling"
    db.add(
        Event(
            investigation_id=inv.id,
            agent="orchestrator",
            type="cancel_requested",
            message="Cancellation requested",
            data={},
        )
    )
    return inv


@router.get("/{inv_id}/events", response_model=list[EventOut])
def list_events(
    inv_id: str, after: int = 0, limit: int = Query(default=1000, le=5000), db: Session = Depends(get_db)
) -> list[Event]:
    _get(db, inv_id)
    return (
        db.query(Event)
        .filter(Event.investigation_id == inv_id, Event.id > after)
        .order_by(Event.id)
        .limit(limit)
        .all()
    )


def _fetch_events(inv_id: str, after: int) -> tuple[list[dict[str, Any]], str | None]:
    with session_scope() as db:
        rows = (
            db.query(Event)
            .filter(Event.investigation_id == inv_id, Event.id > after)
            .order_by(Event.id)
            .limit(500)
            .all()
        )
        inv = db.get(Investigation, inv_id)
        return [EventOut.model_validate(r).model_dump(mode="json") for r in rows], inv.status if inv else None


@router.get("/{inv_id}/events/stream")
async def stream_events(
    inv_id: str,
    request: Request,
    after: int = 0,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    """Server-Sent Events stream of the investigation audit trail."""
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    _events, status_now = await asyncio.to_thread(_fetch_events, inv_id, 0 if cursor < 0 else cursor)
    if status_now is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation not found")

    async def generator() -> AsyncIterator[str]:
        nonlocal cursor
        idle = 0.0
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                return
            events, inv_status = await asyncio.to_thread(_fetch_events, inv_id, cursor)
            for event in events:
                cursor = event["id"]
                yield f"id: {cursor}\nevent: forge\ndata: {json.dumps(event)}\n\n"
            if events:
                idle = 0.0
            if inv_status in TERMINAL and not events:
                yield f"event: end\ndata: {json.dumps({'status': inv_status})}\n\n"
                return
            await asyncio.sleep(0.5)
            idle += 0.5
            if idle >= 15:
                idle = 0.0
                yield ": keep-alive\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{inv_id}/hypotheses", response_model=list[HypothesisOut])
def list_hypotheses(inv_id: str, db: Session = Depends(get_db)) -> list[Hypothesis]:
    _get(db, inv_id)
    return db.query(Hypothesis).filter_by(investigation_id=inv_id).order_by(Hypothesis.rank).all()


@router.get("/{inv_id}/experiments", response_model=list[ExperimentOut])
def list_experiments(inv_id: str, db: Session = Depends(get_db)) -> list[Experiment]:
    _get(db, inv_id)
    return db.query(Experiment).filter_by(investigation_id=inv_id).order_by(Experiment.created_at).all()


@router.get("/{inv_id}/patches", response_model=list[PatchOut])
def list_patches(inv_id: str, db: Session = Depends(get_db)) -> list[Patch]:
    _get(db, inv_id)
    return db.query(Patch).filter_by(investigation_id=inv_id).order_by(Patch.created_at).all()


def _patch(db: Session, inv_id: str, patch_id: str) -> Patch:
    patch = db.get(Patch, patch_id)
    if patch is None or patch.investigation_id != inv_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patch not found")
    return patch


@router.get("/{inv_id}/patches/{patch_id}/diff")
def download_patch(inv_id: str, patch_id: str, db: Session = Depends(get_db)) -> Response:
    patch = _patch(db, inv_id, patch_id)
    return PlainTextResponse(
        patch.diff,
        media_type="text/x-diff",
        headers={"Content-Disposition": f'attachment; filename="forge0-{inv_id[:8]}-{patch.key}.patch"'},
    )


@router.post("/{inv_id}/patches/{patch_id}/review", response_model=PatchOut)
def review_patch(inv_id: str, patch_id: str, body: PatchReview, db: Session = Depends(get_db)) -> Patch:
    patch = _patch(db, inv_id, patch_id)
    if body.decision == "approved" and patch.status != "verified":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only verified patches can be approved")
    patch.review_status = body.decision
    patch.review_note = body.note
    db.add(
        Event(
            investigation_id=inv_id,
            agent="human",
            type="review",
            message=f"{patch.key} marked {body.decision} by reviewer"
            + (f": {body.note}" if body.note else ""),
            data={"patch": patch.key, "decision": body.decision},
        )
    )
    return patch


@router.post("/{inv_id}/verify")
def reverify(inv_id: str, body: VerifyRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Re-runs independent verification of a patch (no model calls)."""
    inv = _get(db, inv_id)
    if inv.status not in TERMINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, "Investigation is still running")
    patches = [p for p in inv.patches if p.edits]
    if body.patch_id:
        patches = [p for p in patches if p.id == body.patch_id]
    if not patches:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No patch with edits to verify")
    patch = next((p for p in reversed(patches) if p.status == "verified"), patches[-1])
    if not inv.investigation_report:
        raise HTTPException(status.HTTP_409_CONFLICT, "Investigation has no repository report")
    report = InvestigationReport.model_validate(inv.investigation_report)
    ctx = InvestigationContext(
        investigation_id=inv.id,
        repository_name=inv.repository.name,
        snapshot=Path(inv.repository.snapshot_path),
        mode=inv.mode,
        symptom=inv.symptom,
        target_test=inv.target_test,
        provider=MockProvider(),
        sandbox=get_sandbox(),
        workspaces=WorkspaceManager(),
        budget=build_budget(get_runtime_config(db)),
        report=report,
    )
    db.commit()  # release the session before the long-running sandbox work
    target = report.target_failure.test_name if report.target_failure else None
    edits = [SourceEdit.model_validate(e) for e in patch.edits]
    result = IndependentVerifier(ctx).verify(edits, target, f"{patch.key}-reverify")
    with session_scope() as s:
        row = s.get(Patch, patch.id)
        assert row is not None
        verification = dict(row.verification or {})
        verification["reverification"] = {
            "verdict": result.verdict,
            "reasons": result.reasons,
            "regressions": result.regressions,
            "target_patched": result.target_patched,
            "repeats": result.target_repeat_runs,
        }
        row.verification = verification
        i = s.get(Investigation, inv.id)
        if i is not None:
            i.phase = "completed"
            i.active_agent = None
    ctx.workspaces.cleanup(inv.id)
    out = dump(result)
    out.pop("baseline_run", None)
    out.pop("patched_run", None)
    return {"patch_id": patch.id, "patch_key": patch.key, "verification": out}


@router.get("/{inv_id}/report")
def get_report(
    inv_id: str, format: str = Query(default="json", pattern="^(json|md)$"), db: Session = Depends(get_db)
):
    inv = _get(db, inv_id)
    report = build_report(db, inv)
    if format == "md":
        return PlainTextResponse(render_markdown(report), media_type="text/markdown")
    return report
