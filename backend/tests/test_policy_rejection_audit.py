"""Ticket 05: a Policy Engine rejection is visible in the case's audit trail."""

from app.policy import PolicyConfig
from tests.conftest import post_signed_webhook, synthetic_payment_failed_payload


def test_rejected_proposal_audit_entry_names_constraint_and_rejected_value(client, monkeypatch):
    # Force a rejection on the very first (only) attempt by dropping the retry ceiling to 0.
    monkeypatch.setattr(
        "app.intake.DEFAULT_POLICY_CONFIG",
        PolicyConfig(max_discount_pct=20.0, max_payment_retries=0, max_interventions_per_customer=5, recovery_budget=10_000_00),
    )

    response = post_signed_webhook(client, "/webhooks/payment-failed", synthetic_payment_failed_payload())

    assert response.status_code == 200
    case = response.json()

    policy_check = next(entry for entry in case["history"] if entry["entry_type"] == "policy_check")
    assert policy_check["data"]["approved"] is False
    assert policy_check["data"]["violated_constraint"] == "max_payment_retries"
    assert policy_check["data"]["proposed_value"] == 1
    assert "max_payment_retries" in policy_check["data"]["reason"]

    # A rejection means nothing executes: no execution entry, no payment link.
    entry_types = [entry["entry_type"] for entry in case["history"]]
    assert "execution" not in entry_types
