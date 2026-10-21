"""Audit explicit source-unit annotation coverage and controlled corpus diversity.

This does not infer events or verify semantic labels. Unit declarations and
alternatives require external review before any model-quality claim.
"""
from collections import Counter

from evaluation.development_contract import score_case
from evaluation.source_units import source_units

DIMENSIONS = ("discipline", "site", "wbs", "vocabulary", "format", "schedule_size")
STRESS_SLICES = {"ordinary", "correction", "negative", "duplicate", "unreadable",
                "wrong_project", "ambiguity", "malicious"}


def audit(corpus):
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("nonempty cases required")
    ids = set()
    dimensions = {name: Counter() for name in DIMENSIONS}
    slices = Counter()
    units_count = events_count = 0
    for case in cases:
        cid = case.get("case_id")
        if not isinstance(cid, str) or not cid.strip() or cid in ids:
            raise ValueError("unique nonempty case identity required")
        ids.add(cid)
        if case.get("review_status") != "ai_authored_unadjudicated":
            raise ValueError("fixture review status must be explicit")
        for name in DIMENSIONS:
            value = case.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"missing diversity dimension: {name}")
            dimensions[name][value] += 1
        tags = case.get("slices")
        if not isinstance(tags, list) or not tags or len(tags) != len(set(tags)) or set(tags) - STRESS_SLICES:
            raise ValueError("explicit known unique slices required")
        slices.update(tags)
        units = source_units(case["text"])
        annotations = case.get("units", [])
        if len(annotations) != len(units):
            raise ValueError("every source unit requires an annotation disposition")
        for source, annotation in zip(units, annotations):
            if any(annotation.get(key) != source[key] for key in ("unit_id", "start", "end", "focus")):
                raise ValueError("source-unit identity/order/span mismatch")
            units_count += 1
            if annotation.get("disposition") == "no_event":
                if annotation.get("events") != [] or not annotation.get("reason", "").strip():
                    raise ValueError("no-event unit needs empty inventory and explicit reason")
            elif annotation.get("disposition") == "events":
                events = annotation.get("events")
                if not isinstance(events, list) or not events:
                    raise ValueError("event unit requires nonempty atomic inventory")
                for event in events:
                    if not isinstance(event, dict) or not event.get("summary") or not event.get("evidence"):
                        raise ValueError("atomic event needs summary and evidence")
                    for evidence in event["evidence"]:
                        if evidence.get("fragment_id") != cid or not evidence.get("quote") or evidence["quote"] not in source["focus"]:
                            raise ValueError("event evidence must cite its own exact source unit")
                score_case({"alternatives": [{"id": "inventory", "events": events}]}, events, completed=True)
                events_count += len(events)
            else:
                raise ValueError("unknown annotation disposition")
        alternatives = case.get("alternatives")
        if alternatives is not None:
            score_case({"alternatives": alternatives}, [], completed=False)
            for alternative in alternatives:
                score_case({"alternatives": alternatives}, alternative["events"], completed=True)
    return dict(cases=len(cases), units=units_count, annotated_events=events_count,
                dimensions={name: dict(counts) for name, counts in dimensions.items()},
                slices=dict(slices), missing_stress_slices=sorted(STRESS_SLICES - set(slices)),
                semantic_labels_verified=False, release_accepted=False,
                prevalence_estimate=False)
