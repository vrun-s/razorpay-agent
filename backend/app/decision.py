"""Decision Engine — ticket 01 stub, plus ticket 06's fatigue signal.

Trivial fixed-rule decision: always propose Payment Retry. Ticket 07 replaces
this with the Beta-Bernoulli estimator + bounded LLM role (ADR-0006); nothing
downstream of this function's return type should need to change when that
happens.

`expected_effect` is a ticket-06 stopgap: the case lifecycle (ADR-0004) needs
*some* signal that repeating an intervention yields diminishing returns
(spec user story 11) before the real estimator exists. Ticket 07 replaces
this with the posterior's point estimate, which is expected to already
account for Case History; this function should be removed then, not kept
alongside it. Its decay rate is this module's own guess, chosen without
looking at the Synthetic Merchant Simulator's fatigue constants
(app/simulator/response_curves.py) -- ADR-0007 requires the two stay
independent, so this value must never be copied from or reconciled against
that module's.
"""

from __future__ import annotations

from app.models import CaseHistoryEntryType, Intervention, RecoveryCase

FATIGUE_DECAY_RATE = 0.8

_BASE_EXPECTED_EFFECT: dict[Intervention, float] = {
    Intervention.PAYMENT_RETRY: 0.5,
    Intervention.RESUME_CHARGE: 0.5,
    Intervention.NO_ACTION: 0.0,
}


def decide(case: RecoveryCase) -> Intervention:
    return Intervention.PAYMENT_RETRY


def expected_effect(case: RecoveryCase, intervention: Intervention) -> float:
    """A fatigue-decayed proxy for "how much this intervention is expected to help."

    Decays geometrically per prior EXECUTION of this same intervention type
    already on the case (CONTEXT.md: Case History drives fatigue).
    """
    prior_attempts = sum(
        1
        for entry in case.history
        if entry.entry_type == CaseHistoryEntryType.EXECUTION and entry.data.get("intervention") == intervention.value
    )
    base = _BASE_EXPECTED_EFFECT.get(intervention, 0.0)
    return base * (FATIGUE_DECAY_RATE**prior_attempts)
