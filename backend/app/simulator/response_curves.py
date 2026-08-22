"""Frozen response-curve module for the Synthetic Merchant Simulator (ticket 02).

Written and frozen before any Decision Engine / estimator work exists, per
ADR-0007's independence discipline: the estimator (ticket 07) must be
designed without visibility into these parameter values. Do not import this
module's constants from `app.decision` or any future estimator code.

Versioned: bump SIMULATOR_VERSION on any change to the constants below, since
such a change invalidates comparability with prior evaluation runs.
"""

from __future__ import annotations

from app.models import Intervention
from app.simulator.personas import Persona

SIMULATOR_VERSION = "response-curves-v1"


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


def decayed_probability(base_probability: float, prior_attempts_of_this_intervention: int) -> float:
    """Apply fatigue decay for repeated attempts of the same intervention within a case."""
    decay = FATIGUE_DECAY_RATE**prior_attempts_of_this_intervention
    return max(_MIN_PROBABILITY, base_probability * decay)
