"""Ticket 18: populate the database with a curated set of Recovery Cases that
makes every beat test2108.md §13 asks for visible in the dashboard:

- a full happy-path timeline (detected -> decision -> policy -> allocation ->
  execution -> recovered),
- a NO_ACTION case that still recovered (proof the money wasn't wasted),
- a policy rejection that names the constraint that bound it,
- an escalation with a human override written back to the audit trail,
- a standing escalation left in the queue for the demo to act on live,
- bulk cases so the Reserved Budget trace has length,
- ticket 19/ADR-0014's reserve-mechanism beat: a mediocre case's real
  Incentive spend visibly declined, then a stronger case's funded from the
  reserve (spec story 31) -- on a `recovery_budget` deliberately sized below
  what the two cases' incentives would cost together, and ordered
  mediocre-then-better. This sizing/ordering is demo-only tuning (ADR-0014):
  the evaluation harness never reads it.

Run it with `uv run python -m app.demo_seed` (wipes and reseeds). Everything
flows through the real app/lifecycle.py engine with the `FakeGateway` /
`FakeLLMClient` doubles -- no branch anywhere knows these cases are seeded,
only their Case History shape differs.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, delete

from app.allocator import BudgetLedger, StreamingAllocator
from app.db import create_db_and_tables, engine
from app.estimator import (
    CustomerSegmentProxy,
    EstimatorCellKey,
    get_estimator,
    reset_estimator,
)
from app.gateway import FakeGateway, Gateway
from app.lifecycle import log_entry, mark_recovered, override_case, run_decision_cycle
from app.merchant_config import DEFAULT_MERCHANT_CONFIG, MerchantConfig
from app.models import (
    CaseHistoryEntry,
    CaseHistoryEntryType,
    CaseStatus,
    EventSource,
    Intervention,
    ProcessedWebhookEvent,
    RecoveryCase,
    WorkflowType,
)
from app.policy import PolicyConfig

# A restrictive config used for exactly one seeded case, so its first
# proposal is rejected on a sequence-bound constraint (and the case is then
# force-stopped) -- the policy-rejection beat.
_RETRY_CEILING_ZERO = PolicyConfig(
    max_discount_pct=20.0,
    max_payment_retries=0,
    max_interventions_per_customer=5,
    recovery_budget=DEFAULT_MERCHANT_CONFIG.recovery_budget,
)

_ESCALATION_SIGNAL = "This is an absolute scam and I am furious — I want to speak to a lawyer."

# ADR-0014: walkthrough-only tuning, never read by the evaluation harness
# (app/evaluation.py keeps DEFAULT_MERCHANT_CONFIG). Sized so one 50_000
# case's 5% incentive (2_500) can't be funded from `available` alone (2/3 of
# the budget) but fits inside `remaining` -- forcing a genuine reserve-quality
# decision instead of an outright "budget exhausted" rejection.
_RESERVE_DEMO_MERCHANT_CONFIG = MerchantConfig(recovery_budget=3_600, incentive_pct=5.0)

# The Policy Engine's own recovery_budget must track the same figure (ADR-0014's
# "the two independently-configured copies... collapse behind the one
# MerchantConfig") -- otherwise this scenario's decline would come from
# validate()'s hard budget reject (a policy violation) instead of the
# Streaming Allocator's reserve-quality gate, misrepresenting which mechanism
# is actually being demonstrated. Same pattern as `_RETRY_CEILING_ZERO` above.
_RESERVE_DEMO_POLICY_CONFIG = PolicyConfig(
    max_discount_pct=20.0,
    max_payment_retries=3,
    max_interventions_per_customer=5,
    recovery_budget=_RESERVE_DEMO_MERCHANT_CONFIG.recovery_budget,
)


def _failed_payment(payment_id: str, *, decline: str = "insufficient funds in account") -> dict[str, Any]:
    return {
        "id": payment_id,
        "amount": 50_000,
        "currency": "INR",
        "order_id": f"order_{payment_id}",
        "email": "customer@example.com",
        "contact": "+911234567890",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": decline,
    }


def _create_case(session: Session, payment: dict[str, Any]) -> RecoveryCase:
    """The persistence half of app/intake.py's `create_case_from_failed_payment`,
    without its hardcoded call into `run_decision_cycle` -- the seed drives
    that step itself so it can pass an explicit shared allocator / policy /
    escalation signal per case."""
    case = RecoveryCase(
        workflow_type=WorkflowType.FAILED_PAYMENT,
        source=EventSource.SIMULATED,
        external_reference_id=payment["id"],
    )
    session.add(case)
    session.add(ProcessedWebhookEvent(event_id=f"evt_create_{payment['id']}", case_id=case.id))
    log_entry(
        session,
        case,
        CaseHistoryEntryType.CASE_CREATED,
        f"Recovery Case created from payment.failed for payment {payment['id']}",
        {"payment_id": payment["id"], "amount": payment["amount"], "currency": payment["currency"]},
    )
    session.commit()
    session.refresh(case)
    return case


def _wipe(session: Session) -> None:
    session.exec(delete(CaseHistoryEntry))
    session.exec(delete(ProcessedWebhookEvent))
    session.exec(delete(RecoveryCase))
    session.commit()


def seed_demo(session: Session, gateway: Gateway | None = None) -> list[RecoveryCase]:
    """Builds the curated case set. Returns every case created, newest last.
    Resets the estimator singleton first so the forced NO_ACTION posterior
    below is the only non-cold-start cell."""
    gateway = gateway or FakeGateway()
    reset_estimator()
    _wipe(session)

    allocator = StreamingAllocator(
        BudgetLedger(recovery_budget=DEFAULT_MERCHANT_CONFIG.recovery_budget, reserve_ratio=1 / 3)
    )
    cases: list[RecoveryCase] = []

    # 1. Happy path: retry proposed, funded, executed, then recovered.
    happy = _create_case(session, _failed_payment("pay_demo_happy"))
    run_decision_cycle(session, gateway, happy, payment=_failed_payment("pay_demo_happy"), allocator=allocator)
    mark_recovered(
        session, happy, event_id="evt_outcome_happy",
        reason="payment pay_demo_happy captured", trigger="payment.captured",
    )
    cases.append(happy)

    # 2. NO_ACTION that still recovered. A distinct decline text lands this in
    #    the `card_declined` cell so pumping it can't sway any other case.
    na_key = EstimatorCellKey(
        failure_reason="card_declined",
        customer_segment_proxy=CustomerSegmentProxy.NEW,
        intervention=Intervention.NO_ACTION,
    )
    for _ in range(25):
        get_estimator().update(na_key, source=EventSource.SIMULATED, success=True)
    na_payment = _failed_payment("pay_demo_noaction", decline="card declined by issuing bank")
    no_action = _create_case(session, na_payment)
    run_decision_cycle(session, gateway, no_action, payment=na_payment, allocator=allocator)
    mark_recovered(
        session, no_action, event_id="evt_outcome_noaction",
        reason="customer paid on their own — no nudge sent", trigger="payment.captured",
    )
    cases.append(no_action)

    # 3. Policy rejection: retry ceiling of 0 -> rejected naming
    #    max_payment_retries -> force-stopped.
    reject = _create_case(session, _failed_payment("pay_demo_policyreject"))
    run_decision_cycle(
        session, gateway, reject, payment=_failed_payment("pay_demo_policyreject"),
        policy=_RETRY_CEILING_ZERO, allocator=allocator,
    )
    cases.append(reject)

    # 4. Escalation + human override written back to the audit trail.
    override = _create_case(session, _failed_payment("pay_demo_override"))
    run_decision_cycle(
        session, gateway, override, payment=_failed_payment("pay_demo_override"),
        qualitative_signal=_ESCALATION_SIGNAL, allocator=allocator,
    )
    override_case(session, gateway, override, intervention=Intervention.PAYMENT_RETRY)
    cases.append(override)

    # 5. Standing escalation left in the queue.
    standing = _create_case(session, _failed_payment("pay_demo_escalated"))
    run_decision_cycle(
        session, gateway, standing, payment=_failed_payment("pay_demo_escalated"),
        qualitative_signal=_ESCALATION_SIGNAL, allocator=allocator,
    )
    cases.append(standing)

    # 6. Bulk cases so the Reserved Budget trace has length; alternate ones
    #    are left open, the rest recovered.
    for i in range(8):
        pid = f"pay_demo_bulk_{i}"
        bulk = _create_case(session, _failed_payment(pid))
        run_decision_cycle(session, gateway, bulk, payment=_failed_payment(pid), allocator=allocator)
        if i % 2 == 0:
            mark_recovered(
                session, bulk, event_id=f"evt_outcome_bulk_{i}",
                reason=f"payment {pid} captured", trigger="payment.captured",
            )
        cases.append(bulk)

    # 7. Reserve mechanism made visible with real Incentive money (spec
    #    story 31, ADR-0014): `_RESERVE_DEMO_MERCHANT_CONFIG` sizes
    #    recovery_budget below what these two cases' incentives would cost
    #    together, on its own allocator so the rest of the run's spend can't
    #    interfere. Ordered mediocre-then-better: the mediocre case's
    #    incentive is genuinely declined (it still executes, degraded to a
    #    free retry per ADR-0014 -- not skipped); the better case's is
    #    funded from the reserve.
    reserve_allocator = StreamingAllocator(
        BudgetLedger(recovery_budget=_RESERVE_DEMO_MERCHANT_CONFIG.recovery_budget, reserve_ratio=1 / 3)
    )
    # Warm the "better" case's cell well above the reserve-quality bar before
    # it's decided -- same trick as the NO_ACTION cell above, a distinct
    # decline text (`bank_server_error`) so pumping it can't sway any other
    # case's cell.
    better_key = EstimatorCellKey(
        failure_reason="bank_server_error",
        customer_segment_proxy=CustomerSegmentProxy.NEW,
        intervention=Intervention.PAYMENT_RETRY,
    )
    for _ in range(30):
        get_estimator().update(better_key, source=EventSource.SIMULATED, success=True)

    mediocre_payment = _failed_payment("pay_demo_reserve_mediocre", decline="invalid card details entered")
    mediocre = _create_case(session, mediocre_payment)
    run_decision_cycle(
        session, gateway, mediocre, payment=mediocre_payment,
        merchant_config=_RESERVE_DEMO_MERCHANT_CONFIG, policy=_RESERVE_DEMO_POLICY_CONFIG,
        allocator=reserve_allocator,
    )
    cases.append(mediocre)

    better_payment = _failed_payment("pay_demo_reserve_better", decline="bank server timeout")
    better = _create_case(session, better_payment)
    run_decision_cycle(
        session, gateway, better, payment=better_payment,
        merchant_config=_RESERVE_DEMO_MERCHANT_CONFIG, policy=_RESERVE_DEMO_POLICY_CONFIG,
        allocator=reserve_allocator,
    )
    mark_recovered(
        session, better, event_id="evt_outcome_reserve_better",
        reason="payment pay_demo_reserve_better captured", trigger="payment.captured",
    )
    cases.append(better)

    return cases


def _main() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        cases = seed_demo(session)
        by_status: dict[str, int] = {}
        for case in cases:
            by_status[case.status.value] = by_status.get(case.status.value, 0) + 1
        total = len(cases)
    print(f"seeded {total} cases: " + ", ".join(f"{n} {s}" for s, n in sorted(by_status.items())))


if __name__ == "__main__":
    _main()
