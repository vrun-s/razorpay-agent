"""Ticket 16: the misspecification stress test (ADR-0007's robustness check)."""

import pytest

import app.simulator.response_curves as response_curves_module
from app.evaluation import ArmResult, BootstrapResult, EvaluationReport
from app.models import WorkflowType
from app.simulator.generator import generate_population
from app.simulator.personas import PERSONA_MIX, Persona
from app.simulator.response_curves import BASE_RESPONSE_CURVES
from app.stress_test import (
    PERTURBATION_MAGNITUDE,
    ScenarioResult,
    StressTestReport,
    _lift_survives,
    _perturbed_fatigue_decay_rate,
    _perturbed_persona_mix,
    _perturbed_response_curves,
    run_stress_test,
)


@pytest.fixture(autouse=True)
def isolated_estimator(monkeypatch):
    """Same isolation pattern as tests/test_evaluation.py -- the AI arm
    resets the shared Estimator singleton itself, but that must not leak
    into other test files."""
    import app.estimator as estimator_module

    monkeypatch.setattr(estimator_module, "_default_estimator", estimator_module.Estimator())


# -- Perturbation functions ---------------------------------------------------


def test_perturbed_persona_mix_still_sums_to_one():
    mix = _perturbed_persona_mix()

    assert sum(mix.values()) == pytest.approx(1.0)


def test_perturbed_persona_mix_moves_every_persona_by_roughly_20pct():
    mix = _perturbed_persona_mix()

    for persona in PERSONA_MIX:
        relative_change = abs(mix[persona] - PERSONA_MIX[persona]) / PERSONA_MIX[persona]
        assert relative_change == pytest.approx(PERTURBATION_MAGNITUDE, abs=0.05)


def test_perturbed_persona_mix_scales_higher_converting_personas_down():
    mix = _perturbed_persona_mix()

    assert mix[Persona.LOYAL] < PERSONA_MIX[Persona.LOYAL]
    assert mix[Persona.BARGAIN_HUNTER] < PERSONA_MIX[Persona.BARGAIN_HUNTER]


def test_perturbed_persona_mix_scales_lower_converting_personas_up():
    mix = _perturbed_persona_mix()

    assert mix[Persona.NEW] > PERSONA_MIX[Persona.NEW]
    assert mix[Persona.UNRELIABLE_PAYER] > PERSONA_MIX[Persona.UNRELIABLE_PAYER]


def test_perturbed_persona_mix_does_not_mutate_the_frozen_constant():
    _perturbed_persona_mix()

    assert PERSONA_MIX[Persona.LOYAL] == 0.30
    assert PERSONA_MIX[Persona.UNRELIABLE_PAYER] == 0.20


def test_perturbed_response_curves_scales_every_probability_down_20pct():
    curves = _perturbed_response_curves()

    for persona, curve in curves.items():
        for intervention, probability in curve.items():
            assert probability == pytest.approx(BASE_RESPONSE_CURVES[persona][intervention] * 0.8)


def test_perturbed_response_curves_does_not_mutate_the_frozen_constant():
    _perturbed_response_curves()

    assert BASE_RESPONSE_CURVES[Persona.LOYAL][list(BASE_RESPONSE_CURVES[Persona.LOYAL])[0]] > 0.5


def test_perturbed_fatigue_decay_rate_scales_down_20pct_inside_the_context():
    original = response_curves_module.FATIGUE_DECAY_RATE

    with _perturbed_fatigue_decay_rate():
        assert response_curves_module.FATIGUE_DECAY_RATE == pytest.approx(original * 0.8)

    assert response_curves_module.FATIGUE_DECAY_RATE == original


def test_perturbed_fatigue_decay_rate_restores_even_if_the_block_raises():
    original = response_curves_module.FATIGUE_DECAY_RATE

    with pytest.raises(ValueError):
        with _perturbed_fatigue_decay_rate():
            raise ValueError("boom")

    assert response_curves_module.FATIGUE_DECAY_RATE == original


