"""Policy Engine (ticket 05) -- merchant-defined constraint enforcement.

`validate()` checks a proposed Intervention against hard constraints before
anything executes (spec: "the AI proposes but never acts on money
directly"). A violation is rejected outright, never downgraded or
auto-corrected to a compliant value -- the Policy Engine only says yes/no;
callers decide what happens next (e.g. NO_ACTION, stop, escalate).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import CaseHistoryEntryType, Intervention, RecoveryCase


@dataclass(frozen=True)
class PolicyConfig:
    """Merchant-defined constraints (spec user stories 23-25)."""

    max_discount_pct: float
    max_payment_retries: int
    max_interventions_per_customer: int
    recovery_budget: int  # smallest currency unit (paise), same convention as Payment.amount


DEFAULT_POLICY_CONFIG = PolicyConfig(
    max_discount_pct=20.0,
    max_payment_retries=3,
    max_interventions_per_customer=5,
    recovery_budget=1_000_000,  # INR 10,000 in paise
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


def validate(
    case: RecoveryCase,
    proposal: ProposedIntervention,
    policy: PolicyConfig = DEFAULT_POLICY_CONFIG,
    *,
    budget_spent_so_far: int = 0,
) -> PolicyResult:
    if proposal.discount_pct > policy.max_discount_pct:
        return _reject(
            proposal,
            "max_discount_pct",
            proposed_value=proposal.discount_pct,
            reason=f"discount_pct {proposal.discount_pct} exceeds max_discount_pct {policy.max_discount_pct}",
        )

    if proposal.intervention == Intervention.PAYMENT_RETRY:
        attempt_number = _prior_executions_of(case, Intervention.PAYMENT_RETRY) + 1
        if attempt_number > policy.max_payment_retries:
            return _reject(
                proposal,
                "max_payment_retries",
                proposed_value=attempt_number,
                reason=f"attempt {attempt_number} exceeds max_payment_retries {policy.max_payment_retries}",
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
        )

    projected_spend = budget_spent_so_far + proposal.incentive_amount
    if projected_spend > policy.recovery_budget:
        return _reject(
            proposal,
            "recovery_budget",
            proposed_value=projected_spend,
            reason=f"projected spend {projected_spend} exceeds recovery_budget {policy.recovery_budget}",
        )

    return PolicyResult(approved=True, intervention=proposal.intervention)


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
    proposal: ProposedIntervention, constraint: str, *, proposed_value: float | int, reason: str
) -> PolicyResult:
    return PolicyResult(
        approved=False,
        intervention=proposal.intervention,
        violated_constraint=constraint,
        proposed_value=proposed_value,
        reason=reason,
    )
