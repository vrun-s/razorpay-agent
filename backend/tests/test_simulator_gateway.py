"""Ticket 14: `SimulatorGateway` -- the frozen generator wired into the
Gateway seam. `test_simulator_driver.py` covers the full pipeline; this file
covers the gateway's own outcome-resolution contract in isolation, including
the statistical sanity check that its draws actually track the generator's
known response curves.
"""

import json
import random

import pytest

from app.gateway import PaymentLinkResult, ResumeChargeResult
from app.models import Intervention
from app.simulator.generator import generate_population, resolve_intervention
from app.simulator.personas import PERSONA_MIX
from app.simulator.response_curves import BASE_RESPONSE_CURVES
from app.simulator_gateway import SimulatorGateway


def _gateway(seed: int = 1, rng_seed: int = 99) -> SimulatorGateway:
    [case] = generate_population(seed=seed, size=1)
    return SimulatorGateway(case.hidden, rng=random.Random(rng_seed))


def test_create_payment_link_resolves_payment_retry_and_returns_the_shared_shape():
    gateway = _gateway()

    result = gateway.create_payment_link(
        case_id="case-1", amount=50000, currency="INR", description="x", customer_contact={}
    )

    assert isinstance(result, PaymentLinkResult)
    assert result.payment_link_id.startswith("plink_sim_")
    assert result.short_url.startswith("https://")
    assert result.status == "created"
    assert gateway.last_outcome in (True, False)


def test_resume_charge_resolves_resume_charge_and_returns_the_shared_shape():
    gateway = _gateway()

    result = gateway.resume_charge(case_id="case-1", subscription_id="sub_1")

    assert isinstance(result, ResumeChargeResult)
    assert result.subscription_id == "sub_1"
    assert result.status == "charge_pending"
    assert gateway.last_outcome in (True, False)


def test_create_payment_link_forwards_incentive_amount_to_resolve():
    """ADR-0014: create_payment_link's incentive_amount reaches the outcome
    draw via resolve(), checked by matching against the generator's own
    resolve_intervention called directly with the same incentive_amount."""
    [case] = generate_population(seed=5, size=1)
    gateway = SimulatorGateway(case.hidden, rng=random.Random(42))

    gateway.create_payment_link(
        case_id="case-1", amount=50000, currency="INR", description="x", customer_contact={}, incentive_amount=2_500
    )

    expected = resolve_intervention(
        case, Intervention.PAYMENT_RETRY, prior_attempts_of_this_intervention=0, rng=random.Random(42), incentive_amount=2_500
    )
    assert gateway.last_outcome == expected


def test_resolve_with_incentive_amount_differs_from_resolve_without_it_statistically():
    """A large sample's hit rate should trend upward when every draw carries
    a real incentive_amount, mirroring the fatigue-decay statistical check
    below."""
    [case] = generate_population(seed=11, size=1)
    trials = 400

    def hit_rate(incentive_amount: int) -> float:
        hits = 0
        for i in range(trials):
            gateway = SimulatorGateway(case.hidden, rng=random.Random(2000 + i))
            if gateway.resolve(Intervention.PAYMENT_RETRY, incentive_amount=incentive_amount):
                hits += 1
        return hits / trials

    assert hit_rate(2_500) > hit_rate(0)


def test_parse_webhook_extracts_event_and_payload_same_as_other_gateways():
    gateway = _gateway()
    body = json.dumps({"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay_1"}}}}).encode()

    parsed = gateway.parse_webhook(headers={}, raw_body=body)

    assert parsed.event == "payment.failed"
    assert parsed.payload["payload"]["payment"]["entity"]["id"] == "pay_1"


def test_resolve_matches_the_generators_own_resolve_intervention_given_the_same_rng_seed():
    [case] = generate_population(seed=5, size=1)
    gateway = SimulatorGateway(case.hidden, rng=random.Random(42))

    expected = resolve_intervention(case, Intervention.PAYMENT_RETRY, prior_attempts_of_this_intervention=0, rng=random.Random(42))

    assert gateway.resolve(Intervention.PAYMENT_RETRY) == expected


def test_repeated_resolve_of_the_same_intervention_applies_fatigue_decay():
    """A gateway resolving the same intervention many times over should see its
    hit rate trend downward, mirroring `decayed_probability`'s monotonic decay
    -- checked statistically (large sample per attempt number), not case by case,
    since each individual draw is still a coin flip."""
    [case] = generate_population(seed=11, size=1)
    trials_per_attempt = 400

    def hit_rate(attempt_number: int) -> float:
        hits = 0
        for i in range(trials_per_attempt):
            gateway = SimulatorGateway(case.hidden, rng=random.Random(1000 + i))
            for _ in range(attempt_number):
                gateway.resolve(Intervention.PAYMENT_RETRY)
            if gateway.resolve(Intervention.PAYMENT_RETRY):
                hits += 1
        return hits / trials_per_attempt

    assert hit_rate(0) > hit_rate(3)


def _rng_from_state(state) -> random.Random:
    rng = random.Random()
    rng.setstate(state)
    return rng


def test_attempt_counts_are_tracked_independently_per_intervention():
    """Two prior PAYMENT_RETRY resolutions shouldn't carry any fatigue decay
    into a RESUME_CHARGE resolution on the same case -- checked by comparing
    the gateway's draw against the generator's own `resolve_intervention`
    called directly with `prior_attempts_of_this_intervention=0`, from an rng
    cloned to the exact state the gateway's rng was in at that point."""
    [case] = generate_population(seed=1, size=1)
    rng = random.Random(99)
    gateway = SimulatorGateway(case.hidden, rng=rng)

    gateway.resolve(Intervention.PAYMENT_RETRY)
    gateway.resolve(Intervention.PAYMENT_RETRY)
    state_before_resume_charge = rng.getstate()

    actual = gateway.resolve(Intervention.RESUME_CHARGE)

    expected = resolve_intervention(
        case,
        Intervention.RESUME_CHARGE,
        prior_attempts_of_this_intervention=0,
        rng=_rng_from_state(state_before_resume_charge),
    )
    assert actual == expected


# -- Statistical sanity check (ticket 14 acceptance criterion) --------------


def test_first_attempt_outcomes_across_a_population_plausibly_match_the_weighted_response_curve():
    """Drives a large population's first PAYMENT_RETRY attempt through
    SimulatorGateway (fatigue-free, matching the generator's own
    `prior_attempts_of_this_intervention=0` case) and checks the aggregate hit
    rate against the known curves' population-weighted average -- not exact
    equality, a statistical sanity check per ticket 14's own acceptance
    criterion."""
    population = generate_population(seed=123, size=4000)
    rng = random.Random(7)

    recoveries = 0
    for simulated in population:
        gateway = SimulatorGateway(simulated.hidden, rng=rng)
        if gateway.resolve(Intervention.PAYMENT_RETRY):
            recoveries += 1
    observed_rate = recoveries / len(population)

    expected_rate = sum(
        PERSONA_MIX[persona] * BASE_RESPONSE_CURVES[persona][Intervention.PAYMENT_RETRY] for persona in PERSONA_MIX
    )

    assert observed_rate == pytest.approx(expected_rate, abs=0.03)
