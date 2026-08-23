"""Ticket 06: the outcome-relevant webhook (payment.captured) closes a case
as recovered immediately -- a webhook-triggered Reassessment, not a sweep."""

from tests.conftest import post_signed_webhook, synthetic_payment_failed_payload


def _captured_payload(payment_id: str) -> dict:
    return {
        "entity": "event",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {"payment": {"entity": {"id": payment_id, "amount": 50000, "currency": "INR", "status": "captured"}}},
        "created_at": 1735689600,
    }


def _create_open_case(client, payment_id: str) -> dict:
    response = post_signed_webhook(
        client, "/webhooks/payment-failed", synthetic_payment_failed_payload(payment_id=payment_id), event_id=f"evt_fail_{payment_id}"
    )
    return response.json()


def test_payment_captured_webhook_immediately_marks_the_case_recovered(client):
    case = _create_open_case(client, "pay_captured1")

    response = post_signed_webhook(
        client, "/webhooks/payment-captured", _captured_payload("pay_captured1"), event_id="evt_captured1"
    )

    assert response.status_code == 200
    recovered = response.json()
    assert recovered["id"] == case["id"]
    assert recovered["status"] == "recovered"

    recovered_entry = next(e for e in recovered["history"] if e["entry_type"] == "case_recovered")
    assert "pay_captured1" in recovered_entry["data"]["reason"]


def test_payment_captured_for_unknown_payment_returns_404(client):
    response = post_signed_webhook(
        client, "/webhooks/payment-captured", _captured_payload("pay_never_seen"), event_id="evt_unknown1"
    )

    assert response.status_code == 404


def test_replaying_the_same_payment_captured_event_id_is_a_noop(client):
    _create_open_case(client, "pay_captured2")

    first = post_signed_webhook(client, "/webhooks/payment-captured", _captured_payload("pay_captured2"), event_id="evt_captured2")
    second = post_signed_webhook(client, "/webhooks/payment-captured", _captured_payload("pay_captured2"), event_id="evt_captured2")

    assert first.status_code == 200 and second.status_code == 200
    assert len(second.json()["history"]) == len(first.json()["history"])


def test_a_second_capture_event_for_an_already_recovered_case_is_a_noop(client):
    _create_open_case(client, "pay_captured3")
    post_signed_webhook(client, "/webhooks/payment-captured", _captured_payload("pay_captured3"), event_id="evt_captured3a")

    # A different event id for the same (already-resolved) payment must not re-log a recovery.
    second = post_signed_webhook(client, "/webhooks/payment-captured", _captured_payload("pay_captured3"), event_id="evt_captured3b")

    assert second.status_code == 200
    recovered_entries = [e for e in second.json()["history"] if e["entry_type"] == "case_recovered"]
    assert len(recovered_entries) == 1
