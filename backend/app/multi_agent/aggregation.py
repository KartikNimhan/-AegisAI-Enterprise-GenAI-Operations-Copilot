"""`ResultAggregator`: combines structured `AgentResult`s into one final
answer — never silently discarding a failure, never fabricating a
result for an agent that didn't complete (see
docs/architecture/decisions/010-multi-agent-architecture.md,
"Aggregation"/"Partial results").

No LLM call of its own: when an Analyst ran, its answer already *is* the
cross-agent synthesis (that's the Analyst's job); when it didn't, there is
at most one successful specialist, so there is nothing left to synthesize
— surfacing that one answer directly is simpler and more honest than an
extra LLM call restating it.
"""

from __future__ import annotations

from app.multi_agent.capabilities import AGENT_ANALYST
from app.multi_agent.models import STATUS_COMPLETED, AgentResult


class ResultAggregator:
    def combine(self, *, agent_results: list[AgentResult]) -> tuple[str, str]:
        """Returns `(answer, workflow_status)`."""
        if not agent_results:
            return "", STATUS_COMPLETED

        successes = [r for r in agent_results if r.status == STATUS_COMPLETED]
        failures = [r for r in agent_results if r.status != STATUS_COMPLETED]

        if not successes:
            unavailable = "; ".join(f"{r.agent_name} ({r.status})" for r in failures)
            return (
                f"Unable to produce an answer — no agent completed successfully: {unavailable}.",
                "failed",
            )

        analyst_result = next((r for r in successes if r.agent_name == AGENT_ANALYST), None)
        if analyst_result is not None:
            answer = analyst_result.answer
        elif len(successes) == 1:
            answer = successes[0].answer
        else:
            # Multiple non-analyst successes with no synthesis step is not
            # expected from the router (it always adds `synthesis` when
            # more than one capability is needed), but concatenating
            # rather than crashing keeps this defensive, not brittle.
            answer = " ".join(r.answer for r in successes if r.answer)

        if failures:
            missing = "; ".join(f"{r.agent_name} did not complete ({r.status})" for r in failures)
            answer = f"{answer}\n\n(Note: {missing}.)"
            return answer, "partial"

        return answer, STATUS_COMPLETED
