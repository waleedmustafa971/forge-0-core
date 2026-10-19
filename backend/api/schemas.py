"""Request/response models for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RepositoryCreate(BaseModel):
    source_type: Literal["local", "git"]
    path: str | None = Field(default=None, max_length=1000)
    url: str | None = Field(default=None, max_length=1000)
    ref: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> RepositoryCreate:
        if self.source_type == "local" and not self.path:
            raise ValueError("path is required for local imports")
        if self.source_type == "git" and not self.url:
            raise ValueError("url is required for git imports")
        return self


class RepositoryOut(ORM):
    id: str
    name: str
    source_type: str
    source: str
    commit_sha: str | None
    profile: dict[str, Any]
    last_scan: dict[str, Any] | None
    created_at: datetime


class InvestigationCreate(BaseModel):
    repository_id: str
    title: str | None = Field(default=None, max_length=300)
    symptom: str = Field(default="", max_length=5000)
    target_test: str | None = Field(default=None, max_length=1000)
    mode: Literal["forge", "baseline"] = "forge"


class InvestigationOut(ORM):
    id: str
    repository_id: str
    title: str
    symptom: str
    target_test: str | None
    mode: str
    status: str
    phase: str
    active_agent: str | None
    verdict: str | None
    provider: str
    model: str
    simulated: bool
    provider_note: str | None
    budget: dict[str, Any]
    usage: dict[str, Any]
    summary: dict[str, Any] | None
    root_cause: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class InvestigationDetail(InvestigationOut):
    investigation_report: dict[str, Any] | None
    repository_name: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class EventOut(ORM):
    id: int
    investigation_id: str
    ts: datetime
    agent: str
    type: str
    message: str
    data: dict[str, Any]


class HypothesisOut(ORM):
    id: str
    key: str
    title: str
    explanation: str
    suspected_locations: list[str]
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    prior: float
    confidence: float
    status: str
    rank: int
    history: list[dict[str, Any]]


class ExperimentOut(ORM):
    id: str
    key: str
    round: int
    designed_by: str
    kind: str
    objective: str
    hypothesis_keys: list[str]
    predictions: list[dict[str, Any]]
    spec: dict[str, Any]
    status: str
    outcome: str | None
    result: dict[str, Any] | None
    evaluation: dict[str, Any] | None
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None


class PatchOut(ORM):
    id: str
    key: str
    attempt: int
    hypothesis_key: str | None
    summary: str
    rationale: str
    edits: list[dict[str, Any]]
    diff: str
    files_changed: list[dict[str, Any]]
    status: str
    verification: dict[str, Any] | None
    review_status: str
    review_note: str | None
    created_at: datetime


class PatchReview(BaseModel):
    decision: Literal["approved", "rejected", "pending"]
    note: str | None = Field(default=None, max_length=2000)


class VerifyRequest(BaseModel):
    patch_id: str | None = None


class ProviderCheckRequest(BaseModel):
    provider: Literal["mock", "meta", "openai"] | None = None
    deep: bool = False
