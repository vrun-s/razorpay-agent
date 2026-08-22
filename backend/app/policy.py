"""Policy Engine — ticket 01 stub.

Pass-through: every proposed Intervention is approved unmodified. Ticket 05
replaces this with real merchant-defined constraint checks (max discount,
retry ceilings, escalation thresholds); the `PolicyResult` shape here is what
that ticket builds against.
"""

from dataclasses import dataclass

from app.models import Intervention, RecoveryCase


@dataclass(frozen=True)
class PolicyResult:
    approved: bool
    intervention: Intervention
    reason: str | None = None


def evaluate(case: RecoveryCase, intervention: Intervention) -> PolicyResult:
    return PolicyResult(approved=True, intervention=intervention, reason=None)
