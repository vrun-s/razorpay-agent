"""Ticket 15: the evaluation harness, implementing ADR-0013's contract
directly. Each test cites the ADR-0013 clause it checks.
"""

import inspect
import random

import pytest

from app.allocator import AllocationCandidate, BudgetLedger, StreamingAllocator
from app.estimator import get_estimator
from app.models import Intervention, WorkflowType
from app.simulator.generator import generate_population
from app.evaluation import (
    ArmResult,
    CaseResult,
    DEV_SIZE,
    HELD_OUT_SIZE,
    VALIDATION_SIZE,
    _EVAL_RESERVE_RATIO,
    _case_seed,
    _percentile,
    _recovers_within_attempt_budget,
    bootstrap_gap_ci,
    calibration_curve,
    generate_dataset_splits,
    run_ai_treatment_arm,
    run_evaluation,
    run_fixed_rule_arm,
    run_no_intervention_arm,
    run_offline_optimal_arm,
)
from app.simulator_driver import ResolvedDecision


@pytest.fixture(autouse=True)
def isolated_estimator(monkeypatch):
    """The AI arm resets the shared Estimator singleton itself (required for
    determinism), but that mutation must not leak into other test files --
    monkeypatch reverts it after each test, same pattern as
    tests/test_simulator_driver.py."""
    import app.estimator as estimator_module

    monkeypatch.setattr(estimator_module, "_default_estimator", estimator_module.Estimator())


# -- Dataset splits (ADR-0013) -----------------------------------------------


def test_default_split_sizes_match_the_adr():
    splits = generate_dataset_splits(seed=1, dev_size=5, validation_size=3, held_out_size=2)

    assert len(splits.dev) == 5
    assert len(splits.validation) == 3
    assert len(splits.held_out) == 2


def test_default_sizes_are_300_150_200():
    assert (DEV_SIZE, VALIDATION_SIZE, HELD_OUT_SIZE) == (300, 150, 200)


def test_splits_are_a_fixed_sequential_partition_of_one_population():
    """ADR-0013: "generated once under a fixed top-level seed and partitioned
    by a fixed sequential rule... so the split itself is reproducible from
    the seed alone." """
    population = generate_population(seed=42, size=10)
    splits = generate_dataset_splits(seed=42, dev_size=4, validation_size=3, held_out_size=3)

    assert splits.dev == population[:4]
    assert splits.validation == population[4:7]
    assert splits.held_out == population[7:10]


def test_dataset_splits_are_deterministic_given_a_seed():
    first = generate_dataset_splits(seed=99, dev_size=10, validation_size=5, held_out_size=5)
    second = generate_dataset_splits(seed=99, dev_size=10, validation_size=5, held_out_size=5)

    assert first == second


# -- Per-case seed pairing (ADR-0013) ----------------------------------------


def test_case_seed_is_deterministic():
    assert _case_seed(7, 3) == _case_seed(7, 3)


def test_case_seed_differs_across_case_index_and_run_seed():
    assert _case_seed(7, 3) != _case_seed(7, 4)
    assert _case_seed(7, 3) != _case_seed(8, 3)


# -- Reserve-free harness (ADR-0016) ---------------------------------------


def test_eval_arms_run_without_a_budget_reserve():
    """ADR-0016: the single-cell eval harness has no cross-case quality
    signal to ration a reserve on, so every arm spends first-come-first-
    served. A low-quality candidate that fits the remaining budget is funded
    without the reserve-quality gate ever running -- with a 1/3 reserve the
    same candidate is declined and the budget it needed is stranded, which
    uniquely handicaps the truthfully-estimated AI arm against fixed_rule's
    hardcoded neutral 0.5."""
    assert _EVAL_RESERVE_RATIO == 0.0

    ledger = BudgetLedger(recovery_budget=100_000, reserve_ratio=_EVAL_RESERVE_RATIO)
    decision = StreamingAllocator(ledger).decide(
        AllocationCandidate(case_id="c1", point_estimate=0.20, uncertainty=0.10, incentive_amount=100_000)
    )

    assert decision.funded
    assert decision.reserved == 0


# -- No-intervention arm ------------------------------------------------------


def test_no_intervention_arm_never_incurs_incentive_cost():
    cases = generate_population(seed=1, size=20)

    arm = run_no_intervention_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=1)

    assert all(result.incentive_cost == 0 for result in arm.case_results)
    assert all(result.intervention == Intervention.NO_ACTION for result in arm.case_results)


