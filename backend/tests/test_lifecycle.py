"""Ticket 06: case lifecycle -- reassessment loop, fatigue, sequence-bound stop."""

from datetime import datetime, timedelta, timezone

from app.gateway import FakeGateway
from app.lifecycle import due_cases, override_case, resolve_case_manually, run_decision_cycle, run_sweep
from app.llm import FakeLLMClient
from app.models import (
    CaseHistoryEntry,
    CaseHistoryEntryType,
    CaseStatus,
    Intervention,
    RecoveryCase,
    WorkflowType,
)
from app.policy import PolicyConfig


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _case_with_prior_payment_retries(session, count: int) -> RecoveryCase:
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT, external_reference_id="pay_lifecycle1")
    session.add(case)
    for _ in range(count):
        session.add(
            CaseHistoryEntry(
                case_id=case.id,
                entry_type=CaseHistoryEntryType.EXECUTION,
                summary="prior payment retry",
                data={"intervention": Intervention.PAYMENT_RETRY.value},
            )
        )
    session.commit()
    session.refresh(case)
    return case


def test_case_exceeding_max_payment_retries_is_force_stopped(session):
    case = _case_with_prior_payment_retries(session, count=3)
    tight_policy = PolicyConfig(
        max_discount_pct=20.0, max_payment_retries=3, max_interventions_per_customer=10, recovery_budget=10_000_00
    )

    result = run_decision_cycle(session, FakeGateway(), case, policy=tight_policy)

    assert result.status == CaseStatus.STOPPED
    assert result.response_window_expires_at is None

    entry_types = [entry.entry_type for entry in result.history]
    assert CaseHistoryEntryType.CASE_STOPPED in entry_types
    # Still only the 3 prior executions -- the over-the-limit 4th retry never ran.
    assert entry_types.count(CaseHistoryEntryType.EXECUTION) == 3

    stop_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.CASE_STOPPED)
    assert "max_payment_retries" in stop_entry.data["reason"]


def test_case_under_the_limit_is_not_stopped(session):
    case = _case_with_prior_payment_retries(session, count=1)
    policy = PolicyConfig(max_discount_pct=20.0, max_payment_retries=3, max_interventions_per_customer=10, recovery_budget=10_000_00)

    result = run_decision_cycle(session, FakeGateway(), case, policy=policy)

    assert result.status == CaseStatus.OPEN
    assert result.response_window_expires_at is not None


def test_decision_entry_records_the_estimator_cell_used(session):
    # Ticket 06's own fatigue stopgap (decision.expected_effect) is gone as
    # promised, superseded by ticket 07's real estimator; case-local fatigue
    # re-weighting on top of the (cross-case) posterior is a disclosed gap
    # for a later ticket, not reintroduced here. This checks the DECISION
    # entry now carries the estimator's cell (segment/failure_reason) instead.
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)

    result = run_decision_cycle(session, FakeGateway(), case)

    decision_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.DECISION)
    assert decision_entry.data["customer_segment_proxy"]
    assert decision_entry.data["failure_reason"]
    assert decision_entry.data["point_estimate"] == 0.5
    assert decision_entry.data["uncertainty"] > 0


def test_failure_reason_is_diagnosed_from_the_payments_decline_text(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)
    payment = {"amount": 50_000, "error_code": "BAD_REQUEST_ERROR", "error_description": "insufficient funds in account"}

    result = run_decision_cycle(session, FakeGateway(), case, payment=payment, llm_client=FakeLLMClient())

    decision_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.DECISION)
    assert decision_entry.data["failure_reason"] == "insufficient_funds"


def test_failure_reason_diagnosis_is_reused_when_a_later_cycle_has_no_decline_text(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)
    payment = {"amount": 50_000, "error_code": "BAD_REQUEST_ERROR", "error_description": "card expired"}
    run_decision_cycle(session, FakeGateway(), case, payment=payment, llm_client=FakeLLMClient())
    session.refresh(case)

    # A later reassessment (e.g. scheduled sweep) with no fresh payment payload
    # still has a diagnosis to fall back on -- the first cycle's own.
    result = run_decision_cycle(session, FakeGateway(), case, llm_client=FakeLLMClient())

    decisions = [e for e in result.history if e.entry_type == CaseHistoryEntryType.DECISION]
    assert decisions[-1].data["failure_reason"] == "expired_card"


def test_halted_subscription_never_gets_a_diagnosed_failure_reason(session):
    case = RecoveryCase(workflow_type=WorkflowType.HALTED_SUBSCRIPTION)
    # error_code/description are meaningless for this workflow even if present.
    payment = {"error_code": "X", "error_description": "insufficient funds"}

    result = run_decision_cycle(session, FakeGateway(), case, payment=payment, llm_client=FakeLLMClient())

    decision_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.DECISION)
    assert decision_entry.data["failure_reason"] == "unknown"


def test_decision_entry_carries_an_llm_generated_justification(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)

    result = run_decision_cycle(session, FakeGateway(), case, llm_client=FakeLLMClient())

    decision_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.DECISION)
    assert isinstance(decision_entry.data["justification"], str) and decision_entry.data["justification"]


