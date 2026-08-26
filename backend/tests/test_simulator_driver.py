"""Ticket 14: driving the frozen generator through the real ingestion/
execution/reassessment pipeline at volume.

`test_simulator_gateway.py` already checks the outcome-resolution math in
isolation; this file checks that `run_simulated_case`/`run_simulated_population`
actually flow through `app/intake.py` and `app/lifecycle.py` unmodified (no
"is this simulated" branch anywhere in them -- only the `source` tag), and
that a population-level run produces plausible aggregate outcomes.
"""

import random

import pytest

from app.estimator import CustomerSegmentProxy, Estimator, EstimatorCellKey, get_estimator
from app.models import (
    CaseHistoryEntry,
    CaseHistoryEntryType,
    CaseStatus,
    EventSource,
    Intervention,
    RecoveryCase,
    WorkflowType,
)
from app.simulator.generator import generate_population
from app.simulator.personas import PERSONA_MIX
from app.simulator.response_curves import BASE_RESPONSE_CURVES
from app.simulator_driver import _resolve_cycle_outcome, run_simulated_case, run_simulated_population
from app.simulator_gateway import SimulatorGateway


@pytest.fixture(autouse=True)
def fresh_estimator(monkeypatch):
    """The Decision Engine's estimator (app/estimator.py) is a process-wide
    singleton -- reset it per test so one test's simulated outcomes can't bias
    another's decisions."""
    import app.estimator as estimator_module

    monkeypatch.setattr(estimator_module, "_default_estimator", estimator_module.Estimator())


def test_failed_payment_case_is_recorded_with_the_simulated_source_tag(session):
    [simulated] = generate_population(seed=1, size=1)

    result = run_simulated_case(session, simulated, workflow_type=WorkflowType.FAILED_PAYMENT, rng=random.Random(1))

    assert result.case.source == EventSource.SIMULATED
    entry_types = [e.entry_type for e in result.case.history]
    assert CaseHistoryEntryType.CASE_CREATED in entry_types
    assert CaseHistoryEntryType.DECISION in entry_types


def test_halted_subscription_case_is_recorded_with_the_simulated_source_tag(session):
    [simulated] = generate_population(seed=2, size=1)

    result = run_simulated_case(
        session, simulated, workflow_type=WorkflowType.HALTED_SUBSCRIPTION, rng=random.Random(2)
    )

    assert result.case.source == EventSource.SIMULATED
    execution_entries = [e for e in result.case.history if e.entry_type == CaseHistoryEntryType.EXECUTION]
    assert all(e.data["intervention"] == Intervention.RESUME_CHARGE.value for e in execution_entries)


def test_a_recovered_case_feeds_its_outcome_back_into_the_estimator(session):
    """Driving enough cases should update the shared estimator's posterior
    away from its Beta(2,2) cold start for the cells this population's cases
    actually land in -- proving the outcome loop closes (mark_recovered ->
    get_estimator().update), not just that some case reaches RECOVERED
    status. Every case here shares the same (failure_reason,
    customer_segment_proxy) cell: the fixed decline text always diagnoses to
    "insufficient_funds" (FakeLLMClient) and order_count=1 always buckets to
    NEW (app/estimator.py's threshold), per the driver's fixed payload."""
    population = generate_population(seed=3, size=20)
    cold_start = Estimator()

    run_simulated_population(session, population, workflow_type=WorkflowType.FAILED_PAYMENT, rng=random.Random(3))

    def key(intervention: Intervention) -> EstimatorCellKey:
        return EstimatorCellKey(
            failure_reason="insufficient_funds",
            customer_segment_proxy=CustomerSegmentProxy.NEW,
            intervention=intervention,
        )

    warmed_estimates = [get_estimator().estimate(key(i)) for i in (Intervention.PAYMENT_RETRY, Intervention.NO_ACTION)]
    cold_estimate = cold_start.estimate(key(Intervention.PAYMENT_RETRY))
    assert any(estimate != cold_estimate for estimate in warmed_estimates)


def test_case_reaches_a_terminal_or_bounded_state_not_left_mid_cycle(session):
    [simulated] = generate_population(seed=4, size=1)

    result = run_simulated_case(session, simulated, workflow_type=WorkflowType.FAILED_PAYMENT, rng=random.Random(4))

    assert result.case.status in (
        CaseStatus.RECOVERED,
        CaseStatus.STOPPED,
        CaseStatus.ESCALATED,
        CaseStatus.OPEN,  # only if the safety-bound cycle count was hit
    )
    assert result.recovered == (result.case.status == CaseStatus.RECOVERED)


# -- Regression: a rejected NO_ACTION must never resolve an outcome --------


def test_a_sequence_bound_rejected_no_action_is_never_resolved_as_an_outcome(session):
    """`PolicyConfig.max_interventions_per_customer` (app/policy.py) is checked
    against any proposed intervention, NO_ACTION included -- so a NO_ACTION
    decision can itself be sequence-bound-rejected and force-stop the case in
    the same cycle. Resolving an outcome for it anyway would risk flipping an
    already-STOPPED case back to RECOVERED (caught in ticket 14's own code
    review, fixed by `_resolve_cycle_outcome` checking `case.status` first)."""
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT, status=CaseStatus.STOPPED)
    new_entries = [
        CaseHistoryEntry(
            case_id=case.id,
            entry_type=CaseHistoryEntryType.DECISION,
            summary="Decision Engine proposed no_action",
            data={"intervention": Intervention.NO_ACTION.value},
        ),
        CaseHistoryEntry(case_id=case.id, entry_type=CaseHistoryEntryType.CASE_STOPPED, summary="stopped", data={}),
    ]
    [simulated] = generate_population(seed=6, size=1)
    gateway = SimulatorGateway(simulated.hidden, rng=random.Random(6))

    assert _resolve_cycle_outcome(gateway, case, new_entries) is None


# -- Population-level statistical sanity check (ticket 14 acceptance criterion) --


def test_population_recovery_rate_is_plausible_not_saturated_at_either_extreme(session):
    """A case gets multiple reassessment cycles (ADR-0004), so the population's
    aggregate recovery rate is a compounded probability across however many
    attempts each case takes, not a single response-curve value -- it can
    legitimately exceed any individual curve's probability. What it should
    never do is saturate to 0% or 100%, which would mean the SimulatorGateway
    wiring (or the fatigue-decay/retry-ceiling machinery) is broken rather
    than genuinely probabilistic. `test_simulator_gateway.py` covers the
    tighter, non-adaptive, single-attempt statistical match against the
    curves' weighted average -- this test is the full-pipeline complement."""
    population = generate_population(seed=5, size=60)

    outcomes = run_simulated_population(
        session, population, workflow_type=WorkflowType.FAILED_PAYMENT, rng=random.Random(5)
    )

    recovered_rate = sum(o.recovered for o in outcomes) / len(outcomes)
    assert 0.0 < recovered_rate < 1.0
    assert set(PERSONA_MIX) == set(BASE_RESPONSE_CURVES)  # sanity: same personas the driver's population drew from
