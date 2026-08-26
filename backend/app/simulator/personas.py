"""Customer Segment persona mix for the Synthetic Merchant Simulator (ticket 02).

Pure and deterministic-given-a-seed: sampling a persona only ever touches the
`random.Random` instance passed in, nothing external.
"""

from __future__ import annotations

import random
from enum import StrEnum


class Persona(StrEnum):
    """Simulator ground truth (CONTEXT.md: Customer Segment). Never exposed to the Decision Engine."""

    LOYAL = "loyal"
    BARGAIN_HUNTER = "bargain_hunter"
    NEW = "new"
    UNRELIABLE_PAYER = "unreliable_payer"


# Population mix. Must sum to 1.0 -- enforced by test_simulator.py.
PERSONA_MIX: dict[Persona, float] = {
    Persona.LOYAL: 0.30,
    Persona.BARGAIN_HUNTER: 0.25,
    Persona.NEW: 0.25,
    Persona.UNRELIABLE_PAYER: 0.20,
}

_PERSONAS_IN_ORDER = list(PERSONA_MIX.keys())
_WEIGHTS_IN_ORDER = [PERSONA_MIX[persona] for persona in _PERSONAS_IN_ORDER]


def sample_persona(rng: random.Random, *, persona_mix: dict[Persona, float] | None = None) -> Persona:
    """`persona_mix` overrides the frozen `PERSONA_MIX` for this call only --
    used by the ticket-16 misspecification stress test (app/stress_test.py)
    to sample from a deliberately perturbed mix without touching the frozen
    constant itself. Weights need not sum to 1.0 (`random.choices` treats
    them as relative)."""
    mix = persona_mix if persona_mix is not None else PERSONA_MIX
    return rng.choices(list(mix.keys()), weights=list(mix.values()), k=1)[0]
