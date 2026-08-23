"""Ticket 04: signature verification and event-id dedup for payment.failed ingestion."""

import json

from tests.conftest import (
    TEST_WEBHOOK_SECRET,
    post_signed_webhook,
    signed_headers,
    synthetic_payment_failed_payload as _payload,
)


def test_validly_signed_synthetic_payload_is_accepted(client):
    response = post_signed_webhook(client, "/webhooks/payment-failed", _payload())

    assert response.status_code == 200
    case = response.json()
    assert case["workflow_type"] == "failed_payment"
    assert case["status"] == "open"


def test_invalidly_signed_payload_is_rejected(client):
    raw_body = json.dumps(_payload()).encode()
    headers = {
        "content-type": "application/json",
        "x-razorpay-signature": "not-a-real-signature",
        "x-razorpay-event-id": "evt_bad_sig",
    }

    response = client.post("/webhooks/payment-failed", content=raw_body, headers=headers)

    assert response.status_code == 400
    assert client.get("/cases").json() == []


def test_missing_signature_header_is_rejected(client):
    raw_body = json.dumps(_payload()).encode()
    headers = {"content-type": "application/json", "x-razorpay-event-id": "evt_no_sig"}

    response = client.post("/webhooks/payment-failed", content=raw_body, headers=headers)

    assert response.status_code == 400
    assert client.get("/cases").json() == []


def test_replaying_the_same_event_id_does_not_create_a_second_case(client):
    payload = _payload()

    first = post_signed_webhook(client, "/webhooks/payment-failed", payload, event_id="evt_replay1")
    second = post_signed_webhook(client, "/webhooks/payment-failed", payload, event_id="evt_replay1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    cases = client.get("/cases").json()
    assert len(cases) == 1
    # A no-op replay never re-runs decide -> policy -> execute for the same case.
    assert len(cases[0]["history"]) == 4


def test_different_event_ids_create_separate_cases(client):
    first = post_signed_webhook(client, "/webhooks/payment-failed", _payload("pay_a"), event_id="evt_a")
    second = post_signed_webhook(client, "/webhooks/payment-failed", _payload("pay_b"), event_id="evt_b")

    assert first.json()["id"] != second.json()["id"]
    assert len(client.get("/cases").json()) == 2


def test_malformed_payload_with_a_valid_signature_is_still_rejected(client):
    response = post_signed_webhook(client, "/webhooks/payment-failed", {"event": "payment.failed", "payload": {}})

    assert response.status_code == 400
    assert client.get("/cases").json() == []


def test_signature_is_computed_over_the_exact_secret(client):
    raw_body = json.dumps(_payload()).encode()
    headers = signed_headers(raw_body, event_id="evt_wrong_secret", secret="a-different-secret")
    assert TEST_WEBHOOK_SECRET != "a-different-secret"

    response = client.post("/webhooks/payment-failed", content=raw_body, headers=headers)

    assert response.status_code == 400
