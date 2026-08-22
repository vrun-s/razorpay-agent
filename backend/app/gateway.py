"""The Gateway/Executor seam (spec: "the one seam").

Everything above this line — Decision Engine, Policy Engine, case lifecycle —
never knows or cares whether it's talking to the fake in-process gateway
(this module's `FakeGateway`) or a real Razorpay-backed implementation
(ticket 13). Both satisfy the same `Gateway` protocol.

This exact shape is what tickets 03 and 13 build against; it must not need
to change later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4


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
    ) -> PaymentLinkResult: ...

    def resume_charge(self, *, case_id: str, subscription_id: str) -> ResumeChargeResult: ...

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
    ) -> PaymentLinkResult:
        link_id = f"plink_fake_{uuid4().hex[:14]}"
        return PaymentLinkResult(
            payment_link_id=link_id,
            short_url=f"https://fake.razorpay.link/{link_id}",
            status="created",
        )

    def resume_charge(self, *, case_id: str, subscription_id: str) -> ResumeChargeResult:
        return ResumeChargeResult(subscription_id=subscription_id, status="charge_pending")

    def parse_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> ParsedWebhookEvent:
        payload = json.loads(raw_body)
        return ParsedWebhookEvent(event=payload.get("event", ""), payload=payload)


_default_gateway = FakeGateway()


def get_gateway() -> Gateway:
    return _default_gateway
