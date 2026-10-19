"""Agent B — Hypothesis Generator."""

from __future__ import annotations

from agents.base import InvestigationContext
from agents.prompts import hypotheses_prompt
from core.schemas import HypothesisDraft, HypothesisSet, InvestigationReport

MIN_HYPOTHESES = 2
MAX_HYPOTHESES = 5


class HypothesisGenerator:
    name = "hypothesis_generator"

    def __init__(self, ctx: InvestigationContext) -> None:
        self.ctx = ctx

    def run(self, report: InvestigationReport) -> HypothesisSet:
        ctx = self.ctx
        ctx.set_phase("hypothesizing", self.name)
        system, user = hypotheses_prompt(report, ctx.symptom)
        target = report.target_failure
        context = {
            "target_test": target.test_name if target else None,
            "error": target.error if target else None,
            "implicated_files": target.implicated_files if target else [],
        }
        result = ctx.call_model(
            agent=self.name,
            task="hypotheses",
            system=system,
            user=user,
            context=context,
            schema=HypothesisSet,
        )
        hypotheses = self._normalize(result.hypotheses)
        if len(hypotheses) < MIN_HYPOTHESES:
            ctx.emit(
                self.name, "warning", "Fewer than two competing hypotheses returned; requesting alternatives"
            )
            retry = ctx.call_model(
                agent=self.name,
                task="hypotheses",
                system=system,
                user=user
                + "\n\nYou returned fewer than two hypotheses. Provide at least two competing explanations.",
                context=context,
                schema=HypothesisSet,
            )
            hypotheses = self._normalize(result.hypotheses + retry.hypotheses)
        if len(hypotheses) < MIN_HYPOTHESES:
            hypotheses.append(
                HypothesisDraft(
                    key=f"H{len(hypotheses) + 1}",
                    title="The defect lies outside the implicated code",
                    explanation="Control hypothesis added by the orchestrator so that the leading "
                    "explanation "
                    "must out-predict at least one alternative.",
                    prior=0.2,
                )
            )
        result.hypotheses = hypotheses
        return result

    @staticmethod
    def _normalize(drafts: list[HypothesisDraft]) -> list[HypothesisDraft]:
        seen_titles: set[str] = set()
        out: list[HypothesisDraft] = []
        for draft in drafts:
            title = draft.title.strip().lower()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            out.append(draft)
        out = out[:MAX_HYPOTHESES]
        # Keys must be unique and stable; keep model keys when they already are.
        keys = [d.key.strip() for d in out]
        if len(set(keys)) != len(keys) or any(not k for k in keys):
            for i, draft in enumerate(out, start=1):
                draft.key = f"H{i}"
        return out
