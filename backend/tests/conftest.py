import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.db import get_session
from app.gateway import RazorpayGateway
from app.main import app
from app.webhook_security import sign

TEST_WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def client(session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def isolated_allocator(monkeypatch):
    """Swaps the process-wide `StreamingAllocator` singleton
    (app/allocator.py's `get_allocator()`) for a fresh one before every test.

    Ticket 19/ADR-0014 gives a `PAYMENT_RETRY`/`RESUME_CHARGE` proposal a
    real, non-zero `incentive_amount` for the first time -- before this, the
    singleton's `spent` never moved regardless of how many tests ran through
    it, so no test needed isolating from it. Autouse (unlike
    `isolated_estimator` below, which some tests want to opt out of): there's
    no test that wants another test's Incentive spend leaking into its own
    budget math.
    """
    import app.allocator as allocator_module
    from app.merchant_config import DEFAULT_MERCHANT_CONFIG

    fresh = allocator_module.StreamingAllocator(
        allocator_module.BudgetLedger(recovery_budget=DEFAULT_MERCHANT_CONFIG.recovery_budget, reserve_ratio=1 / 3)
    )
    monkeypatch.setattr(allocator_module, "_default_allocator", fresh)


@pytest.fixture()
def isolated_estimator(monkeypatch):
    """Swaps the process-wide `Estimator` singleton for a fresh one for the
    duration of a test, so one test's forced posterior can't decide another
    test's cases. Not autouse -- opt in per module with
    `pytestmark = pytest.mark.usefixtures("isolated_estimator")`. Same
    mechanism tests/test_evaluation.py's own fixture uses inline.
    """
    import app.estimator as estimator_module

    monkeypatch.setattr(estimator_module, "_default_estimator", estimator_module.Estimator())


@pytest.fixture(autouse=True)
def webhook_secret(monkeypatch):
    """Fixes the webhook secret for tests, independent of whatever is in .env."""
    monkeypatch.setattr(settings, "razorpay_webhook_secret", TEST_WEBHOOK_SECRET)


@pytest.fixture(autouse=True)
def fake_gateway_backend(monkeypatch):
    """Pin the gateway to the in-process fake for every test, independent of
    `.env`. A real-Razorpay run (ticket 20) puts `GATEWAY_BACKEND=razorpay` and
    live keys in the repo-root `.env` that `config.py` loads; without this,
    `pytest` run from that checkout would send every full-engine test at
    `api.razorpay.com`. Tests that want the real gateway (`test_gateway.py`,
    `test_webhook_event_source.py`) monkeypatch it back on top."""
    monkeypatch.setattr(settings, "gateway_backend", "fake")
    monkeypatch.setattr(settings, "razorpay_key_id", None)
    monkeypatch.setattr(settings, "razorpay_key_secret", None)


def mock_razorpay_client(handler) -> httpx.Client:
    """An httpx.Client wired to a MockTransport, standing in for Razorpay itself
    -- shared by every RazorpayGateway test so none of them hit the network."""
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=RazorpayGateway._BASE_URL)


def signed_headers(raw_body: bytes, *, event_id: str, secret: str = TEST_WEBHOOK_SECRET) -> dict[str, str]:
    return {
        "content-type": "application/json",
        "x-razorpay-signature": sign(raw_body, secret),
        "x-razorpay-event-id": event_id,
    }


def post_signed_webhook(client: TestClient, url: str, payload: dict[str, Any], *, event_id: str = "evt_test1") -> Any:
    raw_body = json.dumps(payload).encode()
    return client.post(url, content=raw_body, headers=signed_headers(raw_body, event_id=event_id))


def synthetic_payment_failed_payload(payment_id: str = "pay_test123", order_id: str = "order_test123") -> dict[str, Any]:
    return {
        "entity": "event",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 50000,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": order_id,
                    "email": "customer@example.com",
                    "contact": "+911234567890",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed due to insufficient funds",
                }
            }
        },
        "created_at": 1735689600,
    }


def synthetic_subscription_halted_payload(subscription_id: str = "sub_test123", plan_id: str = "plan_test123") -> dict[str, Any]:
    """Razorpay's documented `subscription.halted` schema -- the Subscription entity
    under `payload.subscription.entity`, reached only after Razorpay's own three
    automatic retries are already exhausted (CONTEXT.md: Resume Charge)."""
    return {
        "entity": "event",
        "event": "subscription.halted",
        "contains": ["subscription"],
        "payload": {
            "subscription": {
                "entity": {
                    "id": subscription_id,
                    "entity": "subscription",
                    "plan_id": plan_id,
                    "customer_id": "cust_test123",
                    "status": "halted",
                    "current_start": 1735689600,
                    "current_end": 1738368000,
                    "ended_at": None,
                    "quantity": 1,
                    "notes": {},
                    "charge_at": 1735689600,
                    "start_at": 1733011200,
                    "end_at": 1893456000,
                    "auth_attempts": 3,
                    "total_count": 12,
                    "paid_count": 3,
                    "customer_notify": True,
                    "created_at": 1730000000,
                    "short_url": "https://rzp.io/i/test_short_url",
                    "has_scheduled_changes": False,
                    "change_scheduled_at": None,
                    "source": "api",
                    "payment_method": "card",
                    "offer_id": None,
                    "remaining_count": 9,
                }
            }
        },
        "created_at": 1735689600,
    }
