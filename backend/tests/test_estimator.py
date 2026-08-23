"""Ticket 07: the Beta-Bernoulli estimator (ADR-0006) -- pure, DB-free seam."""

from app.estimator import (
    CustomerHistory,
    CustomerSegmentProxy,
    Estimator,
    EstimatorCellKey,
    customer_segment_proxy,
)
from app.models import EventSource, Intervention


def _key(failure_reason: str = "insufficient_funds", intervention: Intervention = Intervention.PAYMENT_RETRY) -> EstimatorCellKey:
    return EstimatorCellKey(
        failure_reason=failure_reason, customer_segment_proxy=CustomerSegmentProxy.RELIABLE, intervention=intervention
    )


# -- customer_segment_proxy threshold boundaries --------------------------


def test_low_order_count_is_new():
    history = CustomerHistory(order_count=2, avg_order_value=0, payment_reliability_rate=1.0)
    assert customer_segment_proxy(history) == CustomerSegmentProxy.NEW


def test_order_count_at_the_established_threshold_is_not_new():
    history = CustomerHistory(order_count=3, avg_order_value=0, payment_reliability_rate=1.0)
    assert customer_segment_proxy(history) != CustomerSegmentProxy.NEW


def test_established_low_reliability_is_at_risk():
    history = CustomerHistory(order_count=10, avg_order_value=0, payment_reliability_rate=0.49)
    assert customer_segment_proxy(history) == CustomerSegmentProxy.AT_RISK


def test_reliability_at_the_at_risk_threshold_is_not_at_risk():
    history = CustomerHistory(order_count=10, avg_order_value=0, payment_reliability_rate=0.5)
    assert customer_segment_proxy(history) != CustomerSegmentProxy.AT_RISK


def test_established_reliable_high_aov_is_high_value():
    history = CustomerHistory(order_count=10, avg_order_value=100_000, payment_reliability_rate=0.9)
    assert customer_segment_proxy(history) == CustomerSegmentProxy.HIGH_VALUE


def test_aov_just_under_the_high_value_threshold_is_reliable_not_high_value():
    history = CustomerHistory(order_count=10, avg_order_value=99_999, payment_reliability_rate=0.9)
    assert customer_segment_proxy(history) == CustomerSegmentProxy.RELIABLE


# -- posterior update -------------------------------------------------------


def test_cold_start_point_estimate_is_one_half():
    estimator = Estimator()
    estimate = estimator.estimate(_key())
    assert estimate.point_estimate == 0.5  # Beta(2,2) mean


def test_simulated_success_increases_the_point_estimate():
    estimator = Estimator()
    before = estimator.estimate(_key()).point_estimate

    estimator.update(_key(), source=EventSource.SIMULATED, success=True)

    after = estimator.estimate(_key()).point_estimate
    assert after > before


def test_simulated_failure_decreases_the_point_estimate():
    estimator = Estimator()
    before = estimator.estimate(_key()).point_estimate

    estimator.update(_key(), source=EventSource.SIMULATED, success=False)

    after = estimator.estimate(_key()).point_estimate
    assert after < before


def test_real_tagged_outcome_does_not_change_the_posterior():
    estimator = Estimator()
    before = estimator.estimate(_key())

    estimator.update(_key(), source=EventSource.REAL, success=True)

    after = estimator.estimate(_key())
    assert after == before


def test_cells_are_independent():
    estimator = Estimator()
    other_key = _key(intervention=Intervention.NO_ACTION)

    estimator.update(_key(), source=EventSource.SIMULATED, success=True)

    assert estimator.estimate(other_key).point_estimate == 0.5


# -- uncertainty --------------------------------------------------------


def test_uncertainty_narrows_as_observations_accumulate():
    estimator = Estimator()
    key = _key()
    cold_start_uncertainty = estimator.estimate(key).uncertainty

    for _ in range(20):
        estimator.update(key, source=EventSource.SIMULATED, success=True)

    warmed_up_uncertainty = estimator.estimate(key).uncertainty
    assert warmed_up_uncertainty < cold_start_uncertainty


def test_real_tagged_outcomes_do_not_narrow_uncertainty():
    estimator = Estimator()
    key = _key()
    cold_start_uncertainty = estimator.estimate(key).uncertainty

    for _ in range(20):
        estimator.update(key, source=EventSource.REAL, success=True)

    assert estimator.estimate(key).uncertainty == cold_start_uncertainty
