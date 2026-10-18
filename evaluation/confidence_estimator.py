"""Experimental review-priority support indices, not correctness probabilities.

The feature definitions are fixed before fresh validation. This module receives
no expected labels and installs no runtime threshold or automatic approval.
"""
import re

VERSION = "evidence-support-index-v1"


def _canonical(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def estimate(observation, *, source, selected_activity=None, candidate_ids=(), activities=()):
    evidence = observation.get("evidence", [])
    exact = bool(evidence) and all(isinstance(e.get("quote"), str) and
        bool(e["quote"]) and e["quote"] in source for e in evidence)
    fields = {field for e in evidence for field in e.get("fields", [])}
    asserted = {"event_type", "work_type"}
    asserted.update(field for field in ("area", "work_date", "quantity")
                    if observation.get(field) is not None)
    coverage = len(asserted & fields) / len(asserted)
    features = {"exact_source_quotes": float(exact),
        "declared_field_coverage": coverage,
        "no_extraction_warnings": float(not observation.get("warnings")),
        "atomic_summary": float(bool(observation.get("summary")) and
            not (observation.get("event_type") == "actual_progress" and observation.get("blocker")))}
    extraction = sum(features.values()) / len(features)
    by_id = {row["activity_id"]: row for row in activities}
    selected = by_id.get(selected_activity)
    source_key = _canonical(source)
    identity = False
    if selected:
        tags = selected.get("asset_tags", "")
        tags = tags.split(";") if isinstance(tags, str) else tags
        identifiers = [selected.get("activity_id", ""), *tags]
        identity = any(len(_canonical(tag)) >= 3 and _canonical(tag) in source_key
                       for tag in identifiers if tag)
    link_features = {"selected_in_candidates": float(selected_activity in candidate_ids if selected_activity else False),
        "unique_candidate": float(len(candidate_ids) == 1),
        "source_identifier_support": float(identity),
        "exact_source_quotes": float(exact)}
    def result(score, values):
        return {"score": score, "method": "evidence_support_index", "version": VERSION,
            "validation_status": "experimental_not_probability", "features": values}
    return {"extraction": result(extraction, features),
            "linking": result(sum(link_features.values()) / len(link_features), link_features)}
