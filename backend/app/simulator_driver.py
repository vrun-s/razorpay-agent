"""Drives ticket 02's generator through the real case lifecycle at volume
(ticket 14): each synthetic case flows through app/intake.py's case creation
and app/lifecycle.py's reassessment loop exactly like a real one would.

This module's only simulation-specific pieces are `SimulatorGateway`
(app/simulator_gateway.py) and resolving a NO_ACTION cycle's own outcome --
the Gateway seam is never called for NO_ACTION even for a real case, so
nothing else can resolve its spontaneous-recovery draw. Everything else
(`create_case_from_failed_payment`, `create_case_from_halted_subscription`,
`run_decision_cycle`, `mark_recovered`) is called exactly as a real webhook
handler would call it -- no branch anywhere in those modules knows this case
is simulated; only its `source` tag does (set by app/intake.py already, per
ticket 07's estimator exclusion rule).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlmodel import Session

from app.intake import create_case_from_failed_payment, create_case_from_halted_subscription
from app.lifecycle import mark_recovered, run_decision_cycle
from app.models import CaseHistoryEntry, CaseHistoryEntryType, CaseStatus, Intervention, RecoveryCase, WorkflowType
from app.simulator.generator import SimulatedCase
from app.simulator_gateway import SimulatorGateway

# Safety bound on reassessment cycles per case. NO_ACTION decisions never
# force-stop a case via the Policy Engine's sequence-bound constraints (those
# only count EXECUTION entries), so nothing else guarantees a simulated case
# ever reaches a terminal state -- this is what does.
_MAX_REASSESSMENT_CYCLES = 10


@dataclass(frozen=True)
class SimulationOutcome:
    case: RecoveryCase
    recovered: bool


def _failed_payment_payload(simulated: SimulatedCase) -> dict:
    return {
        "id": f"pay_sim_{simulated.case_index}",
        "amount": 50_000,
        "currency": "INR",
        "order_id": f"order_sim_{simulated.case_index}",
        "email": "customer@example.com",
        "contact": "+911234567890",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "insufficient funds in account",
    }


def _halted_subscription_payload(simulated: SimulatedCase) -> dict:
    return {"id": f"sub_sim_{simulated.case_index}", "plan_id": "plan_sim_default"}


def _resolve_cycle_outcome(gateway: SimulatorGateway, case: RecoveryCase, new_entries: list[CaseHistoryEntry]) -> bool | None:
    """What this reassessment cycle's outcome is, if resolvable yet.

    `None` means nothing executed this cycle (the Policy Engine or Streaming
    Allocator declined the proposal) -- the same "wait for the next
    reassessment" state a real case sits in when nothing has happened yet.

    A NO_ACTION decision only gets resolved if the case is still OPEN after
    this cycle: `PolicyConfig.max_interventions_per_customer` (app/policy.py)
    is checked against *any* proposed intervention, NO_ACTION included, so a
    NO_ACTION decision can itself be sequence-bound-rejected and force-stop
    the case in the same cycle it was proposed in -- resolving an outcome for
    a decision that never actually took effect would risk flipping an
    already-STOPPED case back to RECOVERED.
    """
    executed = any(entry.entry_type == CaseHistoryEntryType.EXECUTION for entry in new_entries)
    if executed:
        return gateway.last_outcome

    if case.status != CaseStatus.OPEN:
        return None

    decision = next((entry for entry in new_entries if entry.entry_type == CaseHistoryEntryType.DECISION), None)
    if decision is not None and decision.data["intervention"] == Intervention.NO_ACTION.value:
        return gateway.resolve(Intervention.NO_ACTION)

    return None


def run_simulated_case(
    session: Session, simulated: SimulatedCase, *, workflow_type: WorkflowType, rng: random.Random
) -> SimulationOutcome:
    """Drives one synthetic case from creation through however many
    reassessment cycles it takes to resolve (or the safety bound)."""
    gateway = SimulatorGateway(simulated.hidden, rng=rng)

    if workflow_type == WorkflowType.FAILED_PAYMENT:
        case = create_case_from_failed_payment(
            session, gateway, _failed_payment_payload(simulated), event_id=f"evt_sim_create_{simulated.case_index}"
        )
    else:
        case = create_case_from_halted_subscription(
            session, gateway, _halted_subscription_payload(simulated), event_id=f"evt_sim_create_{simulated.case_index}"
        )

    seen = 0
    cycle = 0
    while True:
        new_entries = case.history[seen:]
        seen = len(case.history)

        recovered = _resolve_cycle_outcome(gateway, case, new_entries)
        if recovered:
            case = mark_recovered(
                session,
                case,
                event_id=f"evt_sim_outcome_{simulated.case_index}_{cycle}",
                reason="synthetic outcome resolved recovered",
            )
            break

        if case.status != CaseStatus.OPEN or cycle >= _MAX_REASSESSMENT_CYCLES:
            break

        cycle += 1
        case = run_decision_cycle(session, gateway, case)

    return SimulationOutcome(case=case, recovered=case.status == CaseStatus.RECOVERED)


def run_simulated_population(
    session: Session, population: list[SimulatedCase], *, workflow_type: WorkflowType, rng: random.Random
) -> list[SimulationOutcome]:
    """Drives a whole population (ticket 02's `generate_population`) through
    the pipeline one case at a time, in order, sharing one `rng` across all
    of them -- same convention as `resolve_intervention`'s own caller-supplied
    rng: reproducible given a fixed seed, independent of population generation.
    """
    return [run_simulated_case(session, simulated, workflow_type=workflow_type, rng=rng) for simulated in population]
