import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.db import get_session
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
def webhook_secret(monkeypatch):
    """Fixes the webhook secret for tests, independent of whatever is in .env."""
    monkeypatch.setattr(settings, "razorpay_webhook_secret", TEST_WEBHOOK_SECRET)


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
