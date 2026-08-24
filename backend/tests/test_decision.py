"""Ticket 07/08: decide() picks the highest-point-estimate intervention from
the workflow's valid subset, using the shared Estimator as the actual
decision source, then attaches the LLM's justification/escalate roles
(app/llm.py) without ever letting them touch point_estimate/uncertainty."""

from app.decision import DecisionInput, decide
from app.estimator import CustomerHistory, CustomerSegmentProxy, EstimatorCellKey, get_estimator
from app.llm import FakeLLMClient
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


def test_output_carries_a_generated_justification_and_defaults_escalate_false():
    output = decide(DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason="evt_test_e"))

    assert isinstance(output.justification, str) and output.justification
    assert output.escalate is False  # no qualitative_signal was given


# -- ticket 08: LLM-bounded roles --------------------------------------------


class _SpyLLMClient:
    """Records calls and returns fixed, distinctive values -- proves decide()
    delegates to the injected client rather than building its own strings."""

    def __init__(self, *, escalate: bool = False) -> None:
        self.justification_calls: list[dict] = []
        self.escalation_calls: list[str] = []
        self._escalate = escalate

    def diagnose_failure_reason(self, *, decline_text: str) -> str:
        return "unknown"

    def generate_justification(self, *, intervention, point_estimate, uncertainty, segment, failure_reason) -> str:
        self.justification_calls.append(
            {
                "intervention": intervention,
                "point_estimate": point_estimate,
                "uncertainty": uncertainty,
                "segment": segment,
                "failure_reason": failure_reason,
            }
        )
        return "SPY_JUSTIFICATION"

    def flag_escalation(self, *, signal_text: str) -> bool:
        self.escalation_calls.append(signal_text)
        return self._escalate


def test_decide_delegates_justification_to_the_injected_llm_client():
    spy = _SpyLLMClient()

    output = decide(
        DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason="evt_test_f"),
        llm_client=spy,
    )

    assert output.justification == "SPY_JUSTIFICATION"
    assert len(spy.justification_calls) == 1
    assert spy.justification_calls[0]["failure_reason"] == "evt_test_f"


def test_decide_never_calls_flag_escalation_without_a_qualitative_signal():
    spy = _SpyLLMClient(escalate=True)

    output = decide(
        DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason="evt_test_g"),
        llm_client=spy,
    )

    assert output.escalate is False
    assert spy.escalation_calls == []


def test_decide_flags_escalation_from_a_qualitative_signal():
    spy = _SpyLLMClient(escalate=True)

    output = decide(
        DecisionInput(
            case=_new_case(),
            customer_history=_reliable_history(),
            failure_reason="evt_test_h",
            qualitative_signal="I'm furious, this is unacceptable!",
        ),
        llm_client=spy,
    )

    assert output.escalate is True
    assert spy.escalation_calls == ["I'm furious, this is unacceptable!"]


def test_a_crafted_angry_signal_triggers_escalation_via_the_real_fake_client():
    output = decide(
        DecisionInput(
            case=_new_case(),
            customer_history=_reliable_history(),
            failure_reason="evt_test_i",
            qualitative_signal="This is ridiculous, I've been charged twice and no one is helping me!",
        ),
        llm_client=FakeLLMClient(),
    )

    assert output.escalate is True


def test_point_estimate_and_uncertainty_are_bit_for_bit_the_estimators_value_regardless_of_llm_client():
    from app.decision import resolve_cell_key

    decision_input = DecisionInput(case=_new_case(), customer_history=_reliable_history(), failure_reason="evt_test_j")
    raw_estimate = get_estimator().estimate(resolve_cell_key(decision_input, Intervention.PAYMENT_RETRY))

    class _TamperingLLMClient:
        def diagnose_failure_reason(self, *, decline_text: str) -> str:
            return "unknown"

        def generate_justification(self, *, intervention, point_estimate, uncertainty, segment, failure_reason) -> str:
            return f"tampered {point_estimate + 999}"  # would corrupt the number if decide() used this

        def flag_escalation(self, *, signal_text: str) -> bool:
            return True

    output = decide(decision_input, llm_client=_TamperingLLMClient())

    assert output.point_estimate == raw_estimate.point_estimate
    assert output.uncertainty == raw_estimate.uncertainty
