"""Ticket 10: Streaming Allocator -- online, arrival-order Recovery Budget
allocation with a withheld Reserved Budget (ADR-0003)."""

from app.allocator import AllocationCandidate, BudgetLedger, StreamingAllocator

_CASE_A = "case_a"
_CASE_B = "case_b"


def _candidate(case_id: str, *, point_estimate: float, uncertainty: float, incentive_amount: int = 0) -> AllocationCandidate:
    return AllocationCandidate(
        case_id=case_id, point_estimate=point_estimate, uncertainty=uncertainty, incentive_amount=incentive_amount
    )


# -- BudgetLedger arithmetic -------------------------------------------------


def test_ledger_starts_with_the_full_budget_available_minus_the_reserve():
    ledger = BudgetLedger(recovery_budget=1000, reserve_ratio=0.5)

    assert ledger.spent == 0
    assert ledger.reserved == 500
    assert ledger.available == 500


def test_ledger_spend_and_reserve_shrink_together_as_spend_grows():
    ledger = BudgetLedger(recovery_budget=1000, reserve_ratio=0.5)

    ledger.record_spend(200)

    assert ledger.spent == 200
    assert ledger.remaining == 800
    assert ledger.reserved == 400  # 50% of what's left, recomputed
    assert ledger.available == 400


def test_ledger_arithmetic_across_a_sequence_of_spends():
    ledger = BudgetLedger(recovery_budget=1000, reserve_ratio=0.3)

    ledger.record_spend(300)
    assert (ledger.spent, ledger.available, ledger.reserved) == (300, 490, 210)

    ledger.record_spend(400)
    assert (ledger.spent, ledger.available, ledger.reserved) == (700, 210, 90)

    ledger.record_spend(300)
    assert (ledger.spent, ledger.available, ledger.reserved) == (1000, 0, 0)


# -- StreamingAllocator: arrival-order, reserve-withholding ------------------


def test_ordinary_candidate_is_funded_from_the_available_pool_without_touching_reserve():
    ledger = BudgetLedger(recovery_budget=1000, reserve_ratio=0.5)
    allocator = StreamingAllocator(ledger, min_quality_score=0.6)

    decision = allocator.decide(_candidate(_CASE_A, point_estimate=0.5, uncertainty=0.1, incentive_amount=300))

    assert decision.funded is True
    assert ledger.spent == 300
    assert ledger.reserved == 350  # untouched -- still 50% of the new remaining (700)


def test_mediocre_candidate_declined_then_later_better_candidate_funded_from_reserve():
    # ADR-0003 / ticket 10's own required scenario: a mediocre case that would
    # need to eat into the reserve is declined; a later, higher-quality case
    # in the *same run* is allowed to draw against that preserved reserve.
    ledger = BudgetLedger(recovery_budget=1000, reserve_ratio=0.5)
    allocator = StreamingAllocator(ledger, min_quality_score=0.6)

    mediocre = _candidate(_CASE_A, point_estimate=0.4, uncertainty=0.2, incentive_amount=800)
    mediocre_decision = allocator.decide(mediocre)

    assert mediocre_decision.funded is False
    assert ledger.spent == 0  # nothing spent -- reserve preserved
    assert ledger.available == 500

    better = _candidate(_CASE_B, point_estimate=0.9, uncertainty=0.1, incentive_amount=800)
    better_decision = allocator.decide(better)

    assert better_decision.funded is True
    assert ledger.spent == 800


def test_candidate_exceeding_the_entire_remaining_budget_is_declined_regardless_of_quality():
    ledger = BudgetLedger(recovery_budget=1000, reserve_ratio=0.3)
    allocator = StreamingAllocator(ledger, min_quality_score=0.0)

    decision = allocator.decide(_candidate(_CASE_A, point_estimate=0.99, uncertainty=0.0, incentive_amount=1001))

    assert decision.funded is False
    assert ledger.spent == 0


def test_decide_only_ever_sees_the_one_candidate_passed_to_it():
    # No batch/list method exists at all -- decide() takes exactly one
    # candidate, so the allocator structurally cannot look ahead at cases
    # that haven't arrived yet (ticket 10's own acceptance criterion).
    import inspect

    signature = inspect.signature(StreamingAllocator.decide)
    assert list(signature.parameters) == ["self", "candidate"]
