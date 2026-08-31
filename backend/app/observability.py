"""Ticket 18: read-model projections that turn raw Case History into the
judge-facing views test2108.md §13 asks for -- a staged case timeline, the
Reserved Budget as a moving quantity over a run, and the three "strongest
idea" beats (a NO_ACTION case that still recovered, a policy rejection, a
human-overridden escalation) made explicitly identifiable.

Everything here is a pure projection over already-persisted
`CaseHistoryEntry` rows (the same audit trail every prior ticket writes) --
no new state, no writes. The dashboard's HTTP routes (app/routers/
observability.py) are thin wrappers over these functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from app.models import (
    CaseHistoryEntry,
    CaseHistoryEntryType,
    CaseStatus,
    Intervention,
    RecoveryCase,
)

# -- Budget timeline -------------------------------------------------------


@dataclass(frozen=True)
class BudgetSnapshot:
    """One `ALLOCATION_CHECK` entry's view of the Recovery Budget ledger at
    the moment the Streaming Allocator decided a case (app/allocator.py's
    `BudgetLedger`: `spent` / `available` / `reserved`, paise). Ordered
    oldest-first, these form the Reserved Budget's trace across a run.
    """

    timestamp: datetime
    case_id: str
    funded: bool
    reason: str
    spent: int
    available: int
    reserved: int


def budget_timeline(session: Session) -> list[BudgetSnapshot]:
    """Every allocation decision made so far, oldest-first -- the moving
    Reserved Budget quantity test2108.md §13 item 2 wants visible.

    Ticket 19/ADR-0014: a `PAYMENT_RETRY`/`RESUME_CHARGE` proposal on a
    non-zero-value case now carries a real `incentive_amount`, so `spent`
    genuinely moves and `reserved` genuinely shrinks as the run progresses --
    not a flat line. Only an ALLOCATION_CHECK entry the Streaming Allocator
    was actually consulted for appears here at all (app/lifecycle.py's
    `run_decision_cycle`): a proposal that structurally never carried an
    Incentive (`NO_ACTION`, or `RESUME_CHARGE` on a case_value=0
    `HALTED_SUBSCRIPTION` case) logs no entry, so this trace never shows a
    misleading stream of "declined" points for a spend that was never on the
    table.
    """
    entries = session.exec(
        select(CaseHistoryEntry)
        .where(CaseHistoryEntry.entry_type == CaseHistoryEntryType.ALLOCATION_CHECK)
        .order_by(CaseHistoryEntry.created_at, CaseHistoryEntry.id)
    ).all()
    return [
        BudgetSnapshot(
            timestamp=entry.created_at,
            case_id=entry.case_id,
            funded=bool(entry.data.get("funded", False)),
            reason=str(entry.data.get("reason", "")),
            spent=int(entry.data.get("spent", 0)),
            available=int(entry.data.get("available", 0)),
            reserved=int(entry.data.get("reserved", 0)),
        )
        for entry in entries
    ]


# -- Per-case flags (the three demo beats) -------------------------------------


@dataclass(frozen=True)
class CaseFlags:
    """Whether a case is an instance of each demo beat test2108.md §13 calls
    out. Derived from Case History alone, so the dashboard can badge a case
    in a picker without re-deriving the reasoning."""

    no_action_recovered: bool
    policy_rejected: bool
    human_overridden: bool
    escalated: bool


def _ordered(history: list[CaseHistoryEntry]) -> list[CaseHistoryEntry]:
    """Case History in a stable order. `CaseHistoryEntry.created_at` alone is
    ambiguous -- several entries are written in one transaction and can share
    a microsecond -- so the autoincrement `id` breaks ties by insertion
    order, the same `(created_at, id)` sort `budget_timeline`'s query uses."""
    return sorted(history, key=lambda entry: (entry.created_at, entry.id or 0))


