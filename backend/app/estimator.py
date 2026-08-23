"""The Decision Engine's Beta-Bernoulli estimator (ticket 07, ADR-0006).

A per-`(failure_reason, customer_segment_proxy, intervention)` cell posterior,
updated online only from the synthetic simulation stream -- a `real`-tagged
outcome is a replay of a decision already counted, not independent evidence
(ADR-0006, ADR-0007's simulator<->Razorpay execution boundary).

`customer_segment_proxy`'s thresholds are this module's own, chosen without
looking at the Synthetic Merchant Simulator's persona/response-curve
parameters (app/simulator/personas.py, app/simulator/response_curves.py) --
ADR-0007 requires the two stay independent, permanently, at runtime.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum

from app.models import EventSource, Intervention

# -- Customer Segment Proxy (CONTEXT.md) -------------------------------------


class CustomerSegmentProxy(StrEnum):
    """Deterministic buckets computed from observable Customer History -- never the
    simulator's hidden Customer Segment ground truth (CONTEXT.md distinguishes the two)."""

    NEW = "new"
    AT_RISK = "at_risk"
    HIGH_VALUE = "high_value"
    RELIABLE = "reliable"


@dataclass(frozen=True)
class CustomerHistory:
    """Observable-only inputs to `customer_segment_proxy` (CONTEXT.md: Customer History)."""

    order_count: int
    avg_order_value: int  # paise, same convention as Payment.amount
    payment_reliability_rate: float  # 0..1


# Fixed thresholds (CONTEXT.md: "via fixed thresholds", never an LLM call).
NEW_CUSTOMER_ORDER_COUNT_THRESHOLD = 3  # order_count below this -> NEW
AT_RISK_RELIABILITY_THRESHOLD = 0.5  # reliability below this (once established) -> AT_RISK
HIGH_VALUE_AOV_THRESHOLD = 100_000  # avg_order_value at/above this (once established, reliable) -> HIGH_VALUE


def customer_segment_proxy(history: CustomerHistory) -> CustomerSegmentProxy:
    if history.order_count < NEW_CUSTOMER_ORDER_COUNT_THRESHOLD:
        return CustomerSegmentProxy.NEW
    if history.payment_reliability_rate < AT_RISK_RELIABILITY_THRESHOLD:
        return CustomerSegmentProxy.AT_RISK
    if history.avg_order_value >= HIGH_VALUE_AOV_THRESHOLD:
        return CustomerSegmentProxy.HIGH_VALUE
    return CustomerSegmentProxy.RELIABLE


# -- Beta-Bernoulli posterior, one cell per (failure_reason, segment, intervention) ------


@dataclass(frozen=True)
class EstimatorCellKey:
    failure_reason: str
    customer_segment_proxy: CustomerSegmentProxy
    intervention: Intervention


@dataclass(frozen=True)
class Estimate:
    point_estimate: float
    uncertainty: float  # ~95% credible interval width (normal approximation, no scipy dependency)


_COLD_START_ALPHA = 2.0
_COLD_START_BETA = 2.0
_CREDIBLE_INTERVAL_Z = 1.96  # ~95%, normal approximation to the Beta posterior


@dataclass
class _Posterior:
    alpha: float = field(default=_COLD_START_ALPHA)
    beta: float = field(default=_COLD_START_BETA)


class Estimator:
    """In-memory per-cell posterior store. One process-wide instance via `get_estimator()`.

    FastAPI runs sync routes across threadpool threads (ADR-0008), and
    multiple webhooks can update the same cell concurrently -- `cell.alpha
    += 1` is a read-modify-write, not atomic under the GIL, so a lock guards
    every read and write to avoid losing an update under concurrency.
    """

    def __init__(self) -> None:
        self._cells: dict[EstimatorCellKey, _Posterior] = {}
        self._lock = threading.Lock()

    def _cell(self, key: EstimatorCellKey) -> _Posterior:
        return self._cells.setdefault(key, _Posterior())

    def estimate(self, key: EstimatorCellKey) -> Estimate:
        with self._lock:
            cell = self._cell(key)
            alpha, beta = cell.alpha, cell.beta
        total = alpha + beta
        point_estimate = alpha / total
        variance = (alpha * beta) / (total**2 * (total + 1))
        uncertainty = 2 * _CREDIBLE_INTERVAL_Z * variance**0.5
        return Estimate(point_estimate=point_estimate, uncertainty=uncertainty)

    def update(self, key: EstimatorCellKey, *, source: EventSource, success: bool) -> None:
        """Updates the cell's posterior -- but only for a `simulated`-sourced outcome (ADR-0006)."""
        if source != EventSource.SIMULATED:
            return
        with self._lock:
            cell = self._cell(key)
            if success:
                cell.alpha += 1
            else:
                cell.beta += 1


_default_estimator = Estimator()


def get_estimator() -> Estimator:
    return _default_estimator
