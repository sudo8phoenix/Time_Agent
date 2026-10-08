from datetime import date
from decimal import Decimal

import pytest

from app.llm.extract import (
    ExtractionError,
    FragmentInput,
    BatchInput,
    build_batches,
    deduplicate_results,
    extract_batch,
    extract_fragments,
)
from app.schemas.common import DateBasis


def fragment(text="On 2026-09-21, erected 3 spools on line 24-XX in AREA-A.", fragment_id="f1"):
    return FragmentInput(fragment_id, "p1", text)


def batch(value):
    return build_batches([value])[0]


def observation(quote, *, event_type="actual_progress", quantity="3", work_date="2026-09-21",
                date_basis="explicit", summary="Three spools erected.", quantity_kind="delta"):
    return {
        "discipline": "piping", "work_type": "pipe_spool_erection", "event_type": event_type,
        "observed_status": "in_progress", "area": "AREA-A", "asset_tags": ["24-XX"],
        "explicit_activity_id": None, "work_date": work_date, "date_basis": date_basis,
        "quantity": quantity, "quantity_kind": quantity_kind, "unit": "spool", "raw_unit": "spools",
        "reported_percent": None, "actual_start": None, "actual_finish": None, "blocker": None,
        "summary": summary, "evidence": [{"fields": ["quantity"], "fragment_id": "f1", "quote": quote}],
        "warnings": [],
    }


def test_batches_split_at_character_and_fragment_boundaries():
    fragments = [FragmentInput(f"f{i}", f"p{i}", "x" * 5) for i in range(9)]
    batches = build_batches(fragments, max_chars=12)
    assert [[f.fragment_id for f in b.fragments] for b in batches] == [
        ["f0", "f1"], ["f2", "f3"], ["f4", "f5"], ["f6", "f7"], ["f8"]
    ]
    with pytest.raises(ExtractionError, match="exceeds batch limit"):
        build_batches([FragmentInput("huge", "p", "x" * 11)], max_chars=10)


def test_atomic_response_keeps_multiple_scopes_and_deduplicates_overlap():
    text = "On 2026-09-21, erected 3 spools on line 24-XX in AREA-A. Welded 2 joints on line 25-YY."
    first = observation("On 2026-09-21, erected 3 spools on line 24-XX in AREA-A.")
    second = observation("Welded 2 joints on line 25-YY.", quantity="2", summary="Two joints welded.")
    second.update({"work_type": "welding", "unit": "joint", "raw_unit": "joints", "asset_tags": ["25-YY"]})

    def model(**_):
        return {"observations": [first, second]}

    result = extract_batch(batch(fragment(text)), model)
    assert len(result.observations) == 2
    duplicate = extract_batch(batch(fragment(text)), lambda **_: {"observations": [first]})
    assert len(deduplicate_results([result, duplicate])) == 2


def test_invalid_and_absent_evidence_are_rejected_per_observation():
    valid = observation("On 2026-09-21, erected 3 spools on line 24-XX in AREA-A.")
    invalid = observation("invented quote")
    result = extract_batch(batch(fragment()), lambda **_: {"observations": [valid, invalid]})
    assert len(result.observations) == 1
    assert any("not present" in error for error in result.errors)


def test_repeated_quote_requires_disambiguating_locator():
    repeated = fragment("AREA-A: welded 2 joints. AREA-A: welded 2 joints.")
    item = observation("AREA-A", summary="Area noted.", quantity=None, quantity_kind="none")
    item["evidence"][0]["fields"] = ["area"]
    result = extract_batch(batch(repeated), lambda **_: {"observations": [item]})
    assert result.observations == ()
    assert any("ambiguous" in error for error in result.errors)


def test_relative_date_requires_trusted_report_date():
    item = observation("On 2026-09-21, erected 3 spools on line 24-XX in AREA-A.",
                        work_date="2026-09-21", date_basis="relative_resolved")
    untrusted = extract_batch(batch(fragment()), lambda **_: {"observations": [item]})
    assert untrusted.observations == ()
    trusted_batch = BatchInput("batch-trusted", (fragment(),), date(2026, 9, 21), True)
    trusted = extract_batch(trusted_batch, lambda **_: {"observations": [item]})
    assert trusted.observations[0].date_basis == DateBasis.relative_resolved


def test_schema_rejection_is_visible():
    with pytest.raises(ExtractionError, match="failed observation schema"):
        extract_batch(batch(fragment()), lambda **_: {"observations": [{"unexpected": True}]})


def test_model_null_placeholders_are_normalised_for_optional_fields():
    item = observation("On 2026-09-21, erected 3 spools on line 24-XX in AREA-A.")
    item.update({
        "area": "unknown", "explicit_activity_id": "unknown", "work_date": "unknown",
        "reported_percent": "unknown", "actual_start": "unknown", "actual_finish": "unknown",
        "blocker": "unknown",
    })
    result = extract_batch(batch(fragment()), lambda **_: {"observations": [item]})
    kept = result.observations[0]
    assert kept.area is None
    assert kept.explicit_activity_id is None
    assert kept.work_date is None
    assert kept.reported_percent is None
    assert kept.actual_start is None
    assert kept.actual_finish is None
    assert kept.blocker is None


@pytest.mark.parametrize("event_type", ["planned_work", "no_work", "material_delivery"])
def test_non_progress_quantity_is_removed(event_type):
    item = observation("On 2026-09-21, erected 3 spools on line 24-XX in AREA-A.", event_type=event_type)
    result = extract_batch(batch(fragment()), lambda **_: {"observations": [item]})
    kept = result.observations[0]
    assert kept.quantity is None
    assert kept.quantity_kind.value == "none"
    assert kept.unit is None


def test_extract_fragments_preserves_batch_metadata_and_empty_fragments_are_skipped():
    calls = []

    def model(**kwargs):
        calls.append(kwargs["user"])
        return {"observations": []}

    results = extract_fragments([FragmentInput("empty", "p", " "), fragment()], model,
                                report_date=date(2026, 9, 21), report_date_trusted=True)
    assert len(results) == 1
    assert "Trusted report date: 2026-09-21" in calls[0]
