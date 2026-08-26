"""Simulator-backed Gateway (ticket 14): wires ticket 02's frozen generator
into the Gateway seam so a synthetic case's execution outcomes are drawn
from its hidden ground truth's response curves, instead of `FakeGateway`'s
unconditional success.

Lives outside `app/simulator/` deliberately -- that package stays
independent of Decision Engine/Policy Engine code (ADR-0007, enforced by
`tests/test_simulator.py`). This module is the bridge between the simulator
and the Gateway Protocol it satisfies, so it's allowed to depend on both.
"""

from __future__ import annotations

import random
from uuid import uuid4

from app.gateway import ParsedWebhookEvent, PaymentLinkResult, ResumeChargeResult, parse_webhook_payload
from app.models import Intervention
from app.simulator.generator import HiddenGroundTruth, SimulatedCase, resolve_intervention


class SimulatorGateway:
    """One instance per synthetic case. Fatigue-decay attempt counts (per
    `Intervention`) are tracked here, case-local -- mirroring how the frozen
    generator's `resolve_intervention` scopes `prior_attempts_of_this_intervention`
    to a single case's own history, never pooled across cases.

    Satisfies the same `Gateway` Protocol as `FakeGateway`/`RazorpayGateway`;
    nothing above the seam (app/intake.py, app/lifecycle.py) can tell it apart
    from either.
    """

    def __init__(self, hidden: HiddenGroundTruth, *, rng: random.Random) -> None:
        # `case_index` is never read by `resolve_intervention` (only
        # `case.hidden` is) -- 0 is a placeholder to satisfy SimulatedCase's
        # shape, not a meaningful id.
        self._case = SimulatedCase(case_index=0, hidden=hidden)
        self._rng = rng
        self._attempts: dict[Intervention, int] = {}
        self.last_outcome: bool | None = None

    def resolve(self, intervention: Intervention) -> bool:
        """Draws this case's outcome for `intervention`, applying fatigue decay
        for however many times it's already been resolved on this case.

        Exposed as a public method (not just used internally by
        `create_payment_link`/`resume_charge`) because `NO_ACTION` has no
        Gateway call to hang an outcome off of -- its spontaneous-recovery
        outcome is resolved the same way here, just invoked by a different
        caller (`app/simulator_driver.py`).
        """
        prior_attempts = self._attempts.get(intervention, 0)
        outcome = resolve_intervention(
            self._case, intervention, prior_attempts_of_this_intervention=prior_attempts, rng=self._rng
        )
        self._attempts[intervention] = prior_attempts + 1
        self.last_outcome = outcome
        return outcome

    def create_payment_link(
        self,
        *,
        case_id: str,
        amount: int,
        currency: str,
        description: str,
        customer_contact: dict[str, str],
    ) -> PaymentLinkResult:
        self.resolve(Intervention.PAYMENT_RETRY)
        link_id = f"plink_sim_{uuid4().hex[:14]}"
        return PaymentLinkResult(
            payment_link_id=link_id,
            short_url=f"https://simulated.razorpay.link/{link_id}",
            status="created",
        )

    def resume_charge(self, *, case_id: str, subscription_id: str) -> ResumeChargeResult:
        self.resolve(Intervention.RESUME_CHARGE)
        return ResumeChargeResult(subscription_id=subscription_id, status="charge_pending")

    def parse_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> ParsedWebhookEvent:
        return parse_webhook_payload(raw_body)
