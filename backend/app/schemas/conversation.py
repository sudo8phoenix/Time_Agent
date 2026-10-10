from datetime import date, time
from uuid import UUID
from pydantic import Field
from .common import StrictModel


class ConversationMessage(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(ge=0)
    report_date: date | None = None


class ConversationDecision(StrictModel):
    expected_revision: int = Field(ge=0)
    event_indexes: list[int] | None = None


class ConversationEdit(StrictModel):
    expected_revision: int = Field(ge=0)
    event_index: int = Field(ge=0)
    activity_id: UUID | None = None
    local_date: date | None = None
    local_time: time | None = None
    date_only: bool = False
    scope: str | None = Field(default=None, pattern="^(whole_activity|subactivity)$")
    subactivity_key: str | None = Field(default=None, min_length=1, max_length=200)


class ConversationTurnView(StrictModel):
    ordinal: int
    role: str
    text: str


class ConversationView(StrictModel):
    id: UUID
    project_id: UUID
    schedule_version_id: UUID
    revision: int
    status: str
    pending_question: str | None
    question: str | None
    events: list[dict]
    turns: list[ConversationTurnView]
    job_id: UUID | None
    proposal_ids: list[UUID]
