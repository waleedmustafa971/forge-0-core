"""Runtime-adjustable settings (provider choice and model parameters).

Environment variables provide defaults; non-secret overrides are stored in the
``app_settings`` table. API keys are only ever read from the environment and are never
returned by the API — only whether they are configured.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.config import get_settings
from core.models import AppSetting

RUNTIME_KEY = "runtime"


class RuntimeConfig(BaseModel):
    ai_provider: Literal["mock", "meta", "openai"]
    meta_model: str
    openai_compat_model: str
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(ge=256, le=65536)
    max_experiments: int = Field(ge=1, le=50)
    max_model_calls: int = Field(ge=2, le=200)
    max_repair_attempts: int = Field(ge=1, le=10)
    max_experiment_rounds: int = Field(ge=1, le=10)
    time_budget_s: int = Field(ge=60, le=7200)


class RuntimeConfigUpdate(BaseModel):
    ai_provider: Literal["mock", "meta", "openai"] | None = None
    meta_model: str | None = Field(default=None, max_length=120)
    openai_compat_model: str | None = Field(default=None, max_length=120)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=256, le=65536)
    max_experiments: int | None = Field(default=None, ge=1, le=50)
    max_model_calls: int | None = Field(default=None, ge=2, le=200)
    max_repair_attempts: int | None = Field(default=None, ge=1, le=10)
    max_experiment_rounds: int | None = Field(default=None, ge=1, le=10)
    time_budget_s: int | None = Field(default=None, ge=60, le=7200)


def env_defaults() -> RuntimeConfig:
    s = get_settings()
    return RuntimeConfig(
        ai_provider=s.ai_provider,
        meta_model=s.meta_model,
        openai_compat_model=s.openai_compat_model,
        temperature=s.ai_temperature,
        max_tokens=s.ai_max_tokens,
        max_experiments=s.max_experiments,
        max_model_calls=s.max_model_calls,
        max_repair_attempts=s.max_repair_attempts,
        max_experiment_rounds=s.max_experiment_rounds,
        time_budget_s=s.investigation_time_budget_s,
    )


def get_runtime_config(db: Session) -> RuntimeConfig:
    base = env_defaults().model_dump()
    row = db.get(AppSetting, RUNTIME_KEY)
    if row and isinstance(row.value, dict):
        base.update({k: v for k, v in row.value.items() if k in base and v is not None})
    return RuntimeConfig.model_validate(base)


def update_runtime_config(db: Session, update: RuntimeConfigUpdate) -> RuntimeConfig:
    row = db.get(AppSetting, RUNTIME_KEY)
    current: dict[str, Any] = dict(row.value) if row and isinstance(row.value, dict) else {}
    current.update(update.model_dump(exclude_none=True))
    merged = RuntimeConfig.model_validate({**env_defaults().model_dump(), **current})
    if row is None:
        db.add(AppSetting(key=RUNTIME_KEY, value=current))
    else:
        row.value = current
    db.flush()
    return merged


def reset_runtime_config(db: Session) -> RuntimeConfig:
    row = db.get(AppSetting, RUNTIME_KEY)
    if row is not None:
        db.delete(row)
        db.flush()
    return env_defaults()


def secrets_status() -> dict[str, bool]:
    s = get_settings()
    return {
        "meta_api_key_configured": s.resolved_meta_key is not None,
        "openai_compat_api_key_configured": bool(
            s.openai_compat_api_key and s.openai_compat_api_key.get_secret_value().strip()
        ),
    }