# -- Lift-survival check ------------------------------------------------------


def _report_with_ci_lowers(*lowers: float) -> EvaluationReport:
    empty_arm = ArmResult(name="x", case_results=[])
    return EvaluationReport(
        run_seed=1,
        workflow_type=WorkflowType.FAILED_PAYMENT,
        arms={"no_intervention": empty_arm, "fixed_rule": empty_arm, "offline_optimal": empty_arm, "ai_treatment": empty_arm},
        bootstrap_results=[
            BootstrapResult(baseline_name=f"baseline_{i}", point_estimate=100.0, ci_lower=lower, ci_upper=200.0)
            for i, lower in enumerate(lowers)
        ],
        calibration=[],
    )


def test_lift_survives_when_both_baselines_ci_lower_bounds_are_positive():
    assert _lift_survives(_report_with_ci_lowers(10.0, 5.0)) is True


def test_lift_does_not_survive_when_either_baseline_ci_lower_bound_is_not_positive():
    assert _lift_survives(_report_with_ci_lowers(10.0, -1.0)) is False
    assert _lift_survives(_report_with_ci_lowers(-1.0, 10.0)) is False
    assert _lift_survives(_report_with_ci_lowers(0.0, 10.0)) is False


# -- StressTestReport ----------------------------------------------------------


def _report_stub() -> EvaluationReport:
    return _report_with_ci_lowers(1.0, 1.0)


def test_passed_requires_at_least_2_of_3_scenarios_to_survive():
    report = StressTestReport(
        baseline=_report_stub(),
        scenarios=[
            ScenarioResult(name="a", report=_report_stub(), survived=True),
            ScenarioResult(name="b", report=_report_stub(), survived=True),
            ScenarioResult(name="c", report=_report_stub(), survived=False),
        ],
    )

    assert report.survived_count == 2
    assert report.passed is True


def test_a_failed_stress_test_is_still_fully_reported_not_hidden():
    """ADR-0007/ticket 16: "a failed stress test is documented, not hidden" --
    every scenario's full report stays on the object regardless of outcome."""
    report = StressTestReport(
        baseline=_report_stub(),
        scenarios=[
            ScenarioResult(name="a", report=_report_stub(), survived=False),
            ScenarioResult(name="b", report=_report_stub(), survived=False),
            ScenarioResult(name="c", report=_report_stub(), survived=True),
        ],
    )

    assert report.passed is False
    assert len(report.scenarios) == 3
    assert all(scenario.report is not None for scenario in report.scenarios)


# -- End-to-end run_stress_test ------------------------------------------------


def test_run_stress_test_runs_all_three_scenarios_plus_a_baseline():
    cases = generate_population(seed=10, size=60)

    report = run_stress_test(cases, run_seed=10, workflow_type=WorkflowType.FAILED_PAYMENT, n_bootstrap_resamples=200)

    assert {s.name for s in report.scenarios} == {"persona_mix", "response_curve_elasticities", "fatigue_decay_rate"}
    assert report.baseline.arms  # a real EvaluationReport, not a stub


def test_run_stress_test_leaves_the_fatigue_decay_rate_unperturbed_afterward():
    original = response_curves_module.FATIGUE_DECAY_RATE
    cases = generate_population(seed=11, size=20)

    run_stress_test(cases, run_seed=11, n_bootstrap_resamples=100)

    assert response_curves_module.FATIGUE_DECAY_RATE == original


def test_run_stress_test_is_deterministic_given_the_same_seed():
    cases = generate_population(seed=12, size=30)

    first = run_stress_test(cases, run_seed=12, n_bootstrap_resamples=200)
    second = run_stress_test(cases, run_seed=12, n_bootstrap_resamples=200)

    assert first.passed == second.passed
    assert [s.survived for s in first.scenarios] == [s.survived for s in second.scenarios]
    assert [s.report.arms["ai_treatment"].total_nrr for s in first.scenarios] == [
        s.report.arms["ai_treatment"].total_nrr for s in second.scenarios
    ]
