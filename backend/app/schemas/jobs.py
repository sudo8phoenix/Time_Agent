from enum import Enum
from pydantic import Field
from .common import StrictModel

class JobState(str, Enum):
    queued="queued"; running="running"; ready_for_review="ready_for_review"
    needs_transcription="needs_transcription"; failed="failed"; stale="stale"

class JobStage(str, Enum):
    parse="parse"; extract="extract"; retrieve="retrieve"; select="select"; validate="validate"; persist="persist"

class JobStatus(StrictModel):
    job_id: str = Field(min_length=1, max_length=200)
    state: JobState
    stage: JobStage | None
    attempts: int = Field(ge=0, le=3)
    extracted_count: int = Field(ge=0)
    proposal_count: int = Field(ge=0)
    error_code: str | None = Field(max_length=100)
