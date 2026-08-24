"""Ticket 09: escalation queue + human override, exercised end-to-end via the API."""

from app.policy import PolicyConfig
from tests.conftest import post_signed_webhook, synthetic_payment_failed_payload


def _escalate_via_policy_threshold(client, monkeypatch, *, amount: int = 60_000) -> dict:
    monkeypatch.setattr(
        "app.lifecycle.DEFAULT_POLICY_CONFIG",
        PolicyConfig(
            max_discount_pct=20.0, max_payment_retries=3, max_interventions_per_customer=5,
            recovery_budget=10_000_00, escalation_value_threshold=50_000,
        ),
    )
    payload = synthetic_payment_failed_payload()
    payload["payload"]["payment"]["entity"]["amount"] = amount
    response = post_signed_webhook(client, "/webhooks/payment-failed", payload)
    assert response.status_code == 200
    return response.json()


def test_a_high_value_case_appears_escalated(client, monkeypatch):
    case = _escalate_via_policy_threshold(client, monkeypatch)

    assert case["status"] == "escalated"
    entry_types = [entry["entry_type"] for entry in case["history"]]
    assert "case_escalated" in entry_types
    escalated_entry = next(e for e in case["history"] if e["entry_type"] == "case_escalated")
    assert "escalation_value_threshold" in escalated_entry["data"]["reason"]


def test_override_updates_case_state_and_history(client, monkeypatch):
    case = _escalate_via_policy_threshold(client, monkeypatch)

    response = client.post(f"/cases/{case['id']}/override", json={"intervention": "payment_retry"})

    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "open"
    entry_types = [entry["entry_type"] for entry in updated["history"]]
    assert entry_types.count("execution") == 1  # override's own execution, no earlier one (escalation pre-empted it)
    last_decision = [e for e in updated["history"] if e["entry_type"] == "decision"][-1]
    assert last_decision["data"] == {"intervention": "payment_retry", "source": "human"}


def test_override_rejects_an_intervention_invalid_for_the_workflow(client, monkeypatch):
    case = _escalate_via_policy_threshold(client, monkeypatch)

    response = client.post(f"/cases/{case['id']}/override", json={"intervention": "resume_charge"})

    assert response.status_code == 400


def test_override_on_a_non_escalated_case_is_rejected(client, monkeypatch):
    # No threshold configured -> the case stays OPEN, never escalates.
    payload = synthetic_payment_failed_payload()
    response = post_signed_webhook(client, "/webhooks/payment-failed", payload)
    case = response.json()
    assert case["status"] == "open"

    override_response = client.post(f"/cases/{case['id']}/override", json={"intervention": "payment_retry"})

    assert override_response.status_code == 409


def test_manual_resolve_closes_the_case_and_records_the_resolution(client, monkeypatch):
    case = _escalate_via_policy_threshold(client, monkeypatch)

    response = client.post(f"/cases/{case['id']}/resolve", json={"outcome": "recovered", "reason": "paid by phone"})

    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "recovered"
    recovered_entry = next(e for e in updated["history"] if e["entry_type"] == "case_recovered")
    assert recovered_entry["data"] == {"reason": "paid by phone", "resolved_by": "human"}


def test_override_on_a_missing_case_is_404(client):
    response = client.post("/cases/does-not-exist/override", json={"intervention": "payment_retry"})

    assert response.status_code == 404