def case_flags(case: RecoveryCase) -> CaseFlags:
    history = _ordered(case.history)
    entry_types = {entry.entry_type for entry in history}
    decisions = [entry for entry in history if entry.entry_type == CaseHistoryEntryType.DECISION]
    executed = CaseHistoryEntryType.EXECUTION in entry_types

    # A NO_ACTION case that still recovered: the last decision spent nothing
    # (NO_ACTION), nothing ever executed, and the case still resolved
    # recovered -- proof the money wasn't wasted (test2108.md §13 item 3).
    no_action_recovered = (
        case.status == CaseStatus.RECOVERED
        and not executed
        and bool(decisions)
        and decisions[-1].data.get("intervention") == Intervention.NO_ACTION.value
    )

    policy_rejected = any(
        entry.entry_type == CaseHistoryEntryType.POLICY_CHECK and entry.data.get("approved") is False
        for entry in history
    )

    human_overridden = any(
        entry.entry_type == CaseHistoryEntryType.DECISION and entry.data.get("source") == "human"
        for entry in history
    )

    return CaseFlags(
        no_action_recovered=no_action_recovered,
        policy_rejected=policy_rejected,
        human_overridden=human_overridden,
        escalated=CaseHistoryEntryType.CASE_ESCALATED in entry_types,
    )


# -- Staged case timeline ---------------------------------------------------


@dataclass(frozen=True)
class TimelineStage:
    """One step in a case's life, in the canonical order the ticket's first
    acceptance criterion lists: detected -> decision (+ reasoning) -> policy
    check (naming the constraint that bound it) -> allocation -> execution ->
    webhook -> reassessment -> stop. A 1:1 projection of a Case History entry,
    never a collapsed summary -- the view wants every step, each with its own
    timestamp."""

    stage: str
    label: str
    timestamp: datetime
    entry_type: str
    detail: dict


_STAGE_BY_ENTRY: dict[CaseHistoryEntryType, str] = {
    CaseHistoryEntryType.CASE_CREATED: "detected",
    CaseHistoryEntryType.DECISION: "decision",
    CaseHistoryEntryType.POLICY_CHECK: "policy_check",
    CaseHistoryEntryType.ALLOCATION_CHECK: "allocation",
    CaseHistoryEntryType.EXECUTION: "execution",
    CaseHistoryEntryType.REASSESSMENT_TRIGGERED: "reassessment",
    CaseHistoryEntryType.CASE_RECOVERED: "outcome",
    CaseHistoryEntryType.CASE_STOPPED: "outcome",
    CaseHistoryEntryType.CASE_ESCALATED: "outcome",
}


def _stage_of(entry: CaseHistoryEntry) -> str:
    """The pipeline stage an entry belongs to. A REASSESSMENT_TRIGGERED entry
    that an outcome webhook wrote (ADR-0005: a real outcome is a trigger in
    its own right) is the spec chain's distinct `webhook` beat; the
    scheduled-sweep one stays `reassessment`."""
    if (
        entry.entry_type == CaseHistoryEntryType.REASSESSMENT_TRIGGERED
        and entry.data.get("trigger") == "webhook"
    ):
        return "webhook"
    return _STAGE_BY_ENTRY.get(entry.entry_type, entry.entry_type.value)


def _label(entry: CaseHistoryEntry) -> str:
    data = entry.data
    intervention = data.get("intervention", "")
    if entry.entry_type == CaseHistoryEntryType.DECISION:
        who = "Human override" if data.get("source") == "human" else "Decision Engine"
        return f"{who} proposed {intervention}"
    if entry.entry_type == CaseHistoryEntryType.POLICY_CHECK:
        if data.get("approved") is False:
            constraint = data.get("violated_constraint") or "a merchant constraint"
            return f"Policy Engine rejected {intervention} — {constraint}"
        return f"Policy Engine approved {intervention}"
    if entry.entry_type == CaseHistoryEntryType.ALLOCATION_CHECK:
        verb = "funded" if data.get("funded") else "declined"
        return f"Streaming Allocator {verb} {intervention}"
    # case_created / execution / reassessment / outcome entries already carry
    # a human-readable summary written at the callsite.
    return entry.summary


def case_timeline(case: RecoveryCase) -> list[TimelineStage]:
    """The selected case's full staged timeline for the drill-down view."""
    return [
        TimelineStage(
            stage=_stage_of(entry),
            label=_label(entry),
            timestamp=entry.created_at,
            entry_type=entry.entry_type.value,
            detail=dict(entry.data),
        )
        for entry in _ordered(case.history)
    ]
