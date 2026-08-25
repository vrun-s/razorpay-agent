import json

import httpx
import pytest

from app.config import settings
from app.gateway import FakeGateway, GatewayError, RazorpayGateway, get_gateway
from tests.conftest import mock_razorpay_client as _mock_client


def test_create_payment_link_returns_a_link_and_makes_no_real_calls():
    gateway = FakeGateway()

    result = gateway.create_payment_link(
        case_id="case-1",
        amount=50000,
        currency="INR",
        description="Complete your payment",
        customer_contact={"email": "a@example.com", "contact": "+911234567890"},
    )

    assert result.payment_link_id.startswith("plink_fake_")
    assert result.short_url.startswith("https://fake.razorpay.link/")
    assert result.status == "created"


def test_resume_charge_returns_a_pending_status():
    gateway = FakeGateway()

    result = gateway.resume_charge(case_id="case-1", subscription_id="sub_123")

    assert result.subscription_id == "sub_123"
    assert result.status == "charge_pending"


def test_parse_webhook_extracts_event_and_payload():
    gateway = FakeGateway()
    body = json.dumps({"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_1"}}}}).encode()

    parsed = gateway.parse_webhook(headers={}, raw_body=body)

    assert parsed.event == "payment.failed"
    assert parsed.payload["payload"]["payment"]["entity"]["id"] == "pay_1"


def test_razorpay_gateway_create_payment_link_posts_to_payment_links_and_parses_response():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"id": "plink_real123", "short_url": "https://rzp.io/i/abc123", "status": "created"},
        )

    gateway = RazorpayGateway(key_id="rzp_test_key", key_secret="secret", client=_mock_client(handler))

    result = gateway.create_payment_link(
        case_id="case-1",
        amount=50000,
        currency="INR",
        description="Complete your payment",
        customer_contact={"email": "a@example.com", "contact": "+911234567890"},
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/payment_links"
    assert captured["body"]["amount"] == 50000
    assert captured["body"]["currency"] == "INR"
    assert captured["body"]["customer"]["email"] == "a@example.com"
    assert captured["body"]["customer"]["contact"] == "+911234567890"
    assert captured["body"]["notes"]["case_id"] == "case-1"

    assert result.payment_link_id == "plink_real123"
    assert result.short_url == "https://rzp.io/i/abc123"
    assert result.status == "created"


def test_razorpay_gateway_default_client_authenticates_with_key_id_and_secret():
    gateway = RazorpayGateway(key_id="rzp_test_key", key_secret="secret")

    assert gateway._client.auth is not None


def test_razorpay_gateway_create_payment_link_raises_gateway_error_on_failure_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"description": "amount must be at least 100"}})

    gateway = RazorpayGateway(key_id="rzp_test_key", key_secret="secret", client=_mock_client(handler))

    with pytest.raises(GatewayError, match="amount must be at least 100"):
        gateway.create_payment_link(
            case_id="case-1", amount=1, currency="INR", description="x", customer_contact={}
        )


def test_razorpay_gateway_resume_charge_posts_to_subscription_resume_and_parses_response():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "sub_123", "status": "active"})

    gateway = RazorpayGateway(key_id="rzp_test_key", key_secret="secret", client=_mock_client(handler))

    result = gateway.resume_charge(case_id="case-1", subscription_id="sub_123")

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/subscriptions/sub_123/resume"
    assert captured["body"] == {"resume_at": "now"}
    assert result.subscription_id == "sub_123"
    assert result.status == "active"


def test_razorpay_gateway_resume_charge_raises_gateway_error_on_failure_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"description": "Resume is only allowed for paused subscriptions"}})

    gateway = RazorpayGateway(key_id="rzp_test_key", key_secret="secret", client=_mock_client(handler))

    with pytest.raises(GatewayError, match="Resume is only allowed for paused subscriptions"):
        gateway.resume_charge(case_id="case-1", subscription_id="sub_123")


def test_razorpay_gateway_parse_webhook_extracts_event_and_payload_same_as_fake():
    gateway = RazorpayGateway(key_id="rzp_test_key", key_secret="secret", client=_mock_client(lambda r: httpx.Response(200)))
    body = json.dumps({"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_1"}}}}).encode()

    parsed = gateway.parse_webhook(headers={}, raw_body=body)

    assert parsed.event == "payment.failed"
    assert parsed.payload["payload"]["payment"]["entity"]["id"] == "pay_1"


def test_get_gateway_returns_fake_gateway_by_default(monkeypatch):
    monkeypatch.setattr(settings, "gateway_backend", "fake")

    assert isinstance(get_gateway(), FakeGateway)


def test_get_gateway_returns_razorpay_gateway_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "gateway_backend", "razorpay")
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(settings, "razorpay_key_secret", "secret")

    assert isinstance(get_gateway(), RazorpayGateway)


def test_get_gateway_raises_when_razorpay_backend_configured_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "gateway_backend", "razorpay")
    monkeypatch.setattr(settings, "razorpay_key_id", None)
    monkeypatch.setattr(settings, "razorpay_key_secret", None)

    with pytest.raises(RuntimeError, match="RAZORPAY_KEY_ID"):
        get_gateway()
