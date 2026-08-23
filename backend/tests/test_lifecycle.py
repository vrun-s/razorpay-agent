"""Ticket 06: case lifecycle -- reassessment loop, fatigue, sequence-bound stop."""

from datetime import datetime, timedelta, timezone

from app.gateway import FakeGateway
from app.lifecycle import due_cases, run_decision_cycle, run_sweep
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