def test_no_intervention_arm_nrr_equals_gross_recovered():
    cases = generate_population(seed=2, size=20)

    arm = run_no_intervention_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=2)

    for result in arm.case_results:
        assert result.nrr == result.gross_recovered
        assert result.gross_recovered in (0, 50_000)


# -- Fixed-rule arm -----------------------------------------------------------


def test_fixed_rule_arm_always_proposes_the_workflows_cost_bearing_intervention():
    cases = generate_population(seed=3, size=10)

    failed_payment_arm = run_fixed_rule_arm(
        cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=3
    )
    halted_subscription_arm = run_fixed_rule_arm(
        cases, workflow_type=WorkflowType.HALTED_SUBSCRIPTION, case_value=50_000, run_seed=3
    )

    assert all(r.intervention == Intervention.PAYMENT_RETRY for r in failed_payment_arm.case_results)
    assert all(r.intervention == Intervention.RESUME_CHARGE for r in halted_subscription_arm.case_results)


def test_fixed_rule_arm_incurs_a_flat_5pct_discount_cost_per_attempt():
    """ADR-0013: "a flat 5% discount." A case with at least one attempt (won
    or lost) pays 5% of case_value per attempt made."""
    cases = generate_population(seed=4, size=30)

    arm = run_fixed_rule_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=100_000, run_seed=4)

    attempted = [r for r in arm.case_results if r.incentive_cost > 0]
    assert attempted  # at least some cases got at least one attempt
    for result in attempted:
        assert result.incentive_cost % 5_000 == 0  # 5% of 100_000 per attempt, always a whole multiple


def test_fixed_rule_arm_passes_its_incentive_amount_into_the_gateways_resolve_call(monkeypatch):
    """ticket 19/ADR-0014: fixed_rule's flat discount is real money now, so
    its execution draws should get the same simulator uplift ai_treatment's
    funded proposals do -- not a cost with no effect on the outcome."""
    from app.simulator_gateway import SimulatorGateway

    seen_incentive_amounts: list[int] = []
    original_resolve = SimulatorGateway.resolve

    def _recording_resolve(self, intervention, *, incentive_amount=0):
        seen_incentive_amounts.append(incentive_amount)
        return original_resolve(self, intervention, incentive_amount=incentive_amount)

    monkeypatch.setattr(SimulatorGateway, "resolve", _recording_resolve)

    cases = generate_population(seed=17, size=10)
    run_fixed_rule_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=100_000, run_seed=17)

    assert seen_incentive_amounts  # at least one attempt was made
    assert any(amount > 0 for amount in seen_incentive_amounts)


def test_fixed_rule_arm_stops_retrying_once_the_sequence_bound_is_hit():
    """The same Policy Engine every other arm uses (app/policy.py) caps
    max_payment_retries -- a tight policy should visibly cap attempts."""
    from app.policy import PolicyConfig

    tight_policy = PolicyConfig(
        max_discount_pct=20.0, max_payment_retries=1, max_interventions_per_customer=10, recovery_budget=10_000_000
    )
    cases = generate_population(seed=5, size=20)

    arm = run_fixed_rule_arm(
        cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=100_000, run_seed=5, policy=tight_policy
    )

    max_incentive = 5_000  # 5% of 100_000, exactly one attempt allowed
    assert all(result.incentive_cost <= max_incentive for result in arm.case_results)


# -- Offline-optimal arm -------------------------------------------------------


def test_offline_optimal_arm_never_incurs_incentive_cost():
    cases = generate_population(seed=6, size=20)

    arm = run_offline_optimal_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=6)

    assert all(result.incentive_cost == 0 for result in arm.case_results)


def test_offline_optimal_recovers_whenever_any_candidate_would_within_budget():
    """Cross-checks `run_offline_optimal_arm`'s aggregate decision against
    `_recovers_within_attempt_budget` computed directly per candidate
    (ADR-0013 pairing: same per-case seed) -- not a black-box re-assertion
    of the arm's own internal call to that same helper."""
    cases = generate_population(seed=7, size=15)
    run_seed = 7

    arm = run_offline_optimal_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=run_seed)

    for simulated, result in zip(cases, arm.case_results):
        seed = _case_seed(run_seed, simulated.case_index)
        expected_recovered = any(
            _recovers_within_attempt_budget(simulated, candidate, seed, max_attempts=10)
            for candidate in (Intervention.PAYMENT_RETRY, Intervention.NO_ACTION)
        )
        assert result.recovered == expected_recovered


