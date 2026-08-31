"""The Gateway/Executor seam (spec: "the one seam").

Everything above this line — Decision Engine, Policy Engine, case lifecycle —
never knows or cares whether it's talking to the fake in-process gateway
(this module's `FakeGateway`) or a real Razorpay-backed implementation
(ticket 13). Both satisfy the same `Gateway` protocol.

This exact shape is what tickets 03 and 13 build against, and was declared
final at the time. Ticket 19 / ADR-0014 is the one documented, additive
exception (the same kind of deliberate, disclosed revision ADR-0010 made to
ADR-0009's Policy Engine shape): `create_payment_link`/`resume_charge` gain
an `incentive_amount: int = 0` keyword-only parameter so `SimulatorGateway`
(app/simulator_gateway.py) knows whether *this* execution carried a real
Incentive and should apply the response-curve uplift. `FakeGateway` and
`RazorpayGateway` accept and ignore it -- reflecting a real discount in what
Razorpay is actually charged is out of this ticket's scope. Every existing
caller that doesn't pass it keeps its old behavior unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

import httpx

from app.config import settings


@dataclass(frozen=True)
class PaymentLinkResult:
    payment_link_id: str
    short_url: str
    status: str


@dataclass(frozen=True)
class ResumeChargeResult:
    subscription_id: str
    status: str


@dataclass(frozen=True)
class ParsedWebhookEvent:
    event: str
    payload: dict[str, Any] = field(default_factory=dict)


class GatewayError(Exception):
    """A real Gateway call reached Razorpay but got back a non-2xx response."""


def parse_webhook_payload(raw_body: bytes) -> ParsedWebhookEvent:
    """Shared by every Gateway implementation (including ticket 14's
    `SimulatorGateway`, app/simulator_gateway.py): signature verification
    already happened at the ingestion boundary (`app/webhook_security.py`)
    before `parse_webhook` runs, so this is pure JSON shape extraction,
    identical whether the body came from the simulator or real Razorpay."""
    payload = json.loads(raw_body)
    return ParsedWebhookEvent(event=payload.get("event", ""), payload=payload)


class Gateway(Protocol):
    """One abstraction both the Synthetic Merchant Simulator and real Razorpay drive from the outside."""

    def create_payment_link(
        self,
        *,
        case_id: str,
        amount: int,
        currency: str,
        description: str,
        customer_contact: dict[str, str],
        incentive_amount: int = 0,
    ) -> PaymentLinkResult: ...

    def resume_charge(self, *, case_id: str, subscription_id: str, incentive_amount: int = 0) -> ResumeChargeResult: ...

    def parse_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> ParsedWebhookEvent: ...


class FakeGateway:
    """Stub Gateway implementation. Makes no real Razorpay calls."""

    def create_payment_link(
        self,
        *,
        case_id: str,
        amount: int,
        currency: str,
        description: str,
        customer_contact: dict[str, str],
        incentive_amount: int = 0,
    ) -> PaymentLinkResult:
        link_id = f"plink_fake_{uuid4().hex[:14]}"
        return PaymentLinkResult(
            payment_link_id=link_id,
            short_url=f"https://fake.razorpay.link/{link_id}",
            status="created",
        )

    def resume_charge(self, *, case_id: str, subscription_id: str, incentive_amount: int = 0) -> ResumeChargeResult:
        return ResumeChargeResult(subscription_id=subscription_id, status="charge_pending")

    def parse_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> ParsedWebhookEvent:
        return parse_webhook_payload(raw_body)


class RazorpayGateway:
    """Real Razorpay-backed Gateway implementation (ticket 13). Satisfies the
    same `Gateway` Protocol as `FakeGateway` -- nothing above this seam
    (Decision Engine, Policy Engine, case lifecycle) can tell them apart.
    """

    _BASE_URL = "https://api.razorpay.com/v1"

    def __init__(self, *, key_id: str, key_secret: str, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(base_url=self._BASE_URL, auth=(key_id, key_secret), timeout=10.0)

    def _post(self, path: str, *, json_body: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(path, json=json_body)
        if response.is_error:
            detail = response.json().get("error", {}).get("description", response.text)
            raise GatewayError(f"Razorpay {path} returned {response.status_code}: {detail}")
        return response.json()

    def create_payment_link(
        self,
        *,
        case_id: str,
        amount: int,
        currency: str,
        description: str,
        customer_contact: dict[str, str],
        incentive_amount: int = 0,
    ) -> PaymentLinkResult:
        # `incentive_amount` is accepted (Gateway Protocol parity) but not yet
        # applied to what Razorpay actually charges -- reflecting a real
        # discount in the created link's amount is out of ticket 19's scope.
        customer = {k: v for k, v in customer_contact.items() if k in ("name", "email", "contact") and v}
        data = self._post(
            "/payment_links",
            json_body={
                "amount": amount,
                "currency": currency,
                "description": description,
                "customer": customer,
                "notify": {"sms": bool(customer.get("contact")), "email": bool(customer.get("email"))},
                "notes": {"case_id": case_id},
            },
        )
        return PaymentLinkResult(payment_link_id=data["id"], short_url=data["short_url"], status=data["status"])

    def resume_charge(self, *, case_id: str, subscription_id: str, incentive_amount: int = 0) -> ResumeChargeResult:
        """Ticket-12 disclosed gap, real-integration side: Razorpay's `/resume`
        endpoint is documented for subscriptions in `paused` state, not
        `halted` -- there is no separate "resume from halted" API. This is
        the closest real endpoint to CONTEXT.md's Resume Charge concept;
        calling it against a genuinely `halted` subscription in test mode may
        itself return a Razorpay-side rejection, surfaced here as a
        `GatewayError` like any other failure response.
        """
        data = self._post(f"/subscriptions/{subscription_id}/resume", json_body={"resume_at": "now"})
        return ResumeChargeResult(subscription_id=data.get("id", subscription_id), status=data["status"])

    def parse_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> ParsedWebhookEvent:
        return parse_webhook_payload(raw_body)


_default_gateway = FakeGateway()


def get_gateway() -> Gateway:
    """Ticket 13: swaps Gateway implementation on `settings.gateway_backend`
    alone -- no caller of `get_gateway()` (main.py, routers/*) branches on
    which one it gets back.
    """
    if settings.gateway_backend == "razorpay":
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise RuntimeError(
                "gateway_backend is 'razorpay' but RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET are not configured"
            )
        return RazorpayGateway(key_id=settings.razorpay_key_id, key_secret=settings.razorpay_key_secret)
    return _default_gateway
