"""Ticket 12: subscription.halted ingestion, hardened the same way ticket 04
hardened payment.failed -- HMAC-SHA256 verification and event-id dedupe --
reusing the entire engine matured on failed-payment (ADR-0002)."""

import json

from tests.conftest import post_signed_webhook, signed_headers, synthetic_subscription_halted_payload as _payload


def test_validly_signed_synthetic_payload_is_accepted_and_creates_a_case(client):
    response = post_signed_webhook(client, "/webhooks/subscription-halted", _payload())

    assert response.status_code == 200
    case = response.json()
    assert case["workflow_type"] == "halted_subscription"
    assert case["status"] == "open"


def test_case_flows_through_the_full_existing_engine(client):
    response = post_signed_webhook(client, "/webhooks/subscription-halted", _payload())

    case = response.json()
    entry_types = [entry["entry_type"] for entry in case["history"]]
    assert "case_created" in entry_types
    assert "decision" in entry_types
    assert "policy_check" in entry_types
    # Ticket 19/ADR-0014: HALTED_SUBSCRIPTION's case_value is always 0
    # (ticket 12's disclosed Plan-amount gap), so RESUME_CHARGE's
    # incentive_amount computes to 0 too and the Streaming Allocator is
    # never consulted -- distinct from a decline, no allocation_check entry
    # at all.
    assert "allocation_check" not in entry_types
    assert "execution" in entry_types

    execution_entry = next(e for e in case["history"] if e["entry_type"] == "execution")
    assert execution_entry["data"]["intervention"] == "resume_charge"
    assert execution_entry["data"]["incentive_amount"] == 0


def test_invalidly_signed_payload_is_rejected(client):
    raw_body = json.dumps(_payload()).encode()
    headers = {
        "content-type": "application/json",
        "x-razorpay-signature": "not-a-real-signature",
        "x-razorpay-event-id": "evt_bad_sig",
    }

    response = client.post("/webhooks/subscription-halted", content=raw_body, headers=headers)

    assert response.status_code == 400
    assert client.get("/cases").json() == []


def test_missing_signature_header_is_rejected(client):
    raw_body = json.dumps(_payload()).encode()
    headers = {"content-type": "application/json", "x-razorpay-event-id": "evt_no_sig"}

    response = client.post("/webhooks/subscription-halted", content=raw_body, headers=headers)

    assert response.status_code == 400
    assert client.get("/cases").json() == []


def test_replaying_the_same_event_id_does_not_create_a_second_case(client):
    payload = _payload()

    first = post_signed_webhook(client, "/webhooks/subscription-halted", payload, event_id="evt_replay1")
    second = post_signed_webhook(client, "/webhooks/subscription-halted", payload, event_id="evt_replay1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/cases").json()) == 1


def test_different_event_ids_create_separate_cases(client):
    first = post_signed_webhook(client, "/webhooks/subscription-halted", _payload("sub_a"), event_id="evt_a")
    second = post_signed_webhook(client, "/webhooks/subscription-halted", _payload("sub_b"), event_id="evt_b")

    assert first.json()["id"] != second.json()["id"]
    assert len(client.get("/cases").json()) == 2


def test_malformed_payload_with_a_valid_signature_is_still_rejected(client):
    response = post_signed_webhook(client, "/webhooks/subscription-halted", {"event": "subscription.halted", "payload": {}})

    assert response.status_code == 400
    assert client.get("/cases").json() == []


def test_wrong_event_type_is_rejected(client):
    response = post_signed_webhook(client, "/webhooks/subscription-halted", {"event": "subscription.pending", "payload": {}})

    assert response.status_code == 400
    assert client.get("/cases").json() == []
