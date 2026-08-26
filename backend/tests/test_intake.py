"""Ticket 17: `EventSource.REAL` tagging on case creation, and the
estimator-exclusion guarantee that tag is supposed to buy (ticket 07)."""

import pytest

from app.estimator import CustomerSegmentProxy, Estimator, EstimatorCellKey, get_estimator
from app.gateway import FakeGateway
from app.intake import create_case_from_failed_payment, create_case_from_halted_subscription
from app.lifecycle import mark_recovered
from app.models import CaseStatus, EventSource, Intervention


@pytest.fixture(autouse=True)
def isolated_estimator(monkeypatch):
    """The shared Estimator singleton is process-wide -- reset it per test so
    one test's updates can't bias another's cold-start assumptions (same
    pattern as tests/test_evaluation.py and tests/test_stress_test.py)."""
    import app.estimator as estimator_module

    monkeypatch.setattr(estimator_module, "_default_estimator", estimator_module.Estimator())


def test_failed_payment_case_defaults_to_simulated_source(session):
    case = create_case_from_failed_payment(session, FakeGateway(), {"id": "pay_1"}, event_id="evt_1")

    assert case.source == EventSource.SIMULATED


def test_failed_payment_case_can_be_tagged_real(session):
    case = create_case_from_failed_payment(
        session, FakeGateway(), {"id": "pay_1"}, event_id="evt_1", source=EventSource.REAL
    )

    assert case.source == EventSource.REAL


def test_halted_subscription_case_defaults_to_simulated_source(session):
    case = create_case_from_halted_subscription(session, FakeGateway(), {"id": "sub_1"}, event_id="evt_2")

    assert case.source == EventSource.SIMULATED


def test_halted_subscription_case_can_be_tagged_real(session):
    case = create_case_from_halted_subscription(
        session, FakeGateway(), {"id": "sub_1"}, event_id="evt_2", source=EventSource.REAL
    )

    assert case.source == EventSource.REAL


def test_a_real_tagged_cases_recovery_never_updates_the_shared_estimator(session):
    """The whole point of tagging a case `real` (ticket 17): its outcome is a
    replay of a decision already counted in the AI arm's synthetic stream,
    not independent evidence (ADR-0006) -- `mark_recovered`'s call into
    `get_estimator().update(...)` must be a no-op for it."""
    case = create_case_from_failed_payment(
        session,
        FakeGateway(),
        {"id": "pay_real_1", "amount": 50_000, "error_code": "X", "error_description": "insufficient funds"},
        event_id="evt_real_1",
        source=EventSource.REAL,
    )
    key = EstimatorCellKey(
        failure_reason="insufficient_funds", customer_segment_proxy=CustomerSegmentProxy.NEW, intervention=Intervention.PAYMENT_RETRY
    )
    cold_estimate = get_estimator().estimate(key)

    mark_recovered(session, case, "evt_real_capture_1", reason="real payment captured")

    assert case.status == CaseStatus.RECOVERED
    assert get_estimator().estimate(key) == cold_estimate  # unchanged despite the "success" outcome


def test_a_simulated_cases_recovery_does_update_the_shared_estimator():
    """Contrast case for the test above -- confirms the exclusion is
    genuinely about the `source` tag, not some other side effect of
    `mark_recovered` being disabled entirely."""
    estimator = Estimator()
    key = EstimatorCellKey(
        failure_reason="x", customer_segment_proxy=CustomerSegmentProxy.NEW, intervention=Intervention.PAYMENT_RETRY
    )
    before = estimator.estimate(key)

    estimator.update(key, source=EventSource.SIMULATED, success=True)

    assert estimator.estimate(key) != before
