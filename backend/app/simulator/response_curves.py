"""Frozen response-curve module for the Synthetic Merchant Simulator (ticket 02).

Written and frozen before any Decision Engine / estimator work exists, per
ADR-0007's independence discipline: the estimator (ticket 07) must be
designed without visibility into these parameter values. Do not import this
module's constants from `app.decision` or any future estimator code.

Versioned: bump SIMULATOR_VERSION on any change to the constants below, since
such a change invalidates comparability with prior evaluation runs.

ticket 19 / ADR-0014 is the first such change: a flat, persona-uniform
`INCENTIVE_UPLIFT` for any executed intervention whose Incentive actually
cost money, applied by `response_probability` below. Still independent of
Decision Engine/estimator code (nothing here reads `incentive_pct` or any
economic threshold -- the caller decides whether an execution had a cost;
this module only says what a costed execution is worth).
"""

from __future__ import annotations

from app.models import Intervention
from app.simulator.personas import Persona

SIMULATOR_VERSION = "response-curves-v2"


# Base recovery probability per (persona, intervention), before fatigue
# decay is applied. NO_ACTION's value is the persona's spontaneous-recovery
# rate -- cases that recover with no intervention at all, needed for the
# no-intervention baseline (spec user story 51).
BASE_RESPONSE_CURVES: dict[Persona, dict[Intervention, float]] = {
    Persona.LOYAL: {
        Intervention.PAYMENT_RETRY: 0.55,
        Intervention.RESUME_CHARGE: 0.60,
        Intervention.NO_ACTION: 0.35,
    },
    Persona.BARGAIN_HUNTER: {
        Intervention.PAYMENT_RETRY: 0.45,
        Intervention.RESUME_CHARGE: 0.40,
        Intervention.NO_ACTION: 0.10,
    },
    Persona.NEW: {
        Intervention.PAYMENT_RETRY: 0.35,
        Intervention.RESUME_CHARGE: 0.30,
        Intervention.NO_ACTION: 0.15,
    },
    Persona.UNRELIABLE_PAYER: {
        Intervention.PAYMENT_RETRY: 0.20,
        Intervention.RESUME_CHARGE: 0.18,
        Intervention.NO_ACTION: 0.05,
    },
}

# Geometric fatigue/diminishing-returns decay applied per prior attempt of
# the *same* intervention already tried on a case (CONTEXT.md: Case History
# drives this state-dependent effect).
FATIGUE_DECAY_RATE = 0.65

_MIN_PROBABILITY = 0.02

# ADR-0014: flat boost to post-fatigue recovery probability for an executed
# intervention that carried a real, non-zero Incentive -- uniform across
# every persona (no per-persona discount-sensitivity; that learnable version
# is deliberately deferred, see [[0014-flat-incentive-response-learnable-deferred]]).
INCENTIVE_UPLIFT = 0.10


def decayed_probability(base_probability: float, prior_attempts_of_this_intervention: int) -> float:
    """Apply fatigue decay for repeated attempts of the same intervention within a case."""
    decay = FATIGUE_DECAY_RATE**prior_attempts_of_this_intervention
    return max(_MIN_PROBABILITY, base_probability * decay)


def response_probability(
    base_probability: float, prior_attempts_of_this_intervention: int, *, incentive_amount: int = 0
) -> float:
    """`decayed_probability`, plus ADR-0014's flat `INCENTIVE_UPLIFT` on top
    whenever this execution's `incentive_amount` is real money (> 0) --
    `NO_ACTION` never carries one, so callers resolving it pass no
    `incentive_amount` and get plain `decayed_probability` behavior back.
    Re-clamped to the same `[_MIN_PROBABILITY, 1.0]` band, since the uplift
    can push an already-high probability past 1.0.
    """
    probability = decayed_probability(base_probability, prior_attempts_of_this_intervention)
    if incentive_amount > 0:
        probability += INCENTIVE_UPLIFT
    return max(_MIN_PROBABILITY, min(1.0, probability))
