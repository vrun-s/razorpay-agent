"""Ticket 18: the dashboard read-model projections (app/observability.py)."""

import pytest

from app.models import CaseStatus, Intervention, RecoveryCase, WorkflowType
from app.observability import budget_timeline, case_flags, case_timeline
from app.policy import PolicyConfig
from tests.conftest import post_signed_webhook, synthetic_payment_failed_payload

pytestmark = pytest.mark.usefixtures("isolated_estimator")


def _captured_payload(payment_id: str) -> dict:
    return {
        "entity": "event",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {"payment": {"entity": {"id": payment_id, "amount": 50000, "currency": "INR", "status": "captured"}}},
        "created_at": 1735689600,
    }


def _open_case(client, payment_id: str) -> dict:
    return post_signed_webhook(
        client,
        "/webhooks/payment-failed",
        synthetic_payment_failed_payload(payment_id=payment_id),
        event_id=f"evt_fail_{payment_id}",
    ).json()


# -- budget_timeline --------------------------------------------------------


def test_budget_timeline_has_one_snapshot_per_allocation_decision_oldest_first(client, session):
    _open_case(client, "pay_bt1")
    _open_case(client, "pay_bt2")

    timeline = budget_timeline(session)

    assert len(timeline) == 2
    assert [s.timestamp for s in timeline] == sorted(s.timestamp for s in timeline)
    first = timeline[0]
    assert first.funded is True
    # ADR-0010 disclosed gap: incentive_amount is 0, so nothing is ever spent
    # and the reserve holds at a third of the default budget.
    assert first.spent == 0
    assert first.reserved > 0
    assert first.available > 0


def test_budget_timeline_is_empty_before_any_case_exists(session):
    assert budget_timeline(session) == []


# -- case_flags -----------------------------------------------------------------


def test_no_action_recovered_flag(client, session, monkeypatch):
    # Force the estimator so NO_ACTION outscores PAYMENT_RETRY for this case.
    from app.estimator import CustomerSegmentProxy, EstimatorCellKey, get_estimator
    from app.models import EventSource

    key = EstimatorCellKey(
        failure_reason="insufficient_funds",
        customer_segment_proxy=CustomerSegmentProxy.NEW,
        intervention=Intervention.NO_ACTION,
    )
    for _ in range(20):
        get_estimator().update(key, source=EventSource.SIMULATED, success=True)

    case = _open_case(client, "pay_na1")
    decision = next(e for e in case["history"] if e["entry_type"] == "decision")
    assert decision["data"]["intervention"] == "no_action"
    assert "execution" not in [e["entry_type"] for e in case["history"]]

    # An outcome webhook still recovers it.
    post_signed_webhook(client, "/webhooks/payment-captured", _captured_payload("pay_na1"), event_id="evt_na1")

    stored = session.get(RecoveryCase, case["id"])
    flags = case_flags(stored)
    assert flags.no_action_recovered is True
    assert flags.policy_rejected is False
    assert flags.human_overridden is False


def test_policy_rejected_flag(client, session, monkeypatch):
    monkeypatch.setattr(
        "app.lifecycle.DEFAULT_POLICY_CONFIG",
        PolicyConfig(max_discount_pct=20.0, max_payment_retries=0, max_interventions_per_customer=5, recovery_budget=10_000_00),
    )
    case = _open_case(client, "pay_pr1")

    stored = session.get(RecoveryCase, case["id"])
    flags = case_flags(stored)
    assert flags.policy_rejected is True
    assert flags.no_action_recovered is False


def test_human_overridden_flag(client, session):
    from app.lifecycle import override_case
    from app.gateway import get_gateway

    # Build an escalated case directly, then override it.
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT, status=CaseStatus.ESCALATED)
    session.add(case)
    session.commit()
    session.refresh(case)

    override_case(session, get_gateway(), case, intervention=Intervention.PAYMENT_RETRY)

    flags = case_flags(session.get(RecoveryCase, case.id))
    assert flags.human_overridden is True


# -- case_timeline ------------------------------------------------------------


def test_case_timeline_is_ordered_and_names_the_bound_constraint(client, session, monkeypatch):
    monkeypatch.setattr(
        "app.lifecycle.DEFAULT_POLICY_CONFIG",
        PolicyConfig(max_discount_pct=20.0, max_payment_retries=0, max_interventions_per_customer=5, recovery_budget=10_000_00),
    )
    case = _open_case(client, "pay_tl1")

    stages = case_timeline(session.get(RecoveryCase, case["id"]))

    assert [s.stage for s in stages[:3]] == ["detected", "decision", "policy_check"]
    assert [s.timestamp for s in stages] == sorted(s.timestamp for s in stages)
    policy_stage = next(s for s in stages if s.stage == "policy_check")
    assert "max_payment_retries" in policy_stage.label
    assert policy_stage.detail["violated_constraint"] == "max_payment_retries"
    # Rejected on a sequence-bound constraint -> the case is force-stopped.
    assert stages[-1].stage == "outcome"


def test_case_timeline_happy_path_shows_the_webhook_beat_before_the_outcome(client, session):
    case = _open_case(client, "pay_tl2")
    post_signed_webhook(client, "/webhooks/payment-captured", _captured_payload("pay_tl2"), event_id="evt_tl2")

    stages = case_timeline(session.get(RecoveryCase, case["id"]))
    stage_names = [s.stage for s in stages]
    # The spec chain: ... -> execution -> webhook -> ... -> outcome.
    assert stage_names.index("execution") < stage_names.index("webhook") < stage_names.index("outcome")
    webhook_stage = next(s for s in stages if s.stage == "webhook")
    assert webhook_stage.detail["event"] == "payment.captured"
    assert stage_names[-1] == "outcome"
    assert case_flags(session.get(RecoveryCase, case["id"])).no_action_recovered is False


def test_case_timeline_order_is_stable_under_equal_timestamps():
    # Every entry in one decision cycle can share a timestamp to the
    # microsecond; the autoincrement id must still order them by insertion.
    from datetime import datetime, timezone

    from app.models import CaseHistoryEntry, CaseHistoryEntryType

    t = datetime(2026, 8, 27, tzinfo=timezone.utc)
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT)
    case.history = [
        CaseHistoryEntry(id=4, case_id=case.id, created_at=t, entry_type=CaseHistoryEntryType.ALLOCATION_CHECK, summary=""),
        CaseHistoryEntry(id=1, case_id=case.id, created_at=t, entry_type=CaseHistoryEntryType.CASE_CREATED, summary=""),
        CaseHistoryEntry(id=3, case_id=case.id, created_at=t, entry_type=CaseHistoryEntryType.POLICY_CHECK, summary=""),
        CaseHistoryEntry(id=2, case_id=case.id, created_at=t, entry_type=CaseHistoryEntryType.DECISION, summary=""),
    ]

    stages = case_timeline(case)
    assert [s.stage for s in stages] == ["detected", "decision", "policy_check", "allocation"]
