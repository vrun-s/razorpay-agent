"""Per-case generation for the Synthetic Merchant Simulator (ticket 02).

Pure and deterministic given a seed: the same (seed, size) always produces an
identical population of `SimulatedCase`s. `HiddenGroundTruth` is
simulator-only ground truth -- documented here never to be exposed to the
Decision Engine, per CONTEXT.md's Customer Segment vs Customer Segment Proxy
distinction.

Wired into the Gateway seam by `app/simulator_gateway.py` and driven at
volume by `app/simulator_driver.py` (ticket 14) -- both live outside this
package, which stays independent of Decision Engine/Policy Engine code.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from app.simulator.personas import Persona, sample_persona
from app.simulator.response_curves import BASE_RESPONSE_CURVES, Intervention, decayed_probability


@dataclass(frozen=True)
class HiddenGroundTruth:
    """Simulator-only. Never expose this to the Decision Engine (CONTEXT.md)."""

    customer_segment: Persona
    outcome_odds: dict[Intervention, float]  # base probability per intervention, pre-fatigue-decay


@dataclass(frozen=True)
class SimulatedCase:
    case_index: int
    hidden: HiddenGroundTruth


def generate_population(seed: int, size: int) -> list[SimulatedCase]:
    """Generate `size` cases deterministically: same (seed, size) -> identical output."""
    rng = random.Random(seed)
    return [_generate_one_case(rng, case_index=i) for i in range(size)]


def _generate_one_case(rng: random.Random, *, case_index: int) -> SimulatedCase:
    persona = sample_persona(rng)
    return SimulatedCase(
        case_index=case_index,
        hidden=HiddenGroundTruth(customer_segment=persona, outcome_odds=dict(BASE_RESPONSE_CURVES[persona])),
    )


def resolve_intervention(
    case: SimulatedCase,
    intervention: Intervention,
    *,
    prior_attempts_of_this_intervention: int,
    rng: random.Random,
) -> bool:
    """Draw a Bernoulli recovery outcome for `intervention` on `case`, with fatigue decay applied.

    The caller supplies `rng` so outcome draws are reproducible independently
    of population generation.
    """
    base_probability = case.hidden.outcome_odds[intervention]
    probability = decayed_probability(base_probability, prior_attempts_of_this_intervention)
    return rng.random() < probability
