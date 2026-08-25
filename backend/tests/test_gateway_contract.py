"""Ticket 13: a contract test asserting `FakeGateway` and `RazorpayGateway`
satisfy the same `Gateway` Protocol behavior -- same return shapes for the
same inputs, so nothing above the seam (app/lifecycle.py, app/intake.py) can
tell them apart. `RazorpayGateway` is exercised through an `httpx.MockTransport`
double standing in for Razorpay itself, never a real network call.

Error-handling parity is asymmetric by design, not an oversight: `FakeGateway`
never fails (it makes no real calls, so there's nothing to reject), while
`RazorpayGateway` raises `GatewayError` on any non-2xx Razorpay response. The
error-handling tests below therefore only exercise `RazorpayGateway`, but
assert it does so consistently across both Gateway methods -- the one part of
"error handling" that actually is a contract two failure-capable calls share.
"""

import json

import httpx
import pytest

from app.gateway import FakeGateway, Gateway, GatewayError, PaymentLinkResult, RazorpayGateway, ResumeChargeResult
from tests.conftest import mock_razorpay_client


def _razorpay_gateway_backed_by(*, payment_link_status: str, resume_status: str) -> Gateway:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/payment_links"):
            return httpx.Response(
                200, json={"id": "plink_real1", "short_url": "https://rzp.io/i/real1", "status": payment_link_status}
            )
        return httpx.Response(200, json={"id": "sub_real1", "status": resume_status})

    return RazorpayGateway(key_id="rzp_test_key", key_secret="secret", client=mock_razorpay_client(handler))


@pytest.fixture(
    params=[
        "fake",
        "razorpay",
    ]
)
def gateway(request) -> Gateway:
    if request.param == "fake":
        return FakeGateway()
    return _razorpay_gateway_backed_by(payment_link_status="created", resume_status="active")


def test_create_payment_link_returns_a_payment_link_result(gateway: Gateway):
    result = gateway.create_payment_link(
        case_id="case-1",
        amount=50000,
        currency="INR",
        description="Complete your payment",
        customer_contact={"email": "a@example.com", "contact": "+911234567890"},
    )

    assert isinstance(result, PaymentLinkResult)
    assert isinstance(result.payment_link_id, str) and result.payment_link_id
    assert result.short_url.startswith("https://")
    assert isinstance(result.status, str) and result.status


def test_resume_charge_returns_a_resume_charge_result(gateway: Gateway):
    result = gateway.resume_charge(case_id="case-1", subscription_id="sub_123")

    assert isinstance(result, ResumeChargeResult)
    assert isinstance(result.subscription_id, str) and result.subscription_id
    assert isinstance(result.status, str) and result.status


def test_parse_webhook_extracts_event_and_payload(gateway: Gateway):
    body = json.dumps({"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_1"}}}}).encode()

    parsed = gateway.parse_webhook(headers={}, raw_body=body)

    assert parsed.event == "payment.failed"
    assert parsed.payload["payload"]["payment"]["entity"]["id"] == "pay_1"


@pytest.mark.parametrize(
    "call",
    [
        lambda gateway: gateway.create_payment_link(
            case_id="case-1", amount=50000, currency="INR", description="x", customer_contact={}
        ),
        lambda gateway: gateway.resume_charge(case_id="case-1", subscription_id="sub_123"),
    ],
    ids=["create_payment_link", "resume_charge"],
)
def test_razorpay_gateway_raises_gateway_error_consistently_across_methods(call):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"description": "rejected"}})

    gateway = RazorpayGateway(key_id="rzp_test_key", key_secret="secret", client=mock_razorpay_client(handler))

    with pytest.raises(GatewayError, match="rejected"):
        call(gateway)
