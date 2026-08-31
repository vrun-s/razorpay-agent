"""Ticket 18: the demo seed builds every beat test2108.md §13 needs on screen."""

import pytest

from app.demo_seed import seed_demo
from app.observability import budget_timeline, case_flags
from app.models import CaseHistoryEntryType, CaseStatus

pytestmark = pytest.mark.usefixtures("isolated_estimator")


def test_seed_produces_each_required_demo_beat(session):
    cases = seed_demo(session)
    flags = {c.id: case_flags(c) for c in cases}

    assert any(f.no_action_recovered for f in flags.values()), "a NO_ACTION case that still recovered"
    assert any(f.policy_rejected for f in flags.values()), "a policy rejection"
    assert any(f.human_overridden for f in flags.values()), "a human-overridden escalation"
    assert any(f.escalated for f in flags.values()), "at least one escalation"

    # A full happy-path timeline: something executed and recovered without escalation.
    assert any(
        c.status == CaseStatus.RECOVERED and not f.no_action_recovered and not f.escalated
        for c, f in ((c, flags[c.id]) for c in cases)
    )


def test_seed_gives_the_budget_trace_length(session):
    seed_demo(session)
    timeline = budget_timeline(session)
    assert len(timeline) >= 10
    assert [s.timestamp for s in timeline] == sorted(s.timestamp for s in timeline)


def test_seed_is_idempotent(session):
    first = seed_demo(session)
    first_budget_points = len(budget_timeline(session))
    second = seed_demo(session)

    assert len(first) == len(second)
    # Re-seeding wipes the prior run -- no orphaned history accumulates.
    assert len(budget_timeline(session)) == first_budget_points


def test_seed_demonstrates_a_declined_then_funded_incentive(session):
    """Ticket 19/ADR-0014, spec story 31: a mediocre case's real Incentive
    spend is genuinely declined by the Streaming Allocator (not skipped --
    the retry itself still executes, just for free), and a later, stronger
    case's is funded from the reserve."""
    cases = seed_demo(session)

    mediocre = next(c for c in cases if c.external_reference_id == "pay_demo_reserve_mediocre")
    better = next(c for c in cases if c.external_reference_id == "pay_demo_reserve_better")

    mediocre_allocation = next(
        e for e in mediocre.history if e.entry_type == CaseHistoryEntryType.ALLOCATION_CHECK
    )
    assert mediocre_allocation.data["funded"] is False
    mediocre_execution = next(e for e in mediocre.history if e.entry_type == CaseHistoryEntryType.EXECUTION)
    assert mediocre_execution.data["incentive_amount"] == 0

    better_allocation = next(e for e in better.history if e.entry_type == CaseHistoryEntryType.ALLOCATION_CHECK)
    assert better_allocation.data["funded"] is True
    better_execution = next(e for e in better.history if e.entry_type == CaseHistoryEntryType.EXECUTION)
    assert better_execution.data["incentive_amount"] > 0
