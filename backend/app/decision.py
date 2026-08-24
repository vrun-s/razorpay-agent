"""Decision Engine (ticket 07/08, ADR-0009/ADR-0006).

`decide()` picks the intervention -- among the workflow's valid subset,
per [[0002-pluggable-workflow-abstraction]] -- with the highest posterior
point estimate from the shared `Estimator` (app/estimator.py). This is a
greedy choice by design, not an oversight: exploration under uncertainty is
the Streaming Allocator's job (ticket 10), not this function's -- the spec's
Out of Scope list rules out a separate exploration algorithm here.

`justification` and `escalate` are ticket-08's LLM-bounded roles
(app/llm.py's `LLMClient`) -- generated strictly *after*
`point_estimate`/`uncertainty` are read from the estimator, from values
already fixed at that point, so no LLM step can ever touch them (ticket 08's
own acceptance criteria requires this bit-for-bit guarantee).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.estimator import CustomerHistory, CustomerSegmentProxy, EstimatorCellKey, customer_segment_proxy, get_estimator
from app.llm import LLMClient, get_llm_client
from app.models import CaseHistoryEntryType, Intervention, RecoveryCase, WorkflowType

_UNKNOWN_FAILURE_REASON = "unknown"

# Which Intervention values a workflow may propose (CONTEXT.md: Intervention;
# ADR-0009 documents this mapping). Order matters: it's decide()'s tie-break
# order at cold start, when every cell in a workflow starts at the same
# Beta(2,2) point estimate.
VALID_INTERVENTIONS: dict[WorkflowType, tuple[Intervention, ...]] = {
    WorkflowType.FAILED_PAYMENT: (Intervention.PAYMENT_RETRY, Intervention.NO_ACTION),
    WorkflowType.HALTED_SUBSCRIPTION: (Intervention.RESUME_CHARGE, Intervention.NO_ACTION),
}


@dataclass(frozen=True)
class DecisionInput:
    case: RecoveryCase
    customer_history: CustomerHistory
    failure_reason: str | None = None  # LLM-diagnosed (ticket 08); failed_payment workflow only
    qualitative_signal: str | None = None  # LLM escalation-flag input (ADR-0011); no real source wired yet


@dataclass(frozen=True)
class DecisionOutput:
    intervention: Intervention
    point_estimate: float  # the chosen intervention's Beta-Bernoulli posterior mean
    uncertainty: float  # its credible interval width
    justification: str  # LLM-generated (ticket 08)
    escalate: bool  # LLM-flagged qualitative escalation signal (ticket 08)


def resolve_cell_key(input: DecisionInput, intervention: Intervention) -> EstimatorCellKey:
    """The estimator cell a given proposal on `input` falls into.

    Exposed (not just used internally by `decide()`) so a later outcome
    observation -- which happens at a different point in time, once a case
    resolves -- can be attributed back to the exact same cell without
    re-deriving `failure_reason`/`customer_segment_proxy` a second way.
    """
    return EstimatorCellKey(
        failure_reason=input.failure_reason or _UNKNOWN_FAILURE_REASON,
        customer_segment_proxy=customer_segment_proxy(input.customer_history),
        intervention=intervention,
    )


def resolve_last_decided_cell_key(case: RecoveryCase) -> EstimatorCellKey | None:
    """Reconstructs the estimator cell for a case's most recent DECISION entry.

    Paired with `resolve_cell_key` for the reverse direction: when an outcome
    resolves later (mark_recovered, at a different point in time/control flow
    than the original `decide()` call), this is how it's attributed back to
    the exact same cell -- kept here, not in lifecycle.py, so only this
    module knows `EstimatorCellKey`'s field layout.
    """
    decisions = [entry for entry in case.history if entry.entry_type == CaseHistoryEntryType.DECISION]
    if not decisions:
        return None
    data = decisions[-1].data
    return EstimatorCellKey(
        failure_reason=data["failure_reason"],
        customer_segment_proxy=CustomerSegmentProxy(data["customer_segment_proxy"]),
        intervention=Intervention(data["intervention"]),
    )


def decide(input: DecisionInput, *, llm_client: LLMClient | None = None) -> DecisionOutput:
    llm_client = llm_client or get_llm_client()
    estimator = get_estimator()
    candidates = VALID_INTERVENTIONS[input.case.workflow_type]
    best_intervention = max(
        candidates, key=lambda intervention: estimator.estimate(resolve_cell_key(input, intervention)).point_estimate
    )
    # point_estimate/uncertainty are fixed here, before any LLM call below --
    # nothing from this point on can feed back into them.
    estimate = estimator.estimate(resolve_cell_key(input, best_intervention))
    point_estimate = estimate.point_estimate
    uncertainty = estimate.uncertainty
    segment = customer_segment_proxy(input.customer_history)
    failure_reason = input.failure_reason or _UNKNOWN_FAILURE_REASON

    justification = llm_client.generate_justification(
        intervention=best_intervention.value,
        point_estimate=point_estimate,
        uncertainty=uncertainty,
        segment=segment.value,
        failure_reason=failure_reason,
    )
    escalate = (
        llm_client.flag_escalation(signal_text=input.qualitative_signal) if input.qualitative_signal else False
    )

    return DecisionOutput(
        intervention=best_intervention,
        point_estimate=point_estimate,
        uncertainty=uncertainty,
        justification=justification,
        escalate=escalate,
    )
