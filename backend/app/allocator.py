"""Streaming Allocator (ticket 10, ADR-0003): online, arrival-order Recovery
Budget allocation with a withheld Reserved Budget.

Cases are decided on one at a time, in the order they arrive -- `decide()`
takes exactly one `AllocationCandidate` and returns exactly one
`AllocationDecision`. There is no batch/list method anywhere in this module:
the allocator structurally cannot see a case that hasn't arrived yet, the
same "no foresight" constraint ADR-0003 requires of the whole system. An
Offline-Optimal Allocation (CONTEXT.md) -- computed retrospectively over a
fully-observed case set, purely as an evaluation baseline -- is a separate,
later concern (ticket 15's evaluation harness), not this module's.

`BudgetLedger`'s Reserved Budget (CONTEXT.md) is not a separately-debited
pool: it's always `reserve_ratio` of whatever Recovery Budget remains right
now, recomputed on every read from `spent` alone. An "ordinary" candidate may
only spend from the non-reserved `available` pool; a candidate whose
uncertainty-discounted quality clears `min_quality_score` may additionally
draw against the reserve -- the mechanism that lets a mediocre case be
declined while a later, better one in the same run still gets funded.

`AllocationCandidate.incentive_amount` mirrors `ProposedIntervention`'s field
(ADR-0010) -- a real, non-zero Incentive cost as of ticket 19/ADR-0014 for a
`PAYMENT_RETRY`/`RESUME_CHARGE` proposal on a case with a non-zero
`case_value`. The reserve mechanism is what actually declines one of these
now, not just tested against a free proposal.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from app.merchant_config import DEFAULT_MERCHANT_CONFIG

# The estimator's own cold-start prior (Beta(2,2) mean, app/estimator.py) --
# a candidate must beat coin-flip odds, conservatively, to draw against the
# reserve. Chosen to match a documented existing constant, not an arbitrary one.
_DEFAULT_MIN_QUALITY_SCORE = 0.5

# Withhold a third of whatever Recovery Budget remains for better cases
# still to arrive (ADR-0003) -- a reasonable middle ground. Checked against
# every constant in app/simulator/personas.py and
# app/simulator/response_curves.py and deliberately kept distinct from all of
# them (ADR-0007's independence rule scopes to the estimator, not this
# module, but the same discipline applies: a coincidental match here would be
# just as misleading).
_DEFAULT_RESERVE_RATIO = 1 / 3


@dataclass
class BudgetLedger:
    """Tracks one Recovery Budget's spent/available/reserved amounts (paise),
    each queryable at any point in time (ticket 10's own acceptance criteria).

    `record_spend` is a read-modify-write on `spent`, the same hazard
    app/estimator.py's `Estimator` guards against for its posterior cells
    (FastAPI runs sync routes across threadpool threads, ADR-0008) -- a lock
    protects it here too.
    """

    recovery_budget: int
    reserve_ratio: float
    spent: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def remaining(self) -> int:
        return self.recovery_budget - self.spent

    @property
    def reserved(self) -> int:
        return round(self.remaining * self.reserve_ratio)

    @property
    def available(self) -> int:
        """Spendable right now without touching the reserve (CONTEXT.md: Reserved Budget)."""
        return self.remaining - self.reserved

    def record_spend(self, amount: int) -> None:
        with self._lock:
            self.spent += amount


@dataclass(frozen=True)
class AllocationCandidate:
    """What the Streaming Allocator evaluates for one case, in arrival order."""

    case_id: str
    point_estimate: float  # ticket 07 estimator's posterior mean
    uncertainty: float  # ticket 07 estimator's credible interval width
    incentive_amount: int = 0  # cost of the proposed Intervention, paise


@dataclass(frozen=True)
class AllocationDecision:
    funded: bool
    reason: str
    spent: int
    available: int
    reserved: int


class StreamingAllocator:
    """Decides, one arriving case at a time, whether to fund its proposed
    Intervention against a Recovery Budget with a withheld Reserved Budget.
    """

    def __init__(self, ledger: BudgetLedger, *, min_quality_score: float = _DEFAULT_MIN_QUALITY_SCORE) -> None:
        self.ledger = ledger
        self.min_quality_score = min_quality_score

    def decide(self, candidate: AllocationCandidate) -> AllocationDecision:
        ledger = self.ledger

        if candidate.incentive_amount > ledger.remaining:
            return self._decision(funded=False, reason="exceeds the entire remaining recovery_budget")

        if candidate.incentive_amount <= ledger.available:
            ledger.record_spend(candidate.incentive_amount)
            return self._decision(funded=True, reason="funded from available (non-reserved) budget")

        # Fits only by drawing against the reserve -- only a candidate good
        # enough (conservatively) may do that; uncertainty discounts the
        # point estimate per ADR-0006's rationale (a shaky, sparse cell reads
        # as riskier without a separate exploration algorithm).
        quality = candidate.point_estimate - candidate.uncertainty / 2
        if quality >= self.min_quality_score:
            ledger.record_spend(candidate.incentive_amount)
            return self._decision(funded=True, reason=f"quality {quality:.2f} clears the reserve bar {self.min_quality_score}")

        return self._decision(
            funded=False, reason=f"quality {quality:.2f} below reserve bar {self.min_quality_score} -- reserve held for a better case"
        )

    def _decision(self, *, funded: bool, reason: str) -> AllocationDecision:
        ledger = self.ledger
        return AllocationDecision(funded=funded, reason=reason, spent=ledger.spent, available=ledger.available, reserved=ledger.reserved)


_default_allocator: StreamingAllocator | None = None


def get_allocator() -> StreamingAllocator:
    """Process-wide default, mirroring app/estimator.py's `get_estimator()`
    singleton pattern (ADR-0008: no external state store, single-process
    demo). Built against `DEFAULT_MERCHANT_CONFIG.recovery_budget` -- the same
    number `DEFAULT_POLICY_CONFIG.recovery_budget` (app/policy.py) derives
    from, per ticket 19's unification.
    """
    global _default_allocator
    if _default_allocator is None:
        ledger = BudgetLedger(recovery_budget=DEFAULT_MERCHANT_CONFIG.recovery_budget, reserve_ratio=_DEFAULT_RESERVE_RATIO)
        _default_allocator = StreamingAllocator(ledger)
    return _default_allocator
