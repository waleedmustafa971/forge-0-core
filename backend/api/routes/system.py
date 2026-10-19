from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from api.deps import get_db, require_auth
from api.schemas import EventOut, ProviderCheckRequest
from core.config import REPO_ROOT, get_settings
from core.models import Event, Experiment, Investigation, Patch, Repository
from providers.registry import build_provider
from sandbox.docker import get_sandbox
from sandbox.runners import RUNNERS
from services.settings_service import (
    RuntimeConfig,
    RuntimeConfigUpdate,
    get_runtime_config,
    reset_runtime_config,
    secrets_status,
    update_runtime_config,
)

router = APIRouter(prefix="/api", tags=["system"])
VERSION = "0.1.0"


@router.get("/system/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    db_ok, db_detail = True, "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on infrastructure
        db_ok, db_detail = False, str(exc)[:200]
    sandbox = get_sandbox().status()
    config = get_runtime_config(db)
    selection = build_provider(config)
    return {
        "status": "ok" if db_ok else "degraded",
        "version": VERSION,
        "time": datetime.now(UTC).isoformat(),
        "database": {"ok": db_ok, "dialect": db.get_bind().dialect.name, "detail": db_detail},
        "sandbox": {
            "ok": sandbox.available,
            "detail": sandbox.detail,
            "docker_command": " ".join(sandbox.docker_command),
            "server_version": sandbox.server_version,
        },
        "provider": {
            "requested": config.ai_provider,
            "active": selection.provider.name,
            "model": selection.provider.model,
            "simulated": selection.provider.simulated,
            "fallback_reason": selection.fallback_reason,
        },
    }


@router.get("/system/info", dependencies=[Depends(require_auth)])
def info() -> dict[str, Any]:
    s = get_settings()
    return {
        "version": VERSION,
        "auth_mode": s.auth_mode,
        "sandbox": {
            "node_image": s.sandbox_node_image,
            "python_image": s.sandbox_python_image,
            "cpus": s.sandbox_cpus,
            "memory": s.sandbox_memory,
            "pids_limit": s.sandbox_pids_limit,
            "timeout_s": s.sandbox_timeout_s,
            "workdir_size": s.sandbox_workdir_size,
            "network": "none",
            "read_only_rootfs": True,
            "runners": {name: r.description for name, r in RUNNERS.items()},
        },
    }


@router.post("/system/provider/check", dependencies=[Depends(require_auth)])
def provider_check(body: ProviderCheckRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    config = get_runtime_config(db)
    if body.provider:
        config = config.model_copy(update={"ai_provider": body.provider})
    selection = build_provider(config)
    result = selection.provider.check(deep=body.deep)
    result["requested"] = selection.requested
    result["fallback_reason"] = selection.fallback_reason
    if selection.fallback_reason:
        result["ok"] = False
    return result


@router.get("/settings", dependencies=[Depends(require_auth)])
def get_app_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    s = get_settings()
    return {
        "runtime": get_runtime_config(db).model_dump(),
        "secrets": secrets_status(),
        "endpoints": {
            "meta_api_base_url": s.meta_api_base_url,
            "openai_compat_base_url": s.openai_compat_base_url,
        },
        "pricing": {"input_per_m": s.ai_price_input_per_m, "output_per_m": s.ai_price_output_per_m},
        "meta": {
            "reasoning_effort": s.meta_reasoning_effort or None,
            "structured_output": s.meta_structured_output,
        },
    }


@router.put("/settings", dependencies=[Depends(require_auth)], response_model=RuntimeConfig)
def put_app_settings(body: RuntimeConfigUpdate, db: Session = Depends(get_db)) -> RuntimeConfig:
    return update_runtime_config(db, body)


@router.post("/settings/reset", dependencies=[Depends(require_auth)], response_model=RuntimeConfig)
def reset_app_settings(db: Session = Depends(get_db)) -> RuntimeConfig:
    return reset_runtime_config(db)


@router.get("/dashboard", dependencies=[Depends(require_auth)])
def dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    by_status = dict(db.query(Investigation.status, func.count()).group_by(Investigation.status).all())
    by_verdict = dict(db.query(Investigation.verdict, func.count()).group_by(Investigation.verdict).all())
    failed_experiments = db.query(Experiment).filter(Experiment.outcome.in_(["error", "timeout"])).count()
    since = datetime.now(UTC) - timedelta(days=7)
    recent = db.query(Event).order_by(Event.id.desc()).limit(25).all()
    titles = dict(db.query(Investigation.id, Investigation.title).all())
    return {
        "active": by_status.get("running", 0) + by_status.get("queued", 0) + by_status.get("cancelling", 0),
        "completed": by_status.get("completed", 0),
        "failed": by_status.get("failed", 0),
        "verified_repairs": by_verdict.get("verified_fix", 0),
        "no_verified_fix": by_verdict.get("no_verified_fix", 0),
        "inconclusive": by_verdict.get("inconclusive", 0),
        "experiments_total": db.query(Experiment).count(),
        "experiments_failed_to_run": failed_experiments,
        "patches_rejected": db.query(Patch).filter(Patch.status.in_(["rejected", "apply_failed"])).count(),
        "repositories": db.query(Repository).count(),
        "investigations_last_7d": db.query(Investigation).filter(Investigation.created_at >= since).count(),
        "recent_activity": [
            EventOut.model_validate(e).model_dump(mode="json")
            | {"investigation_title": titles.get(e.investigation_id)}
            for e in recent
        ],
    }


@router.get("/benchmarks", dependencies=[Depends(require_auth)])
def list_benchmarks() -> dict[str, Any]:
    results_dir = REPO_ROOT / "benchmarks" / "results"
    files = sorted(results_dir.glob("*.json"), reverse=True) if results_dir.is_dir() else []
    runs = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runs.append(
            {
                "file": f.name,
                "run_id": data.get("run_id"),
                "created_at": data.get("created_at"),
                "provider": data.get("provider"),
                "simulated": data.get("simulated"),
            }
        )
    return {"runs": runs}


@router.get("/benchmarks/{name}", dependencies=[Depends(require_auth)])
def get_benchmark(name: str) -> dict[str, Any]:
    results_dir = REPO_ROOT / "benchmarks" / "results"
    if name == "latest":
        files = sorted(results_dir.glob("*.json"), reverse=True) if results_dir.is_dir() else []
        if not files:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No benchmark results yet")
        path = files[0]
    else:
        if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid name")
        path = results_dir / (name if name.endswith(".json") else f"{name}.json")
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Benchmark not found")
    return json.loads(path.read_text(encoding="utf-8"))
