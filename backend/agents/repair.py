"""Agent E — Repair Engineer."""

from __future__ import annotations

from typing import Any

from agents.base import InvestigationContext
from agents.prompts import one_shot_prompt, repair_prompt
from core.schemas import InvestigationReport, PatchDraft
from services.workspace import EditError, EditResult, apply_edits


class RepairEngineer:
    name = "repair_engineer"

    def __init__(self, ctx: InvestigationContext) -> None:
        self.ctx = ctx

    def propose(
        self,
        report: InvestigationReport,
        leader: dict[str, Any],
        evidence: list[dict[str, Any]],
        previous: list[dict[str, Any]],
        attempt: int,
    ) -> PatchDraft:
        ctx = self.ctx
        ctx.set_phase(f"repairing (attempt {attempt + 1})", self.name)
        system, user = repair_prompt(report, leader, evidence, previous)
        return ctx.call_model(
            agent=self.name,
            task="repair",
            system=system,
            user=user,
            context={
                "target_test": report.target_failure.test_name if report.target_failure else None,
                "attempt": attempt,
                "hypothesis": leader.get("key"),
            },
            schema=PatchDraft,
        )

    def propose_one_shot(self, report: InvestigationReport) -> PatchDraft:
        ctx = self.ctx
        ctx.set_phase("direct repair (baseline A)", self.name)
        system, user = one_shot_prompt(report, ctx.symptom)
        return ctx.call_model(
            agent=self.name,
            task="one_shot_repair",
            system=system,
            user=user,
            context={"target_test": report.target_failure.test_name if report.target_failure else None},
            schema=PatchDraft,
        )

    def materialize(self, draft: PatchDraft, label: str) -> EditResult:
        """Applies the patch to a scratch copy to validate it and compute the unified diff."""
        ctx = self.ctx
        ws = ctx.workspaces.create(ctx.snapshot, ctx.investigation_id, label)
        try:
            return apply_edits(ws, draft.edits, allow_test_files=False, allow_create=True)
        finally:
            ctx.workspaces.discard(ws)


__all__ = ["EditError", "RepairEngineer"]
