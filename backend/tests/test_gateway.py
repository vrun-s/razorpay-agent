import json

from app.gateway import FakeGateway


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
