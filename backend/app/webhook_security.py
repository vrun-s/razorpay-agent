"""HMAC-SHA256 verification for inbound Razorpay webhooks (ticket 04).

Razorpay signs each webhook body with the merchant's webhook secret, in the
`X-Razorpay-Signature` header. Verifying it before anything downstream runs
is what makes a synthetic payload signed with our own secret indistinguishable,
at the ingestion boundary, from a real Razorpay-originated one (spec user
story 4) -- and rejects anything that isn't.
"""

from __future__ import annotations

import hashlib
import hmac


class InvalidWebhookSignatureError(Exception):
    """Raised when a webhook's signature does not match its raw body."""


def sign(raw_body: bytes, secret: str) -> str:
    """Compute the HMAC-SHA256 hex digest Razorpay expects in X-Razorpay-Signature."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify(*, raw_body: bytes, signature: str, secret: str) -> None:
    """Raise InvalidWebhookSignatureError unless `signature` matches `raw_body` under `secret`."""
    expected = sign(raw_body, secret)
    if not hmac.compare_digest(expected, signature):
        raise InvalidWebhookSignatureError
