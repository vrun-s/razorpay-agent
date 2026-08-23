"""Ticket 07: decide() picks the highest-point-estimate intervention from the
workflow's valid subset, using the shared Estimator as the actual decision source."""

from app.decision import DecisionInput, decide
from app.estimator import CustomerHistory, CustomerSegmentProxy, EstimatorCellKey, get_estimator
from app.models import EventSource, Intervention, RecoveryCase, WorkflowType


def _new_case(workflow_type: WorkflowType = WorkflowType.FAILED_PAYMENT) -> RecoveryCase:
    return RecoveryCase(workflow_type=workflow_type)


def _reliable_history() -> CustomerHistory:
    return CustomerHistory(order_count=10, avg_order_value=50_000, payment_reliability_rate=0.9)


def test_cold_start_prefers_the_workflow_primary_intervention_for_failed_payment():
    output = decide(DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason="evt_test_a"))

    assert output.intervention is Intervention.PAYMENT_RETRY


def test_cold_start_prefers_resume_charge_for_halted_subscription():
    output = decide(
        DecisionInput(
            case=_new_case(WorkflowType.HALTED_SUBSCRIPTION), customer_history=_reliable_history(), failure_reason="evt_test_b"
        )
    )

    assert output.intervention is Intervention.RESUME_CHARGE


def test_a_stronger_posterior_for_no_action_wins():
    failure_reason = "evt_test_c"
    segment = CustomerSegmentProxy.RELIABLE
    estimator = get_estimator()

    # Push NO_ACTION's cell well above PAYMENT_RETRY's cold-start 0.5.
    key = EstimatorCellKey(failure_reason=failure_reason, customer_segment_proxy=segment, intervention=Intervention.NO_ACTION)
    for _ in range(20):
        estimator.update(key, source=EventSource.SIMULATED, success=True)

    output = decide(DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason=failure_reason))

    assert output.intervention is Intervention.NO_ACTION


def test_output_carries_the_estimator_point_estimate_and_uncertainty():
    output = decide(DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason="evt_test_d"))

    assert output.point_estimate == 0.5  # cold-start Beta(2,2) mean, nothing has updated this cell
    assert output.uncertainty > 0


def test_missing_failure_reason_still_produces_a_decision():
    output = decide(DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason=None))

    assert output.intervention in (Intervention.PAYMENT_RETRY, Intervention.NO_ACTION)


def test_output_includes_ticket_08_stopgap_fields():
    output = decide(DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason="evt_test_e"))

    assert isinstance(output.justification, str) and output.justification
    assert output.escalate is False
