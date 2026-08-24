"""The LLM's three fixed, bounded roles (ticket 08, ADR-0006): diagnose
`failure_reason` from unstructured decline text, generate a Reassessment's
audit-trail justification, and flag qualitative-signal escalation. Nothing
here ever produces a recovery-probability number -- that's app/estimator.py's
Beta-Bernoulli posterior alone.

`LLMClient` mirrors app/gateway.py's `Gateway` seam: `AnthropicLLMClient` and
`FakeLLMClient` satisfy the same `Protocol`, so the case lifecycle never
knows or cares which one it's holding. `get_llm_client()` falls back to the
fake whenever `ANTHROPIC_API_KEY` isn't configured (true for the whole test
suite, and for local dev until the key is added to `.env`), the same way
app/gateway.py's `get_gateway()` stands in for the real Razorpay gateway
before ticket 13 exists.
"""

from __future__ import annotations

from typing import Protocol

from app.config import settings

# Known failure_reason categories (spec user story 18) -- the estimator
# cell's failure_reason axis is only meaningful if every diagnosis, however
# messy the input decline text/bank code, lands in this fixed set.
FAILURE_REASON_CATEGORIES: tuple[str, ...] = (
    "insufficient_funds",
    "card_declined",
    "expired_card",
    "invalid_card_details",
    "bank_server_error",
    "fraud_suspected",
    "customer_cancelled",
    "unknown",
)

_MODEL = "claude-haiku-4-5-20251001"  # fast/cheap: bounded classification and short-text jobs, not open-ended reasoning


class LLMClient(Protocol):
    def diagnose_failure_reason(self, *, decline_text: str) -> str: ...

    def generate_justification(
        self, *, intervention: str, point_estimate: float, uncertainty: float, segment: str, failure_reason: str
    ) -> str: ...

    def flag_escalation(self, *, signal_text: str) -> bool: ...


class AnthropicLLMClient:
    """Real Claude-backed implementation (ADR-0008). Makes network calls."""

    def __init__(self, api_key: str) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)

    def _complete(self, prompt: str, *, max_tokens: int) -> str:
        response = self._client.messages.create(
            model=_MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()

    def diagnose_failure_reason(self, *, decline_text: str) -> str:
        prompt = (
            "Classify this payment decline into exactly one of these categories: "
            f"{', '.join(FAILURE_REASON_CATEGORIES)}.\n"
            f"Decline text/bank code: {decline_text!r}\n"
            "Respond with only the category name, nothing else."
        )
        category = self._complete(prompt, max_tokens=20).lower()
        return category if category in FAILURE_REASON_CATEGORIES else "unknown"

    def generate_justification(
        self, *, intervention: str, point_estimate: float, uncertainty: float, segment: str, failure_reason: str
    ) -> str:
        prompt = (
            "Write one concise sentence for a payment-recovery audit trail explaining this decision. "
            f"Chosen intervention: {intervention}. Estimated recovery probability: {point_estimate:.0%} "
            f"(uncertainty band width {uncertainty:.2f}). Customer segment: {segment}. "
            f"Failure reason: {failure_reason}. State the numbers as given -- do not invent your own."
        )
        return self._complete(prompt, max_tokens=120)

    def flag_escalation(self, *, signal_text: str) -> bool:
        prompt = (
            "A customer responded to an automated payment-recovery outreach with this message. "
            "Does the tone show anger, confusion, or distress serious enough that a human should "
            "step in, rather than the automated process continuing?\n"
            f"Message: {signal_text!r}\n"
            "Respond with only 'yes' or 'no'."
        )
        return self._complete(prompt, max_tokens=5).lower().startswith("y")


class FakeLLMClient:
    """Deterministic test/dev double (mirrors app/gateway.py's `FakeGateway`).
    Keyword-matches instead of calling out to Anthropic. Makes no real calls."""

    _DECLINE_KEYWORDS: tuple[tuple[str, str], ...] = (
        ("insufficient", "insufficient_funds"),
        ("expired", "expired_card"),
        ("invalid", "invalid_card_details"),
        ("fraud", "fraud_suspected"),
        ("cancel", "customer_cancelled"),
        ("server", "bank_server_error"),
        ("timeout", "bank_server_error"),
        ("declined", "card_declined"),
    )

    _ESCALATION_KEYWORDS: tuple[str, ...] = ("angry", "furious", "ridiculous", "scam", "confused", "lawyer", "frustrat")

    def diagnose_failure_reason(self, *, decline_text: str) -> str:
        lowered = decline_text.lower()
        for keyword, category in self._DECLINE_KEYWORDS:
            if keyword in lowered:
                return category
        return "unknown"

    def generate_justification(
        self, *, intervention: str, point_estimate: float, uncertainty: float, segment: str, failure_reason: str
    ) -> str:
        return (
            f"Estimated {point_estimate:.0%} recovery probability for {intervention} "
            f"({segment} segment, {failure_reason} failure reason)."
        )

    def flag_escalation(self, *, signal_text: str) -> bool:
        lowered = signal_text.lower()
        return any(keyword in lowered for keyword in self._ESCALATION_KEYWORDS)


_default_fake_client = FakeLLMClient()


def get_llm_client() -> LLMClient:
    """Real Anthropic client once `ANTHROPIC_API_KEY` is configured; the
    deterministic fake until then -- re-checked on every call (not cached
    across a settings change) since tests monkeypatch `settings` directly."""
    if settings.anthropic_api_key:
        return AnthropicLLMClient(api_key=settings.anthropic_api_key)
    return _default_fake_client
