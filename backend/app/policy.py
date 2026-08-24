"""Policy Engine (ticket 05) -- merchant-defined constraint enforcement.

`validate()` checks a proposed Intervention against hard constraints before
anything executes (spec: "the AI proposes but never acts on money
directly"). A violation is rejected outright, never downgraded or
auto-corrected to a compliant value -- the Policy Engine only says yes/no;
callers decide what happens next (e.g. NO_ACTION, stop, escalate).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.decision import VALID_INTERVENTIONS
from app.models import CaseHistoryEntryType, Intervention, RecoveryCase


@dataclass(frozen=True)
class PolicyConfig:
    """Merchant-defined constraints (spec user stories 23-25)."""

    max_discount_pct: float
    max_payment_retries: int
    max_interventions_per_customer: int
    recovery_budget: int  # smallest currency unit (paise), same convention as Payment.amount
    # ADR-0012: story 25's "cases above a certain value are routed to a
    # human" -- paise, same convention as recovery_budget. None disables it.
    escalation_value_threshold: int | None = None


DEFAULT_POLICY_CONFIG = PolicyConfig(
    max_discount_pct=20.0,
    max_payment_retries=3,
    max_interventions_per_customer=5,
    recovery_budget=1_000_000,  # INR 10,000 in paise
    escalation_value_threshold=None,
)


@dataclass(frozen=True)
class ProposedIntervention:
    """What the Decision Engine proposes, bundled with its economic terms."""

    intervention: Intervention
    discount_pct: float = 0.0
    incentive_amount: int = 0  # cost of this specific intervention, in paise


@dataclass(frozen=True)
class PolicyResult:
    approved: bool
    intervention: Intervention
    violated_constraint: str | None = None
    proposed_value: float | int | None = None  # the specific value that violated the constraint
    reason: str | None = None
    # ADR-0012: orthogonal to `approved` -- a compliant proposal on a
    # high-value case still escalates, and a rejected one can too.
    escalate: bool = False


def validate(
    case: RecoveryCase,
    proposal: ProposedIntervention,
    policy: PolicyConfig = DEFAULT_POLICY_CONFIG,
    *,
    budget_spent_so_far: int = 0,
    case_value: int = 0,
) -> PolicyResult:
    escalate = policy.escalation_value_threshold is not None and case_value >= policy.escalation_value_threshold

    # ADR-0002/ADR-0009 (spec story 28): each workflow declares its own valid
    # Intervention subset -- checked first, since a violation here means the
    # proposal doesn't even belong to this case's workflow, before any
    # economic constraint is meaningful to evaluate against it.
    if proposal.intervention not in VALID_INTERVENTIONS[case.workflow_type]:
        return _reject(
            proposal,
            "invalid_intervention_for_workflow",
            reason=f"{proposal.intervention.value} is not valid for workflow {case.workflow_type.value}",
            escalate=escalate,
        )

    if proposal.discount_pct > policy.max_discount_pct:
        return _reject(
            proposal,
            "max_discount_pct",
            proposed_value=proposal.discount_pct,
            reason=f"discount_pct {proposal.discount_pct} exceeds max_discount_pct {policy.max_discount_pct}",
            escalate=escalate,
        )

    if proposal.intervention == Intervention.PAYMENT_RETRY:
        attempt_number = _prior_executions_of(case, Intervention.PAYMENT_RETRY) + 1
        if attempt_number > policy.max_payment_retries:
            return _reject(
                proposal,
                "max_payment_retries",
                proposed_value=attempt_number,
                reason=f"attempt {attempt_number} exceeds max_payment_retries {policy.max_payment_retries}",
                escalate=escalate,
            )

    # Case ~ customer for now: no cross-case customer identity exists yet, so
    # "per customer" scopes to this case's own executed interventions.
    intervention_number = _total_prior_executions(case) + 1
    if intervention_number > policy.max_interventions_per_customer:
        return _reject(
            proposal,
            "max_interventions_per_customer",
            proposed_value=intervention_number,
            reason=(
                f"intervention {intervention_number} exceeds "
                f"max_interventions_per_customer {policy.max_interventions_per_customer}"
            ),
            escalate=escalate,
        )

    projected_spend = budget_spent_so_far + proposal.incentive_amount
    if projected_spend > policy.recovery_budget:
        return _reject(
            proposal,
            "recovery_budget",
            proposed_value=projected_spend,
            reason=f"projected spend {projected_spend} exceeds recovery_budget {policy.recovery_budget}",
            escalate=escalate,
        )

    return PolicyResult(approved=True, intervention=proposal.intervention, escalate=escalate)


def _total_prior_executions(case: RecoveryCase) -> int:
    """Count every EXECUTION entry already recorded on this case (for max_interventions_per_customer)."""
    return sum(1 for entry in case.history if entry.entry_type == CaseHistoryEntryType.EXECUTION)


def _prior_executions_of(case: RecoveryCase, intervention: Intervention) -> int:
    """Count EXECUTION entries of one specific intervention type (for max_payment_retries)."""
    return sum(
        1
        for entry in case.history
        if entry.entry_type == CaseHistoryEntryType.EXECUTION and entry.data.get("intervention") == intervention.value
    )


def _reject(
    proposal: ProposedIntervention,
    constraint: str,
    *,
    proposed_value: float | int | None = None,
    reason: str,
    escalate: bool = False,
) -> PolicyResult:
    return PolicyResult(
        approved=False,
        intervention=proposal.intervention,
        violated_constraint=constraint,
        proposed_value=proposed_value,
        reason=reason,
        escalate=escalate,
    )
