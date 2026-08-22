"""End-to-end tracer-bullet flow: POST a synthetic payment.failed payload ->
a Recovery Case is created, decided, policy-checked, and executed against the
fake Gateway -- and shows up via GET /cases with its recorded outcome.
"""


def _synthetic_payment_failed_payload(payment_id: str = "pay_test123") -> dict:
    return {
        "entity": "event",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 50000,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_test123",
                    "email": "customer@example.com",
                    "contact": "+911234567890",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed due to insufficient funds",
                }
            }
        },
        "created_at": 1735689600,
    }


def test_payment_failed_webhook_creates_a_case_with_recorded_execution(client):
    response = client.post("/webhooks/payment-failed", json=_synthetic_payment_failed_payload())

    assert response.status_code == 200
    case = response.json()
    assert case["workflow_type"] == "failed_payment"
    assert case["status"] == "open"
    assert case["source"] == "simulated"

    entry_types = [entry["entry_type"] for entry in case["history"]]
    assert entry_types == ["case_created", "decision", "policy_check", "execution"]

    execution = case["history"][-1]
    assert execution["data"]["status"] == "created"
    assert execution["data"]["payment_link_id"].startswith("plink_fake_")


def test_created_case_is_visible_via_list_cases_with_its_outcome(client):
    post_response = client.post("/webhooks/payment-failed", json=_synthetic_payment_failed_payload())
    case_id = post_response.json()["id"]

    list_response = client.get("/cases")

    assert list_response.status_code == 200
    cases = list_response.json()
    assert any(c["id"] == case_id for c in cases)
    listed_case = next(c for c in cases if c["id"] == case_id)
    assert listed_case["history"][-1]["entry_type"] == "execution"


def test_malformed_payload_is_rejected(client):
    response = client.post("/webhooks/payment-failed", json={"event": "payment.failed", "payload": {}})

    assert response.status_code == 400


def test_wrong_event_type_is_rejected(client):
    response = client.post(
        "/webhooks/payment-failed",
        json={"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_1"}}}},
    )

    assert response.status_code == 400
