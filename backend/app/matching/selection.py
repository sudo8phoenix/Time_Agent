"""W-11 candidate selection and safe abstention.

The model is an untrusted classifier. This module owns candidate/evidence
membership, contradiction checks, and the conservative strength label.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..prompts.selection_v1 import SYSTEM_PROMPT
from ..schemas.matching import Candidate, Proposal


class SelectionValidationError(ValueError):
    pass


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {_norm(value)} if _norm(value) else set()
    return {_norm(item) for item in value if _norm(item)}


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise SelectionValidationError("candidate must be a mapping or model object")


def selection_schema(candidate_ids: Sequence[str]) -> dict[str, Any]:
    """Build the JSON schema with the supplied IDs as the only allowed enum."""
    return {"type": "object", "additionalProperties": False, "required":
            ["candidate_id", "mapping_state", "evidence_fragment_ids", "reason_codes", "explanation", "missing_information"],
            "properties": {
                "candidate_id": {"anyOf": [{"type": "string", "enum": list(candidate_ids)}, {"type": "null"}]},
                "mapping_state": {"type": "string", "enum": ["suggested", "ambiguous", "unmatched"]},
                "evidence_fragment_ids": {"type": "array", "items": {"type": "string"}},
                "reason_codes": {"type": "array", "items": {"type": "string"}},
                "explanation": {"type": "string"}, "missing_information": {"type": "array", "items": {"type": "string"}},
            }}


def _contradiction(observation: Any, candidate: Any) -> list[str]:
    conflicts: list[str] = []
    area, c_area = _norm(_get(observation, "area")), _norm(_get(candidate, "area"))
    if area and c_area and area != c_area: conflicts.append("AREA_CONFLICT")
    work, c_work = _norm(_get(observation, "work_type")), _norm(_get(candidate, "work_type"))
    if work and c_work and work != c_work: conflicts.append("WORK_TYPE_CONFLICT")
    tags, c_tags = _set(_get(observation, "asset_tags")), _set(_get(candidate, "asset_tags"))
    if tags and c_tags and not tags.intersection(c_tags): conflicts.append("TAG_CONFLICT")
    if not bool(_get(candidate, "is_leaf", True)): conflicts.append("SUMMARY_ACTIVITY")
    return conflicts


def select_candidate(observation: Any, candidates: Sequence[Any], fragments: Mapping[str, Any] | Sequence[Any] | None = None,
                     *, model_call: Callable[..., Mapping[str, Any]] | None = None,
                     project_id: str | None = None) -> Proposal:
    """Select or abstain, returning a pending proposal with no side effects.

    ``model_call`` receives ``system``, ``user`` and the dynamic ``schema``.
    Empty retrieval bypasses it entirely.
    """
    supplied = list(candidates)
    ids = [str(_get(c, "candidate_id", _get(c, "id", ""))) for c in supplied]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise SelectionValidationError("candidate IDs must be present and unique")
    eligible = [
        c for c in supplied
        if not _contradiction(observation, c)
        and (project_id is None or _get(c, "project_id") in (None, project_id))
    ]
    if not eligible:
        raw = {"candidate_id": None, "mapping_state": "unmatched", "evidence_fragment_ids": [],
               "reason_codes": ["NO_SUPPORTED_CANDIDATE"], "explanation": "No eligible candidates were retrieved.",
               "missing_information": ["A schedule activity or supported identifier is required."]}
    elif model_call is None:
        raise SelectionValidationError("model_call is required when candidates are supplied")
    else:
        user = {"observation": _as_mapping(observation), "candidates": [_as_mapping(c) for c in eligible]}
        raw = dict(model_call(system=SYSTEM_PROMPT, user=user, schema=selection_schema([str(_get(c, "candidate_id", _get(c, "id", ""))) for c in eligible])))
    allowed = {str(_get(c, "candidate_id", _get(c, "id", ""))) for c in eligible}
    chosen = raw.get("candidate_id")
    if chosen is not None and str(chosen) not in allowed: raise SelectionValidationError("candidate_id is not an eligible supplied ID")
    if chosen is not None and _contradiction(observation, next(c for c in eligible if str(_get(c, "candidate_id", _get(c, "id", ""))) == str(chosen))):
        raise SelectionValidationError("selected candidate contradicts supported observation facts")
    evidence_ids = [str(x) for x in raw.get("evidence_fragment_ids", [])]
    if fragments is None: fragment_map = {}
    elif isinstance(fragments, Mapping): fragment_map = fragments
    else: fragment_map = {str(_get(f, "fragment_id")): f for f in fragments}
    for fid in evidence_ids:
        if fid not in fragment_map: raise SelectionValidationError("evidence_fragment_id is not supplied")
    state = str(raw.get("mapping_state", "unmatched"))
    if state in {"ambiguous", "unmatched"}: chosen = None
    if state == "ambiguous" and len(eligible) < 2: raise SelectionValidationError("ambiguous result requires two eligible candidates")
    if state == "unmatched" and not raw.get("missing_information"): raw["missing_information"] = ["A supported activity identifier, location, or work type is required."]
    if chosen is not None and not evidence_ids:
        raise SelectionValidationError("a selected candidate requires source evidence")
    strength = "review" if chosen is not None else "unresolved"
    proposal = {"candidate_id": chosen, "mapping_state": state, "match_strength": strength,
                "evidence_fragment_ids": evidence_ids, "reason_codes": raw.get("reason_codes", []),
                "explanation": raw.get("explanation", "No supported match."), "missing_information": raw.get("missing_information", []),
                "candidates": [c if isinstance(c, Candidate) else Candidate.model_validate({
                    key: _get(c, key) for key in ("candidate_id", "external_id", "activity_name", "area", "work_type",
                                                   "is_leaf", "retrieval_rank", "retrieval_score")
                }) for c in eligible],
                "review_state": "pending", "proposed_effects": {}}
    return Proposal.model_validate(proposal)
