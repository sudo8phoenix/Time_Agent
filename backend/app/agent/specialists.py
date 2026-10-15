"""Shared specialist boundaries for report and conversation intake.

Only source fragments reach extraction; only one observation and its bounded
candidate set reach selection. These interfaces grant no persistence authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..llm.extract import extract_fragments
from ..schemas.observation import Observation
from ..schemas.matching import Candidate, Proposal


@dataclass(frozen=True)
class ExtractionInput:
    fragments: tuple
    report_date: object = None
    report_date_trusted: bool = False
    prompt_version: str | None = None


def extract_source(request: ExtractionInput, model_call: Callable, *, service=None):
    options = {"report_date": request.report_date, "report_date_trusted": request.report_date_trusted}
    if request.prompt_version is not None:
        options["prompt_version"] = request.prompt_version
    return (service or extract_fragments)(list(request.fragments), model_call, **options)


@dataclass(frozen=True)
class SelectionInput:
    observation: Observation
    candidates: tuple[Candidate, ...]
    fragments: dict[str, str]

    def validate(self):
        if len(self.candidates) > 8 or len({str(c.candidate_id) for c in self.candidates}) != len(self.candidates):
            raise ValueError("selection candidate scope exceeds its contract")
        for evidence in self.observation.evidence:
            if evidence.fragment_id not in self.fragments or evidence.quote not in self.fragments[evidence.fragment_id]:
                raise ValueError("selection evidence is outside source scope")


def select_source(request: SelectionInput, *, service: Callable, model_call, **kwargs) -> Proposal:
    request.validate()
    value = service(request.observation, list(request.candidates), dict(request.fragments),
                    model_call=model_call, **kwargs)
    result = value if isinstance(value, Proposal) else Proposal.model_validate(value)
    ids = {str(candidate.candidate_id) for candidate in request.candidates}
    if result.candidate_id is not None and str(result.candidate_id) not in ids:
        raise ValueError("selection returned an out-of-scope candidate")
    if any(str(candidate.candidate_id) not in ids for candidate in result.candidates):
        raise ValueError("selection returned unsupported candidates")
    if any(ref not in request.fragments for ref in result.evidence_fragment_ids) or result.proposed_effects:
        raise ValueError("selection exceeded evidence or effect authority")
    return result