def test_offline_optimal_is_a_plausible_upper_bound_over_a_population():
    """Structural sanity, not a per-case guarantee (a small sample can have
    lucky/unlucky draws): in aggregate, over a large enough population,
    offline-optimal's total NRR should be at least as large as fixed-rule's
    (same attempt budget, but offline-optimal additionally gets NO_ACTION as
    a free-to-try candidate and perfect foresight of which one wins)."""
    cases = generate_population(seed=8, size=200)

    offline = run_offline_optimal_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=8)
    fixed_rule = run_fixed_rule_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=8)

    assert offline.total_nrr >= fixed_rule.total_nrr


# -- AI treatment arm -----------------------------------------------------------


def test_ai_treatment_arm_resets_the_estimator_before_running():
    """`reset_estimator()` (app/estimator.py) swaps the process-wide
    singleton for a fresh instance -- proof it ran is the singleton's
    *identity* changing, which holds regardless of what this run's own case
    happens to decide, unlike asserting on any specific cell's value (whose
    resting state after the run legitimately depends on that case's own
    outcome, not just on whether the reset happened)."""
    estimator_before = get_estimator()
    cases = generate_population(seed=9, size=1)

    run_ai_treatment_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=9)

    assert get_estimator() is not estimator_before


def test_ai_treatment_arm_produces_resolved_decisions_for_calibration():
    cases = generate_population(seed=10, size=10)

    arm = run_ai_treatment_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=10)

    assert arm.resolved_decisions
    for decision in arm.resolved_decisions:
        assert 0.0 <= decision.point_estimate <= 1.0


# -- Ticket 19: real incentive cost flows through to the AI arm (ADR-0014) --


def test_ai_treatment_arm_carries_a_real_incentive_cost():
    """The old always-0 gap (ADR-0010) is gone: at least one case in a
    reasonably-sized run pays the same case-value-scaled incentive rate
    fixed_rule does, whenever its proposal was funded."""
    cases = generate_population(seed=15, size=60)

    arm = run_ai_treatment_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=15)

    assert any(result.incentive_cost > 0 for result in arm.case_results)
    for result in arm.case_results:
        assert result.incentive_cost % 2_500 == 0  # whole multiples of 5% of 50_000 per funded attempt


def test_ai_treatment_arm_does_not_leak_spend_across_separate_calls():
    """Ticket 19: each call gets its own fresh StreamingAllocator -- back-to-
    back calls (dev/validation/held-out within one evaluation run, or two
    separate runs) must not see each other's ledger spend."""
    cases = generate_population(seed=16, size=40)

    first = run_ai_treatment_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=16)
    second = run_ai_treatment_arm(cases, workflow_type=WorkflowType.FAILED_PAYMENT, case_value=50_000, run_seed=16)

    assert [r.incentive_cost for r in first.case_results] == [r.incentive_cost for r in second.case_results]
    assert [r.recovered for r in first.case_results] == [r.recovered for r in second.case_results]


# -- Bootstrap CI (ADR-0013 exact procedure) -----------------------------------


def test_bootstrap_default_resample_count_matches_the_adr():
    signature = inspect.signature(bootstrap_gap_ci)
    assert signature.parameters["n_resamples"].default == 10_000


def test_bootstrap_point_estimate_is_the_mean_of_the_actual_paired_gaps():
    ai = ArmResult(
        name="ai_treatment",
        case_results=[
            CaseResult(case_index=0, intervention=Intervention.PAYMENT_RETRY, recovered=True, gross_recovered=100, incentive_cost=0),
            CaseResult(case_index=1, intervention=Intervention.PAYMENT_RETRY, recovered=False, gross_recovered=0, incentive_cost=0),
        ],
    )
    baseline = ArmResult(
        name="no_intervention",
        case_results=[
            CaseResult(case_index=0, intervention=Intervention.NO_ACTION, recovered=False, gross_recovered=0, incentive_cost=0),
            CaseResult(case_index=1, intervention=Intervention.NO_ACTION, recovered=False, gross_recovered=0, incentive_cost=0),
        ],
    )

    result = bootstrap_gap_ci(ai, baseline, n_resamples=500, rng=random.Random(1))

    assert result.point_estimate == pytest.approx(50.0)  # gaps = [100, 0], mean 50
    assert result.ci_lower <= result.point_estimate <= result.ci_upper


