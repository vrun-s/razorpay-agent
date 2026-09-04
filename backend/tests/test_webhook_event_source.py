"""Ticket 20: a webhook that arrives while the app is wired to real Razorpay
(`GATEWAY_BACKEND=razorpay`) creates a `source=REAL` case, so it is excluded
from the Decision Engine's posterior (ticket 07's exclusion rule). Under the
fake gateway (dev, demo, tests) an inbound webhook is synthetic and the case
stays SIMULATED -- the pre-ticket-20 behaviour, unchanged.
"""

import pytest

from app.config import settings
from app.gateway import FakeGateway, get_gateway
from app.main import app
from tests.conftest import (
    post_signed_webhook,
    synthetic_payment_failed_payload,
    synthetic_subscription_halted_payload,
)


@pytest.fixture()
def real_gateway_config(monkeypatch):
    """`GATEWAY_BACKEND=razorpay` without standing up a real `RazorpayGateway`:
    the config flag is what source-tagging branches on; the `FakeGateway`
    override keeps the rest of the pipeline in-process (no network, no keys)."""
    monkeypatch.setattr(settings, "gateway_backend", "razorpay")
    app.dependency_overrides[get_gateway] = lambda: FakeGateway()
    yield
    app.dependency_overrides.pop(get_gateway, None)


def test_halted_subscription_webhook_is_simulated_under_the_fake_gateway(client):
    response = post_signed_webhook(client, "/webhooks/subscription-halted", synthetic_subscription_halted_payload())

    assert response.status_code == 200
    assert response.json()["source"] == "simulated"


def test_halted_subscription_webhook_is_real_under_the_razorpay_gateway(client, real_gateway_config):
    response = post_signed_webhook(client, "/webhooks/subscription-halted", synthetic_subscription_halted_payload())

    assert response.status_code == 200
    assert response.json()["source"] == "real"


def test_failed_payment_webhook_source_tracks_the_gateway_backend(client, real_gateway_config):
    response = post_signed_webhook(client, "/webhooks/payment-failed", synthetic_payment_failed_payload())

    assert response.status_code == 200
    assert response.json()["source"] == "real"
