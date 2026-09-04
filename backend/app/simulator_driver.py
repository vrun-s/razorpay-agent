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
from dataclasses import dataclass, field

from sqlmodel import Session

from app.allocator import StreamingAllocator
from app.decision import resolve_last_decided_cell_key
from app.estimator import get_estimator
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

# The synthetic payment amount every simulated failed-payment case carries
# (paise). The frozen generator (ticket 02) has no case-value dimension --
# only persona/response-curve ground truth -- so every case shares one fixed
# face value; ticket 15's evaluation harness reuses this same constant so a
# case's gross_recovered is consistent across every arm that scores it.
DEFAULT_CASE_AMOUNT = 50_000


@dataclass(frozen=True)
class ResolvedDecision:
    """One reassessment cycle whose outcome was actually observed this cycle
    (an executed intervention, or a resolved NO_ACTION) -- paired
    (predicted, actual) data point for the estimator's calibration curve
    (ticket 15, app/evaluation.py). A cycle nothing happened in (declined by
    Policy Engine/Streaming Allocator) contributes no data point here."""

    point_estimate: float
    recovered: bool


@dataclass(frozen=True)
class SimulationOutcome:
    case: RecoveryCase
    recovered: bool
    resolved_decisions: list[ResolvedDecision] = field(default_factory=list)


def _failed_payment_payload(simulated: SimulatedCase) -> dict:
    return {
        "id": f"pay_sim_{simulated.case_index}",
        "amount": DEFAULT_CASE_AMOUNT,
        "currency": "INR",
        "order_id": f"order_sim_{simulated.case_index}",
        "email": "customer@example.com",
        "contact": "+911234567890",
        "error_code": "BAD_REQUEST_ERROR",
        "error_description": "insufficient funds in account",
    }


def _halted_subscription_payload(simulated: SimulatedCase) -> dict:
    return {"id": f"sub_sim_{simulated.case_index}", "plan_id": "plan_sim_default"}


@dataclass(frozen=True)
class _CycleOutcome:
    resolved: bool  # whether this cycle actually produced an observation
    recovered: bool  # meaningless when resolved is False
    point_estimate: float | None  # this cycle's DECISION entry's point_estimate, if any


def _resolve_cycle_outcome(gateway: SimulatorGateway, case: RecoveryCase, new_entries: list[CaseHistoryEntry]) -> _CycleOutcome:
    """What this reassessment cycle's outcome is, if resolvable yet.

    `resolved=False` means nothing executed this cycle (the Policy Engine or
    Streaming Allocator declined the proposal) -- the same "wait for the next
    reassessment" state a real case sits in when nothing has happened yet.

    A NO_ACTION decision only gets resolved if the case is still OPEN after
    this cycle: `PolicyConfig.max_interventions_per_customer` (app/policy.py)
    is checked against *any* proposed intervention, NO_ACTION included, so a
    NO_ACTION decision can itself be sequence-bound-rejected and force-stop
    the case in the same cycle it was proposed in -- resolving an outcome for
    a decision that never actually took effect would risk flipping an
    already-STOPPED case back to RECOVERED.
    """
    decision = next((entry for entry in new_entries if entry.entry_type == CaseHistoryEntryType.DECISION), None)
    point_estimate = decision.data.get("point_estimate") if decision is not None else None

    executed = any(entry.entry_type == CaseHistoryEntryType.EXECUTION for entry in new_entries)
    if executed:
        return _CycleOutcome(resolved=True, recovered=gateway.last_outcome, point_estimate=point_estimate)

    if case.status != CaseStatus.OPEN:
        return _CycleOutcome(resolved=False, recovered=False, point_estimate=point_estimate)

    if decision is not None and decision.data["intervention"] == Intervention.NO_ACTION.value:
        return _CycleOutcome(
            resolved=True, recovered=gateway.resolve(Intervention.NO_ACTION), point_estimate=point_estimate
        )

    return _CycleOutcome(resolved=False, recovered=False, point_estimate=point_estimate)


def run_simulated_case(
    session: Session,
    simulated: SimulatedCase,
    *,
    workflow_type: WorkflowType,
    rng: random.Random,
    allocator: StreamingAllocator | None = None,
) -> SimulationOutcome:
    """Drives one synthetic case from creation through however many
    reassessment cycles it takes to resolve (or the safety bound).

    `allocator` defaults to `run_decision_cycle`'s own default (the
    process-wide singleton, correct for a live/demo run); ticket 19's
    evaluation harness passes one fresh `StreamingAllocator` shared across a
    whole arm's case stream instead (app/evaluation.py's `run_ai_treatment_arm`).
    """
    gateway = SimulatorGateway(simulated.hidden, rng=rng)

    if workflow_type == WorkflowType.FAILED_PAYMENT:
        case = create_case_from_failed_payment(
            session,
            gateway,
            _failed_payment_payload(simulated),
            event_id=f"evt_sim_create_{simulated.case_index}",
            allocator=allocator,
        )
    else:
        case = create_case_from_halted_subscription(
            session,
            gateway,
            _halted_subscription_payload(simulated),
            event_id=f"evt_sim_create_{simulated.case_index}",
            allocator=allocator,
        )

    seen = 0
    cycle = 0
    resolved_decisions: list[ResolvedDecision] = []
    while True:
        new_entries = case.history[seen:]
        seen = len(case.history)

        outcome = _resolve_cycle_outcome(gateway, case, new_entries)
        if outcome.resolved and outcome.point_estimate is not None:
            resolved_decisions.append(ResolvedDecision(point_estimate=outcome.point_estimate, recovered=outcome.recovered))

        if outcome.resolved and outcome.recovered:
            case = mark_recovered(
                session,
                case,
                event_id=f"evt_sim_outcome_{simulated.case_index}_{cycle}",
                reason="synthetic outcome resolved recovered",
            )
            break

        if outcome.resolved and not outcome.recovered:
            # A resolved-but-unrecovered cycle -- a failed executed
            # intervention, or a NO_ACTION cycle with no spontaneous recovery
            # -- is a Bernoulli failure for that cycle's decision cell,
            # attributed the same way mark_recovered attributes a success
            # (app/lifecycle.py). Recorded once per failed cycle, not once
            # per case: a case with N failed retries then a recovery
            # contributes beta += N, alpha += 1 -- the most trials, so the
            # fastest posterior convergence. Without this the estimator only
            # ever saw successes and beta never left cold start (ADR-0006's
            # "beta += 1 on failure" was specified but had no live caller).
            cell_key = resolve_last_decided_cell_key(case)
            if cell_key is not None:
                get_estimator().update(cell_key, source=case.source, success=False)

        if case.status != CaseStatus.OPEN or cycle >= _MAX_REASSESSMENT_CYCLES:
            break

        cycle += 1
        case = run_decision_cycle(session, gateway, case, allocator=allocator)

    return SimulationOutcome(
        case=case, recovered=case.status == CaseStatus.RECOVERED, resolved_decisions=resolved_decisions
    )


def run_simulated_population(
    session: Session,
    population: list[SimulatedCase],
    *,
    workflow_type: WorkflowType,
    rng: random.Random,
    allocator: StreamingAllocator | None = None,
) -> list[SimulationOutcome]:
    """Drives a whole population (ticket 02's `generate_population`) through
    the pipeline one case at a time, in order, sharing one `rng` across all
    of them -- same convention as `resolve_intervention`'s own caller-supplied
    rng: reproducible given a fixed seed, independent of population generation.
    """
    return [
        run_simulated_case(session, simulated, workflow_type=workflow_type, rng=rng, allocator=allocator)
        for simulated in population
    ]
