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


def sample_persona(rng: random.Random) -> Persona:
    return rng.choices(_PERSONAS_IN_ORDER, weights=_WEIGHTS_IN_ORDER, k=1)[0]
