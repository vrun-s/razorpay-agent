"""Ticket 20: run a *real* captured Razorpay test-mode `subscription.halted`
webhook body through the ingestion path, guarding against a real-vs-synthetic
field-shape drift that `conftest.py::synthetic_subscription_halted_payload`
(hand-built for ticket 12) would not catch.

Skipped until `tests/fixtures/real_subscription_halted.json` exists -- see that
directory's README for how to capture it. Once dropped in, this file self-
activates and is the criterion-3/criterion-4 regression guard for the slice.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.config import settings
from app.gateway import FakeGateway, get_gateway
from app.main import app
from app.routers.webhooks import _extract_halted_subscription
from tests.conftest import post_signed_webhook

_FIXTURE = Path(__file__).parent / "fixtures" / "real_subscription_halted.json"

pytestmark = pytest.mark.skipif(
    not _FIXTURE.exists(),
    reason=f"drop a captured real subscription.halted payload at {_FIXTURE} (see tests/fixtures/README.md)",
)


@pytest.fixture()
def real_payload() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text())


def test_real_payload_is_a_subscription_halted_event(real_payload):
    assert real_payload.get("event") == "subscription.halted"


def test_real_payload_has_the_shape_the_extractor_expects(real_payload):
    entity = _extract_halted_subscription(real_payload)

    assert entity.get("id"), "real payload has no payload.subscription.entity.id -- _extract_halted_subscription drift"


def test_real_payload_creates_one_halted_subscription_case(client, real_payload):
    response = post_signed_webhook(client, "/webhooks/subscription-halted", real_payload, event_id="evt_real_halted_1")

    assert response.status_code == 200
    case = response.json()
    assert case["workflow_type"] == "halted_subscription"
    assert case["status"] == "open"
    assert len(client.get("/cases").json()) == 1


def test_real_payload_replayed_event_id_does_not_duplicate(client, real_payload):
    first = post_signed_webhook(client, "/webhooks/subscription-halted", real_payload, event_id="evt_real_halted_dedupe")
    second = post_signed_webhook(client, "/webhooks/subscription-halted", real_payload, event_id="evt_real_halted_dedupe")

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/cases").json()) == 1


def test_real_payload_is_tagged_source_real_under_the_razorpay_backend(client, real_payload, monkeypatch):
    """The real fixture through the real-Razorpay tagging path (criterion 4):
    `GATEWAY_BACKEND=razorpay` without a live gateway -- the flag is what
    `_webhook_event_source` branches on."""
    monkeypatch.setattr(settings, "gateway_backend", "razorpay")
    app.dependency_overrides[get_gateway] = lambda: FakeGateway()
    try:
        response = post_signed_webhook(
            client, "/webhooks/subscription-halted", real_payload, event_id="evt_real_halted_src"
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)

    assert response.status_code == 200
    assert response.json()["source"] == "real"
