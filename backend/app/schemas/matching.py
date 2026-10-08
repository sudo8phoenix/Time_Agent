from uuid import UUID
from pydantic import Field, field_validator, model_validator
from .common import StrictModel, MappingState, MatchStrength, ReviewState, WorkType


class Candidate(StrictModel):
    candidate_id: UUID | str
    external_id: str = Field(min_length=1, max_length=200)
    activity_name: str = Field(min_length=1, max_length=500)
    area: str | None = Field(max_length=200)
    work_type: WorkType
    is_leaf: bool
    asset_tags: list[str] = Field(default_factory=list)
    wbs: str | None = None
    discipline: str | None = None
    aliases: str | None = None
    measurement_basis: str | None = None
    planned_quantity: str | None = None
    unit: str | None = None
    planned_start: str | None = None
    planned_finish: str | None = None
    retrieval_rank: int | None = Field(ge=1, le=1000)
    retrieval_score: float | None

    @field_validator("retrieval_score")
    @classmethod
    def finite_score(cls, value):
        if value is not None and not __import__("math").isfinite(value):
            raise ValueError("retrieval_score must be finite")
        return value


class Proposal(StrictModel):
    candidate_id: UUID | str | None
    mapping_state: MappingState
    match_strength: MatchStrength
    evidence_fragment_ids: list[str] = Field(max_length=30)
    reason_codes: list[str] = Field(max_length=30)
    explanation: str = Field(min_length=1, max_length=2000)
    missing_information: list[str] = Field(max_length=30)
    candidates: list[Candidate] = Field(max_length=8)
    review_state: ReviewState
    proposed_effects: dict[str, object]

    @model_validator(mode="after")
    def validate_membership(self):
        ids = {str(c.candidate_id) for c in self.candidates}
        if self.candidate_id is not None and str(self.candidate_id) not in ids:
            raise ValueError("candidate_id must be one of candidates or null")
        if self.mapping_state in (MappingState.ambiguous, MappingState.unmatched) and self.candidate_id is not None:
            raise ValueError("ambiguous and unmatched proposals require candidate_id=null")
        if self.mapping_state is MappingState.ambiguous and len(self.candidates) < 2:
            raise ValueError("ambiguous proposal requires at least two candidates")
        if any(not c.is_leaf for c in self.candidates):
            raise ValueError("summary activities cannot be candidates")
        return self


def proposal_model(candidate_ids: list[str | UUID]):
    """Return a strict proposal model whose candidate_id is dynamically constrained."""
    allowed = {str(x) for x in candidate_ids}
    class DynamicProposal(Proposal):
        @model_validator(mode="after")
        def validate_dynamic(self):
            if self.candidate_id is not None and str(self.candidate_id) not in allowed:
                raise ValueError("candidate_id is not in supplied candidate IDs")
            return self
    DynamicProposal.__name__ = "ProposalForCandidates"
    return DynamicProposal


class ReviewRequest(StrictModel):
    expected_proposal_revision: int = Field(ge=1)
    chosen_candidate_id: UUID | str | None
    field_changes: dict[str, object]
    reason: str = Field(min_length=1, max_length=2000)
    evidence_fragment_ids: list[str] = Field(max_length=30)


class ApprovalRequest(StrictModel):
    expected_proposal_revision: int = Field(ge=1)
    expected_activity_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)
    resolution_notes: str | None = Field(max_length=2000)
