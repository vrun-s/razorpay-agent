import ast
import random
from pathlib import Path

import pytest

from app.models import Intervention
from app.simulator.generator import generate_population, resolve_intervention
from app.simulator.personas import PERSONA_MIX, Persona
from app.simulator.response_curves import (
    BASE_RESPONSE_CURVES,
    INCENTIVE_UPLIFT,
    SIMULATOR_VERSION,
    decayed_probability,
    response_probability,
)

SIMULATOR_DIR = Path(__file__).resolve().parent.parent / "app" / "simulator"
DECISION_ENGINE_FILE = SIMULATOR_DIR.parent / "decision.py"
POLICY_ENGINE_FILE = SIMULATOR_DIR.parent / "policy.py"


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_persona_mix_covers_every_persona_and_sums_to_one():
    assert set(PERSONA_MIX.keys()) == set(Persona)
    assert sum(PERSONA_MIX.values()) == pytest.approx(1.0)


def test_every_persona_has_a_fully_specified_response_curve():
    for persona in Persona:
        curve = BASE_RESPONSE_CURVES[persona]
        assert set(curve.keys()) == set(Intervention)
        for probability in curve.values():
            assert 0.0 < probability < 1.0


def test_simulator_version_is_set():
    assert SIMULATOR_VERSION


def test_simulator_version_bumped_for_ticket_19_incentive_uplift():
    """ADR-0014: the flat incentive-uplift mechanism is a response-curve
    version bump, invalidating comparability with any prior evaluation run."""
    assert SIMULATOR_VERSION == "response-curves-v2"


# -- Ticket 19: flat incentive uplift (ADR-0014) -----------------------------


def test_response_probability_with_no_incentive_matches_decayed_probability():
    for prior_attempts in range(3):
        assert response_probability(0.4, prior_attempts) == decayed_probability(0.4, prior_attempts)


def test_response_probability_adds_the_uplift_when_incentive_amount_is_positive():
    base = 0.4
    without = response_probability(base, 0, incentive_amount=0)
    with_incentive = response_probability(base, 0, incentive_amount=2_500)

    assert with_incentive == pytest.approx(without + INCENTIVE_UPLIFT)


def test_response_probability_is_clamped_to_one():
    assert response_probability(0.95, 0, incentive_amount=1) == pytest.approx(1.0)


def test_response_probability_uplift_is_uniform_regardless_of_incentive_size():
    # Only *whether* incentive_amount > 0 matters, not its magnitude --
    # ADR-0014's flat uplift, not a learned discount-sensitivity curve.
    assert response_probability(0.4, 0, incentive_amount=1) == response_probability(0.4, 0, incentive_amount=999_999)


def test_generate_population_is_deterministic_for_a_fixed_seed():
    first = generate_population(seed=42, size=25)
    second = generate_population(seed=42, size=25)

    assert first == second


def test_generate_population_differs_across_seeds():
    a = generate_population(seed=1, size=25)
    b = generate_population(seed=2, size=25)

    assert a != b


def test_generated_case_hidden_ground_truth_covers_every_intervention():
    [case] = generate_population(seed=7, size=1)

    assert case.hidden.customer_segment in Persona
    assert set(case.hidden.outcome_odds.keys()) == set(Intervention)
    for probability in case.hidden.outcome_odds.values():
        assert 0.0 <= probability <= 1.0


def test_persona_mix_is_respected_over_a_large_population():
    population = generate_population(seed=123, size=4000)

    counts = {persona: 0 for persona in Persona}
    for case in population:
        counts[case.hidden.customer_segment] += 1

    for persona, expected_share in PERSONA_MIX.items():
        observed_share = counts[persona] / len(population)
        assert observed_share == pytest.approx(expected_share, abs=0.03)


def test_fatigue_decay_reduces_probability_monotonically_with_repetition():
    base = 0.5

    probabilities = [decayed_probability(base, prior_attempts) for prior_attempts in range(5)]

    assert probabilities == sorted(probabilities, reverse=True)
    assert probabilities[0] == pytest.approx(base)
    assert all(probability > 0 for probability in probabilities)


def test_resolve_intervention_is_deterministic_given_an_rng_seed():
    [case] = generate_population(seed=3, size=1)

    def draw_outcomes() -> list[bool]:
        return [
            resolve_intervention(
                case, Intervention.PAYMENT_RETRY, prior_attempts_of_this_intervention=i, rng=random.Random(99)
            )
            for i in range(3)
        ]

    assert draw_outcomes() == draw_outcomes()


def test_simulator_package_has_no_dependency_on_decision_or_policy_engine_code():
    """Ticket-02 acceptance criterion: no import from, and not imported by, any Decision Engine code."""
    for path in SIMULATOR_DIR.glob("*.py"):
        for name in _imported_module_names(path):
            assert not name.startswith("app.decision"), f"{path.name} imports Decision Engine code: {name}"
            assert not name.startswith("app.policy"), f"{path.name} imports Policy Engine code: {name}"


def test_decision_and_policy_engines_do_not_import_the_simulator():
    for path in (DECISION_ENGINE_FILE, POLICY_ENGINE_FILE):
        for name in _imported_module_names(path):
            assert not name.startswith("app.simulator"), f"{path.name} imports the simulator: {name}"


# -- ticket 16: optional persona_mix/response_curves overrides --------------


def test_generate_population_with_no_override_matches_default_behavior():
    default = generate_population(seed=1, size=10)
    overridden = generate_population(seed=1, size=10, persona_mix=None, response_curves=None)

    assert default == overridden


def test_generate_population_respects_an_overridden_persona_mix():
    skewed_mix = {Persona.LOYAL: 0.0, Persona.BARGAIN_HUNTER: 0.0, Persona.NEW: 0.0, Persona.UNRELIABLE_PAYER: 1.0}

    population = generate_population(seed=1, size=50, persona_mix=skewed_mix)

    assert all(case.hidden.customer_segment == Persona.UNRELIABLE_PAYER for case in population)


def test_generate_population_respects_overridden_response_curves():
    flat_curves = {persona: {intervention: 0.9 for intervention in Intervention} for persona in Persona}

    population = generate_population(seed=1, size=20, response_curves=flat_curves)

    assert all(
        probability == 0.9 for case in population for probability in case.hidden.outcome_odds.values()
    )


def test_overriding_response_curves_leaves_the_frozen_constant_untouched():
    generate_population(seed=1, size=5, response_curves={p: {i: 0.5 for i in Intervention} for p in Persona})

    assert BASE_RESPONSE_CURVES[Persona.LOYAL][Intervention.PAYMENT_RETRY] == 0.55
