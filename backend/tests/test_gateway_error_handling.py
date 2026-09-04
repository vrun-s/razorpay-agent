"""Ticket 20: a real Gateway call that reaches Razorpay and is rejected
(`GatewayError`) is recorded as an `EXECUTION_FAILED` entry and the case is
left OPEN for the next reassessment / escalation -- `run_decision_cycle` does
not let it propagate as a 500. The real trigger: Razorpay returns
400 "subscription can't be resumed as subscription is in completed state" for
a genuinely halted subscription (the `/resume` endpoint is documented for
`paused`, not `halted`).
"""

from app.gateway import FakeGateway, GatewayError, get_gateway
from app.llm import FakeLLMClient
from app.main import app
from app.lifecycle import run_decision_cycle
from app.models import CaseHistoryEntryType, CaseStatus, RecoveryCase, WorkflowType
from tests.conftest import post_signed_webhook, synthetic_subscription_halted_payload

_RESUME_REJECTION = (
    "Razorpay /subscriptions/sub_x/resume returned 400: "
    "subscription can't be resumed as subscription is in completed state"
)


class _RejectingGateway(FakeGateway):
    """Both write calls fail the way `RazorpayGateway` surfaces a non-2xx."""

    def resume_charge(self, **kwargs):
        raise GatewayError(_RESUME_REJECTION)

    def create_payment_link(self, **kwargs):
        raise GatewayError("Razorpay /payment_links returned 400: bad request")


def test_resume_charge_rejection_is_recorded_and_case_stays_open(session):
    case = RecoveryCase(workflow_type=WorkflowType.HALTED_SUBSCRIPTION, external_reference_id="sub_x")
    session.add(case)
    session.commit()
    session.refresh(case)

    result = run_decision_cycle(
        session, _RejectingGateway(), case, payment={"id": "sub_x"}, llm_client=FakeLLMClient()
    )

    entry_types = [e.entry_type for e in result.history]
    assert CaseHistoryEntryType.EXECUTION_FAILED in entry_types
    assert CaseHistoryEntryType.EXECUTION not in entry_types
    assert result.status == CaseStatus.OPEN

    failed = next(e for e in result.history if e.entry_type == CaseHistoryEntryType.EXECUTION_FAILED)
    assert failed.data["intervention"] == "resume_charge"
    assert "completed state" in failed.data["error"]


def test_payment_retry_rejection_is_recorded_and_case_stays_open(session):
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT, external_reference_id="pay_x")
    session.add(case)
    session.commit()
    session.refresh(case)

    result = run_decision_cycle(
        session, _RejectingGateway(), case, payment={"id": "pay_x", "amount": 50_000}, llm_client=FakeLLMClient()
    )

    entry_types = [e.entry_type for e in result.history]
    assert CaseHistoryEntryType.EXECUTION_FAILED in entry_types
    assert CaseHistoryEntryType.EXECUTION not in entry_types
    assert result.status == CaseStatus.OPEN


def test_subscription_halted_webhook_returns_200_when_the_gateway_rejects_resume(client, session):
    app.dependency_overrides[get_gateway] = lambda: _RejectingGateway()
    try:
        response = post_signed_webhook(
            client, "/webhooks/subscription-halted", synthetic_subscription_halted_payload()
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)

    assert response.status_code == 200
    case = response.json()
    entry_types = [e["entry_type"] for e in case["history"]]
    assert "execution_failed" in entry_types
    assert "execution" not in entry_types
    assert case["status"] == "open"
