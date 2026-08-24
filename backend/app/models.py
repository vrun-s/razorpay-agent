from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowType(StrEnum):
    """Which workflow a Recovery Case belongs to (ADR-0002: pluggable workflow abstraction)."""

    FAILED_PAYMENT = "failed_payment"
    HALTED_SUBSCRIPTION = "halted_subscription"


class CaseStatus(StrEnum):
    """A Recovery Case's lifecycle state (ADR-0004: cases as persistent sequences)."""

    OPEN = "open"
    RECOVERED = "recovered"
    STOPPED = "stopped"
    ESCALATED = "escalated"


class EventSource(StrEnum):
    """Whether a case (or an entry within it) originated from a real or simulated event."""

    REAL = "real"
    SIMULATED = "simulated"


class Intervention(StrEnum):
    """The shared Intervention type (CONTEXT.md) — each workflow declares its own valid subset."""

    PAYMENT_RETRY = "payment_retry"
    RESUME_CHARGE = "resume_charge"
    NO_ACTION = "no_action"


class CaseHistoryEntryType(StrEnum):
    CASE_CREATED = "case_created"
    DECISION = "decision"
    POLICY_CHECK = "policy_check"
    EXECUTION = "execution"
    REASSESSMENT_TRIGGERED = "reassessment_triggered"
    CASE_RECOVERED = "case_recovered"
    CASE_STOPPED = "case_stopped"
    CASE_ESCALATED = "case_escalated"


class CaseHistoryEntry(SQLModel, table=True):
    """One ordered entry in a Recovery Case's Case History."""

    id: int | None = Field(default=None, primary_key=True)
    case_id: str = Field(foreign_key="recoverycase.id", index=True)
    created_at: datetime = Field(default_factory=_now, index=True)
    entry_type: CaseHistoryEntryType
    summary: str
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))

    case: "RecoveryCase" = Relationship(back_populates="history")


class RecoveryCase(SQLModel, table=True):
    """A persistent Recovery Case (CONTEXT.md), identified by its `recovery_id`."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    workflow_type: WorkflowType
    status: CaseStatus = Field(default=CaseStatus.OPEN)
    source: EventSource = Field(default=EventSource.SIMULATED)
    created_at: datetime = Field(default_factory=_now)

    # The Razorpay payment/subscription id this case is about -- lets an
    # outcome webhook (e.g. payment.captured) find its case (ticket 06).
    external_reference_id: str | None = Field(default=None, index=True)

    # When the case's current intervention is expected to produce an outcome
    # by (ADR-0005's Response Window); the scheduled sweep reassesses any
    # OPEN case past this with no outcome yet. None once resolved.
    response_window_expires_at: datetime | None = Field(default=None, index=True)

    history: list[CaseHistoryEntry] = Relationship(
        back_populates="case",
        sa_relationship_kwargs={"order_by": "CaseHistoryEntry.created_at", "cascade": "all, delete-orphan"},
    )


class ProcessedWebhookEvent(SQLModel, table=True):
    """Dedup record for `x-razorpay-event-id` (ticket 04) -- a repeated event id is a no-op."""

    event_id: str = Field(primary_key=True)
    case_id: str = Field(foreign_key="recoverycase.id", index=True)
    received_at: datetime = Field(default_factory=_now)
