"""ORM models: the persistent investigation state and audit trail."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")
EventId = BigInteger().with_variant(Integer(), "sqlite")


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(20))  # demo | local | git
    source: Mapped[str] = mapped_column(Text)
    snapshot_path: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    last_scan: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    investigations: Mapped[list[Investigation]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", passive_deletes=True
    )


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    symptom: Mapped[str] = mapped_column(Text, default="")
    target_test: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(20), default="forge")  # forge | baseline
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(40), default="queued")
    active_agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    model: Mapped[str] = mapped_column(String(120), default="")
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    investigation_report: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="investigations")
    hypotheses: Mapped[list[Hypothesis]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", order_by="Hypothesis.created_at"
    )
    experiments: Mapped[list[Experiment]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", order_by="Experiment.created_at"
    )
    patches: Mapped[list[Patch]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", order_by="Patch.created_at"
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(EventId, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    agent: Mapped[str] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    suspected_locations: Mapped[list[str]] = mapped_column(JsonType, default=list)
    supporting_evidence: Mapped[list[str]] = mapped_column(JsonType, default=list)
    contradicting_evidence: Mapped[list[str]] = mapped_column(JsonType, default=list)
    prior: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|supported|refuted|confirmed
    rank: Mapped[int] = mapped_column(Integer, default=0)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    investigation: Mapped[Investigation] = relationship(back_populates="hypotheses")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(16))
    round: Mapped[int] = mapped_column(Integer, default=0)
    designed_by: Mapped[str] = mapped_column(String(40), default="experiment_designer")
    kind: Mapped[str] = mapped_column(String(30))
    objective: Mapped[str] = mapped_column(Text)
    hypothesis_keys: Mapped[list[str]] = mapped_column(JsonType, default=list)
    predictions: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    spec: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned|running|completed|invalid
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pass|fail|error|timeout
    result: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    investigation: Mapped[Investigation] = relationship(back_populates="experiments")


class Patch(Base):
    __tablename__ = "patches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    hypothesis_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    edits: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    diff: Mapped[str] = mapped_column(Text, default="")
    files_changed: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    verification: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    investigation: Mapped[Investigation] = relationship(back_populates="patches")


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[str] = mapped_column(String(40))
    task: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tokens_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
