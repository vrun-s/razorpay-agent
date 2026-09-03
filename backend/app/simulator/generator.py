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

import math
import random
from dataclasses import dataclass

from app.simulator.personas import Persona, sample_persona
from app.simulator.response_curves import BASE_RESPONSE_CURVES, Intervention, response_probability

# SPIKE (P1 eval): per-case value + failure-reason dispersion. Throwaway --
# Phase 2 replaces this with an ADR-backed model. Distributions picked to look
# like plausible SME data, NOT to make the AI arm win (Q10 tuning discipline).

# Lognormal case value in paise: median exp(mu) = 50_000 (Rs 500), sigma 1.5
# => p95 ~ Rs 5.9k. Hard-clamped to [Rs 50, Rs 20k].
_CASE_VALUE_MU = math.log(50_000)
_CASE_VALUE_SIGMA = 1.5
_CASE_VALUE_MIN = 5_000
_CASE_VALUE_MAX = 2_000_000

# Per-persona failure-reason mix. The persona already drives recovery odds, so
# conditioning failure_reason on persona is what gives the estimator's
# failure_reason axis real signal -- a plausible real-world correlation
# (shaky payers decline for funds/card reasons; loyal customers hit
# transient expiry/bank blips), not reverse-engineered from outcome_odds.
_FAILURE_REASON_MIX: dict[Persona, dict[str, float]] = {
    Persona.LOYAL: {
        "insufficient_funds": 0.15, "card_declined": 0.10, "expired_card": 0.30,
        "invalid_card_details": 0.05, "bank_server_error": 0.28, "fraud_suspected": 0.02,
        "customer_cancelled": 0.05, "unknown": 0.05,
    },
    Persona.BARGAIN_HUNTER: {
        "insufficient_funds": 0.28, "card_declined": 0.20, "expired_card": 0.10,
        "invalid_card_details": 0.07, "bank_server_error": 0.10, "fraud_suspected": 0.03,
        "customer_cancelled": 0.17, "unknown": 0.05,
    },
    Persona.NEW: {
        "insufficient_funds": 0.22, "card_declined": 0.16, "expired_card": 0.12,
        "invalid_card_details": 0.22, "bank_server_error": 0.12, "fraud_suspected": 0.05,
        "customer_cancelled": 0.06, "unknown": 0.05,
    },
    Persona.UNRELIABLE_PAYER: {
        "insufficient_funds": 0.42, "card_declined": 0.24, "expired_card": 0.06,
        "invalid_card_details": 0.08, "bank_server_error": 0.05, "fraud_suspected": 0.06,
        "customer_cancelled": 0.07, "unknown": 0.02,
    },
}

# Decline text per category, worded so app.llm.FakeLLMClient's keyword table
# diagnoses it straight back to the same category.
FAILURE_REASON_DECLINE_TEXT: dict[str, str] = {
    "insufficient_funds": "insufficient funds in account",
    "card_declined": "card declined by issuing bank",
    "expired_card": "card expired",
    "invalid_card_details": "invalid card number supplied",
    "bank_server_error": "bank server timeout",
    "fraud_suspected": "transaction flagged as fraud",
    "customer_cancelled": "payment cancelled by customer",
    "unknown": "unspecified gateway response",
}


@dataclass(frozen=True)
class HiddenGroundTruth:
    """Simulator-only. Never expose this to the Decision Engine (CONTEXT.md)."""

    customer_segment: Persona
    outcome_odds: dict[Intervention, float]  # base probability per intervention, pre-fatigue-decay


@dataclass(frozen=True)
class SimulatedCase:
    case_index: int
    hidden: HiddenGroundTruth
    # SPIKE (P1 eval): observable per-case attributes (payment amount + decline
    # text are on the real webhook; failure_reason is what the LLM diagnoses).
    case_value: int = 50_000
    failure_reason: str = "insufficient_funds"

    @property
    def decline_text(self) -> str:
        return FAILURE_REASON_DECLINE_TEXT[self.failure_reason]


def generate_population(
    seed: int,
    size: int,
    *,
    persona_mix: dict[Persona, float] | None = None,
    response_curves: dict[Persona, dict[Intervention, float]] | None = None,
) -> list[SimulatedCase]:
    """Generate `size` cases deterministically: same (seed, size) -> identical output.

    `persona_mix`/`response_curves` override the frozen `PERSONA_MIX`/
    `BASE_RESPONSE_CURVES` for this call only, defaulting to them otherwise
    -- used by the ticket-16 misspecification stress test
    (app/stress_test.py) to generate a deliberately perturbed population
    without touching either frozen constant.
    """
    curves = response_curves if response_curves is not None else BASE_RESPONSE_CURVES
    rng = random.Random(seed)
    return [_generate_one_case(rng, case_index=i, persona_mix=persona_mix, response_curves=curves) for i in range(size)]


def _generate_one_case(
    rng: random.Random,
    *,
    case_index: int,
    persona_mix: dict[Persona, float] | None,
    response_curves: dict[Persona, dict[Intervention, float]],
) -> SimulatedCase:
    persona = sample_persona(rng, persona_mix=persona_mix)
    # SPIKE: draw value then failure_reason from the same rng so the population
    # stays deterministic given (seed, size).
    case_value = int(min(_CASE_VALUE_MAX, max(_CASE_VALUE_MIN, rng.lognormvariate(_CASE_VALUE_MU, _CASE_VALUE_SIGMA))))
    reason_mix = _FAILURE_REASON_MIX[persona]
    failure_reason = rng.choices(list(reason_mix.keys()), weights=list(reason_mix.values()), k=1)[0]
    return SimulatedCase(
        case_index=case_index,
        hidden=HiddenGroundTruth(customer_segment=persona, outcome_odds=dict(response_curves[persona])),
        case_value=case_value,
        failure_reason=failure_reason,
    )


def resolve_intervention(
    case: SimulatedCase,
    intervention: Intervention,
    *,
    prior_attempts_of_this_intervention: int,
    rng: random.Random,
    incentive_amount: int = 0,
) -> bool:
    """Draw a Bernoulli recovery outcome for `intervention` on `case`, with
    fatigue decay and (ADR-0014) an Incentive uplift applied when this
    execution actually carried one.

    The caller supplies `rng` so outcome draws are reproducible independently
    of population generation.
    """
    base_probability = case.hidden.outcome_odds[intervention]
    probability = response_probability(
        base_probability, prior_attempts_of_this_intervention, incentive_amount=incentive_amount
    )
    return rng.random() < probability
