from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import CaseHistoryEntryType, CaseStatus, EventSource, WorkflowType


class CaseHistoryEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    entry_type: CaseHistoryEntryType
    summary: str
    data: dict[str, Any]


class RecoveryCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_type: WorkflowType
    status: CaseStatus
    source: EventSource
    created_at: datetime
    history: list[CaseHistoryEntryRead]