def test_bootstrap_is_deterministic_given_the_same_rng_seed():
    ai = ArmResult(
        name="ai_treatment",
        case_results=[
            CaseResult(case_index=i, intervention=Intervention.PAYMENT_RETRY, recovered=i % 2 == 0, gross_recovered=100 if i % 2 == 0 else 0, incentive_cost=0)
            for i in range(20)
        ],
    )
    baseline = ArmResult(
        name="fixed_rule",
        case_results=[
            CaseResult(case_index=i, intervention=Intervention.PAYMENT_RETRY, recovered=False, gross_recovered=0, incentive_cost=5)
            for i in range(20)
        ],
    )

    first = bootstrap_gap_ci(ai, baseline, n_resamples=1000, rng=random.Random(42))
    second = bootstrap_gap_ci(ai, baseline, n_resamples=1000, rng=random.Random(42))

    assert first == second


# -- Percentile helper ---------------------------------------------------------


def test_percentile_matches_known_values():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    assert _percentile(values, 0) == 1.0
    assert _percentile(values, 50) == 3.0
    assert _percentile(values, 100) == 5.0


# -- Calibration curve ----------------------------------------------------------


def test_calibration_curve_buckets_predicted_vs_actual():
    decisions = [
        ResolvedDecision(point_estimate=0.15, recovered=True),
        ResolvedDecision(point_estimate=0.18, recovered=False),
        ResolvedDecision(point_estimate=0.85, recovered=True),
    ]

    buckets = calibration_curve(decisions, n_buckets=10)

    low_bucket = next(b for b in buckets if b.bucket_low == pytest.approx(0.1))
    assert low_bucket.count == 2
    assert low_bucket.observed_rate == pytest.approx(0.5)
    high_bucket = next(b for b in buckets if b.bucket_low == pytest.approx(0.8))
    assert high_bucket.count == 1
    assert high_bucket.observed_rate == pytest.approx(1.0)


def test_calibration_curve_omits_empty_buckets():
    decisions = [ResolvedDecision(point_estimate=0.55, recovered=True)]

    buckets = calibration_curve(decisions, n_buckets=10)

    assert len(buckets) == 1


# -- Top-level run_evaluation (ticket 15's determinism acceptance criterion) --


def test_rerunning_with_the_same_seed_reproduces_the_same_headline_numbers():
    cases = generate_population(seed=11, size=25)

    first = run_evaluation(cases, run_seed=123, workflow_type=WorkflowType.FAILED_PAYMENT, n_bootstrap_resamples=300)
    second = run_evaluation(cases, run_seed=123, workflow_type=WorkflowType.FAILED_PAYMENT, n_bootstrap_resamples=300)

    assert {name: arm.total_nrr for name, arm in first.arms.items()} == {
        name: arm.total_nrr for name, arm in second.arms.items()
    }
    assert first.bootstrap_results == second.bootstrap_results
    assert first.calibration == second.calibration


def test_a_dev_run_does_not_change_a_subsequent_held_out_runs_result():
    """No code path feeds one run's results back into another's -- the
    estimator is reset cold at the start of every `run_evaluation` call
    (this module's docstring), so running dev first must not perturb a
    held-out run with the same cases/seed."""
    cases = generate_population(seed=12, size=20)

    run_evaluation(cases, run_seed=55, n_bootstrap_resamples=100)  # a prior "dev" run
    held_out_after_dev = run_evaluation(cases, run_seed=55, n_bootstrap_resamples=100)
    held_out_alone = run_evaluation(cases, run_seed=55, n_bootstrap_resamples=100)

    assert {n: a.total_nrr for n, a in held_out_after_dev.arms.items()} == {
        n: a.total_nrr for n, a in held_out_alone.arms.items()
    }


def test_pct_of_offline_optimal_captured_is_a_plausible_fraction():
    cases = generate_population(seed=13, size=100)

    report = run_evaluation(cases, run_seed=13, n_bootstrap_resamples=100)

    assert 0.0 <= report.pct_of_offline_optimal_captured() <= 1.0


def test_incremental_recovery_matches_the_bootstrap_point_estimate():
    cases = generate_population(seed=14, size=30)

    report = run_evaluation(cases, run_seed=14, n_bootstrap_resamples=200)

    for result in report.bootstrap_results:
        assert report.incremental_recovery(result.baseline_name) == result.point_estimate
