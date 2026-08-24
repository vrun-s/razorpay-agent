"""Ticket 08: the LLM's three fixed, bounded roles (ADR-0006) -- diagnosis,
narration, escalation flagging. `FakeLLMClient` is the deterministic double
exercised here; `get_llm_client` falls back to it whenever no
`ANTHROPIC_API_KEY` is configured (true for the whole test suite)."""

from app.llm import FAILURE_REASON_CATEGORIES, FakeLLMClient, get_llm_client


def test_get_llm_client_returns_the_fake_without_an_api_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    assert isinstance(get_llm_client(), FakeLLMClient)


# -- diagnose_failure_reason -------------------------------------------------


def test_diagnoses_insufficient_funds():
    client = FakeLLMClient()
    category = client.diagnose_failure_reason(decline_text="Payment failed due to insufficient funds in account")
    assert category == "insufficient_funds"


def test_diagnoses_expired_card():
    client = FakeLLMClient()
    category = client.diagnose_failure_reason(decline_text="Card expired, please use a different card")
    assert category == "expired_card"


def test_diagnoses_fraud_suspected():
    client = FakeLLMClient()
    category = client.diagnose_failure_reason(decline_text="Transaction blocked: suspected fraud")
    assert category == "fraud_suspected"


def test_unrecognized_decline_text_maps_to_unknown():
    client = FakeLLMClient()
    category = client.diagnose_failure_reason(decline_text="something completely unrelated to any bank code")
    assert category == "unknown"


def test_diagnosis_always_lands_in_the_known_category_set():
    client = FakeLLMClient()
    for text in ["insufficient funds", "expired card", "gibberish xyz", ""]:
        assert client.diagnose_failure_reason(decline_text=text) in FAILURE_REASON_CATEGORIES


# -- generate_justification --------------------------------------------------


def test_justification_is_a_nonempty_string_mentioning_the_intervention():
    client = FakeLLMClient()
    justification = client.generate_justification(
        intervention="payment_retry",
        point_estimate=0.62,
        uncertainty=0.1,
        segment="reliable",
        failure_reason="insufficient_funds",
    )
    assert isinstance(justification, str) and justification
    assert "payment_retry" in justification


# -- flag_escalation -----------------------------------------------------------


def test_angry_customer_signal_triggers_escalation():
    client = FakeLLMClient()
    assert client.flag_escalation(signal_text="This is ridiculous, I'm furious and want a refund now!") is True


def test_neutral_customer_signal_does_not_trigger_escalation():
    client = FakeLLMClient()
    assert client.flag_escalation(signal_text="Ok, I'll try the payment link again.") is False