def test_scheduled_sweep_reassesses_a_case_past_its_response_window(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT, external_reference_id="pay_due1")
    case.response_window_expires_at = _now() - timedelta(minutes=1)
    session.add(case)
    session.commit()
    session.refresh(case)

    swept = run_sweep(session, FakeGateway(), now=_now())

    assert [c.id for c in swept] == [case.id]

    session.refresh(case)
    entry_types = [entry.entry_type for entry in case.history]
    assert CaseHistoryEntryType.REASSESSMENT_TRIGGERED in entry_types
    assert CaseHistoryEntryType.DECISION in entry_types
    assert CaseHistoryEntryType.EXECUTION in entry_types  # payment_retry was approved and executed


def test_scheduled_sweep_does_not_touch_a_case_not_yet_due(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)
    case.response_window_expires_at = _now() + timedelta(hours=1)
    session.add(case)
    session.commit()
    session.refresh(case)

    swept = run_sweep(session, FakeGateway(), now=_now())

    assert swept == []
    session.refresh(case)
    assert case.history == []


def test_due_cases_ignores_cases_with_no_response_window_set(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)
    session.add(case)
    session.commit()

    assert due_cases(session, now=_now()) == []


# --- Ticket 09: escalation, human override, manual resolve ---------------


def test_llm_escalation_flag_escalates_the_case(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)

    result = run_decision_cycle(
        session, FakeGateway(), case, llm_client=FakeLLMClient(), qualitative_signal="This is ridiculous, get me a lawyer!"
    )

    assert result.status == CaseStatus.ESCALATED
    assert result.response_window_expires_at is None
    escalated_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.CASE_ESCALATED)
    assert "LLM" in escalated_entry.data["reason"]
    # Escalation short-circuits execution -- no gateway call happened this cycle.
    assert CaseHistoryEntryType.EXECUTION not in [e.entry_type for e in result.history]


def test_policy_escalation_threshold_escalates_the_case(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)
    policy = PolicyConfig(
        max_discount_pct=20.0, max_payment_retries=3, max_interventions_per_customer=5,
        recovery_budget=10_000_00, escalation_value_threshold=50_000,
    )

    result = run_decision_cycle(session, FakeGateway(), case, payment={"amount": 60_000}, policy=policy)

    assert result.status == CaseStatus.ESCALATED
    escalated_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.CASE_ESCALATED)
    assert "60000" in escalated_entry.data["reason"] or "60_000" in escalated_entry.data["reason"]


def test_case_value_under_the_escalation_threshold_proceeds_normally(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)
    policy = PolicyConfig(
        max_discount_pct=20.0, max_payment_retries=3, max_interventions_per_customer=5,
        recovery_budget=10_000_00, escalation_value_threshold=50_000,
    )

    result = run_decision_cycle(session, FakeGateway(), case, payment={"amount": 10_000}, policy=policy)

    assert result.status == CaseStatus.OPEN


def _escalated_case(session) -> RecoveryCase:
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT, external_reference_id="pay_esc1")
    session.add(case)
    session.commit()
    session.refresh(case)
    return run_decision_cycle(
        session, FakeGateway(), case, llm_client=FakeLLMClient(), qualitative_signal="I'm furious about this."
    )


def test_override_records_a_human_decision_and_executes_it(session):
    case = _escalated_case(session)

    result = override_case(session, FakeGateway(), case, intervention=Intervention.PAYMENT_RETRY)

    assert result.status == CaseStatus.OPEN
    assert result.response_window_expires_at is not None
    decisions = [e for e in result.history if e.entry_type == CaseHistoryEntryType.DECISION]
    assert decisions[-1].data == {"intervention": "payment_retry", "source": "human"}
    executions = [e for e in result.history if e.entry_type == CaseHistoryEntryType.EXECUTION]
    assert executions[-1].data["source"] == "human"


def test_override_with_no_action_records_no_execution(session):
    case = _escalated_case(session)

    result = override_case(session, FakeGateway(), case, intervention=Intervention.NO_ACTION)

    assert result.status == CaseStatus.OPEN
    decisions = [e for e in result.history if e.entry_type == CaseHistoryEntryType.DECISION]
    assert decisions[-1].data["intervention"] == "no_action"
    assert CaseHistoryEntryType.EXECUTION not in [e.entry_type for e in result.history]


def test_manual_resolve_as_recovered_closes_the_case(session):
    case = _escalated_case(session)

    result = resolve_case_manually(session, case, outcome=CaseStatus.RECOVERED, reason="customer paid over the phone")

    assert result.status == CaseStatus.RECOVERED
    assert result.response_window_expires_at is None
    recovered_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.CASE_RECOVERED)
    assert recovered_entry.data["reason"] == "customer paid over the phone"
    assert recovered_entry.data["resolved_by"] == "human"


def test_manual_resolve_as_stopped_closes_the_case(session):
    case = _escalated_case(session)

    result = resolve_case_manually(session, case, outcome=CaseStatus.STOPPED, reason="customer disputes the charge")

    assert result.status == CaseStatus.STOPPED
    stopped_entry = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.CASE_STOPPED)
    assert stopped_entry.data["reason"] == "customer disputes the charge"
    assert stopped_entry.data["resolved_by"] == "human"
