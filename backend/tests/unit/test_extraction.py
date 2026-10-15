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
    assert len(untrusted.observations) == 1
    assert untrusted.observations[0].work_date is None
    assert untrusted.observations[0].date_basis == DateBasis.unknown
    assert untrusted.observations[0].warnings
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


@pytest.mark.parametrize("inferred", ["0.5", "50"])
def test_source_percentage_does_not_become_unitless_quantity(inferred):
    text = "slab reinforcement in ground floor is 50% done . date is 19th oct 2026"
    item = observation(text, quantity=inferred, work_date="2026-10-19", quantity_kind="cumulative")
    item.update(unit=None, raw_unit=None, reported_percent=50)
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [item]})
    kept = result.observations[0]
    assert kept.reported_percent == 50
    assert kept.quantity is None and kept.quantity_kind.value == "none"
    assert kept.warnings


def test_percentage_repair_requires_exact_source_support():
    item = observation("invented 50%", quantity="0.5", quantity_kind="cumulative")
    item.update(unit=None, raw_unit=None, reported_percent=50)
    with pytest.raises(ExtractionError):
        extract_batch(batch(fragment("slab reinforcement ongoing")), lambda **_: {"observations": [item]})


def test_percentage_with_measured_quantity_keeps_both():
    text = "50% done, 500 kg installed in total"
    item = observation(text, quantity="500", quantity_kind="cumulative")
    item.update(unit="kg", raw_unit="kg", reported_percent=50)
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [item]})
    assert result.observations[0].quantity == 500
    assert result.observations[0].reported_percent == 50


def test_distinct_reported_percentages_are_not_deduplicated():
    text = "50% done. 60% done."
    items = []
    for percent in [50, 60]:
        item = observation(f"{percent}% done.", quantity=None, quantity_kind="none", summary="Slab progress")
        item.update(unit=None, raw_unit=None, reported_percent=percent)
        items.append(item)
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": items})
    assert [item.reported_percent for item in result.observations] == [50, 60]


def test_conflicting_current_day_anchors_remove_dated_effect_and_require_review():
    from app.progress.effects import build_effects
    text = "Source header 2026-09-21; body says today is 2026-09-23; 3 spools erected today."
    source = BatchInput("batch-1", (fragment(text),), date(2026, 9, 21), True)
    raw = observation(text, work_date="2026-09-23")
    result = extract_batch(source, lambda **_: {"observations": [raw]})
    kept = result.observations[0]
    assert kept.quantity == Decimal("3")
    assert kept.work_date is None and kept.date_basis == DateBasis.unknown
    assert any("Conflicting" in warning for warning in kept.warnings)
    assert "effective_date" not in build_effects(kept)


def test_explicit_historical_work_date_is_not_a_conflicting_current_day_anchor():
    text = "On 2026-09-20, erected 3 spools. Report date 2026-09-21."
    source = BatchInput("batch-1", (fragment(text),), date(2026, 9, 21), True)
    result = extract_batch(source, lambda **_: {"observations": [observation(text, work_date="2026-09-20")]})
    assert result.observations[0].work_date == date(2026, 9, 20)
    assert not result.observations[0].warnings


def test_report_context_date_must_equal_the_trusted_report_date():
    text = "Erected 3 spools today."
    source = BatchInput("batch-1", (fragment(text),), date(2026, 9, 21), True)
    result = extract_batch(source, lambda **_: {"observations": [observation(
        text, work_date="2026-09-23", date_basis="report_context")]})
    assert result.observations[0].work_date is None
    assert result.observations[0].warnings


def test_two_source_today_anchors_conflict_even_without_trusted_metadata():
    text = "Source header 2026-09-21; body says today is 2026-09-23; 3 spools erected."
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [
        observation(text, work_date="2026-09-23")]})
    assert result.observations[0].work_date is None and result.observations[0].warnings


def test_model_declared_conflicting_date_cannot_produce_a_dated_effect():
    text = "3 spools erected on the 21st or the 23rd; date unclear."
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [
        observation(text, work_date="2026-09-21", date_basis="conflicting")]})
    assert result.observations[0].work_date is None and result.observations[0].warnings


@pytest.mark.parametrize("word,kind,expected", [
    ("Tomorrow", "planned_work", date(2026, 9, 22)),
    ("today", "material_delivery", date(2026, 9, 21)),
    ("yesterday", "material_delivery", date(2026, 9, 20)),
])
def test_non_actual_relative_date_uses_validated_quote_and_trusted_context(word, kind, expected):
    from app.progress.effects import build_effects
    text = f"{word}: 3 spools {'planned for erection' if kind == 'planned_work' else 'delivered'}."
    item = observation(text, event_type=kind, work_date=None, date_basis="unknown")
    result = extract_batch(BatchInput("b", (fragment(text),), date(2026, 9, 21), True),
                           lambda **_: {"observations": [item]})
    kept = result.observations[0]
    assert kept.work_date == expected and kept.date_basis == DateBasis.relative_resolved
    assert any("work_date" in e.fields for e in kept.evidence)
    assert kept.quantity is None and kept.unit is None and build_effects(kept) == {}
    assert kept.actual_start is None and kept.actual_finish is None and not kept.lifecycle_effects


@pytest.mark.parametrize("text", [
    "Delivery today or tomorrow.", "Delivery not today.",
    "Delivery by tomorrow.", "Delivery after yesterday.",
    "Delivery before tomorrow.", "Delivery yesterday or next Monday.",
    "Delivery today, possibly.", "Delivery on 2026-09-20; today is just the filing date.",
])
def test_ambiguous_relative_date_remains_unknown(text):
    item = observation(text, event_type="material_delivery", work_date=None, date_basis="unknown")
    result = extract_batch(BatchInput("b", (fragment(text),), date(2026, 9, 21), True),
                           lambda **_: {"observations": [item]})
    assert result.observations[0].work_date is None


def test_non_actual_date_is_not_borrowed_from_unquoted_or_other_fragment_text():
    text = "Tomorrow erect 3 spools."
    item = observation("3 spools", event_type="planned_work", work_date=None, date_basis="unknown")
    source = BatchInput("b", (fragment(text), FragmentInput("f2", "p2", "Delivery today.")), date(2026, 9, 21), True)
    assert extract_batch(source, lambda **_: {"observations": [item]}).observations[0].work_date is None
    item["evidence"][0]["quote"] = text
    untrusted = BatchInput("b", (fragment(text),), date(2026, 9, 21), False)
    assert extract_batch(untrusted, lambda **_: {"observations": [item]}).observations[0].work_date is None


def test_declared_conflict_cannot_be_restored_from_a_relative_day_token():
    text = "Tomorrow erect 3 spools."
    item = observation(text, event_type="planned_work", work_date=None, date_basis="conflicting")
    result = extract_batch(BatchInput("b", (fragment(text),), date(2026, 9, 21), True),
                           lambda **_: {"observations": [item]})
    assert result.observations[0].work_date is None and result.observations[0].warnings


def test_missing_constraint_gets_a_blocking_warning_without_fabricating_a_blocker():
    text = "Installed 3 spools; welding stopped due to rain."
    item = observation(text)
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [item]})
    assert len(result.observations) == 1
    kept = result.observations[0]
    assert kept.event_type.value == "actual_progress" and kept.quantity == 3
    assert any("no separate blocker observation" in warning for warning in kept.warnings)


@pytest.mark.parametrize("text", [
    "Installed 3 spools; welding was not stopped due to rain.",
    "Installed 3 spools; welding could be stopped due to rain.",
    "Installed 3 spools; if welding stopped due to rain, reschedule it.",
])
def test_negated_or_conditional_constraint_does_not_trigger_omission_warning(text):
    item = observation(text)
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [item]})
    assert not result.observations[0].warnings


def test_a_separate_blocker_with_its_own_source_evidence_satisfies_presence_check():
    text = "Installed 3 spools; welding stopped due to rain."
    first = observation("Installed 3 spools")
    blocker = observation("welding stopped due to rain.", event_type="blocker", quantity=None,
                          quantity_kind="none", summary="Welding stopped due to rain.")
    blocker.update(work_type="welding", unit=None, blocker="Rain", observed_status="blocked")
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [first, blocker]})
    assert len(result.observations) == 2
    assert not any(o.warnings for o in result.observations)
    assert result.observations[1].quantity is None


def test_legacy_prompt_remains_exact_and_does_not_apply_new_normalization():
    from hashlib import sha256
    from app.prompts.extraction_v1 import LEGACY_PROMPT_VERSION, get_extraction_prompt
    version, system = get_extraction_prompt(LEGACY_PROMPT_VERSION)
    assert sha256(system.encode()).hexdigest() == "6fd7968e2c9a5b2a9c559b0e177e2c1bcf1dd08e186a65b8da22087bccb8ff98"
    text = "Tomorrow install 3 spools; welding stopped due to rain."
    item = observation(text, event_type="planned_work", work_date=None, date_basis="unknown")
    seen = []
    def model(**kwargs):
        seen.append(kwargs["system"])
        return {"observations": [item]}
    result = extract_batch(BatchInput("b", (fragment(text),), date(2026, 9, 21), True),
                           model, prompt_version=version)
    assert seen == [system] and result.metadata.prompt_version == version
    assert result.observations[0].work_date is None and not result.observations[0].warnings


def test_unknown_prompt_version_is_rejected_before_any_model_call():
    def model(**kwargs):
        raise AssertionError("unsupported prompt must fail before inference")
    with pytest.raises(ExtractionError, match="Unsupported extraction prompt"):
        extract_batch(batch(fragment()), model, prompt_version="unregistered")


@pytest.mark.parametrize("decorated", ["f1 | p1", "[f1 | p1]"])
def test_exact_header_decoration_is_repaired_with_reviewer_warning(decorated):
    item = observation("Installed 3 spools.")
    item["evidence"][0]["fragment_id"] = decorated
    result = extract_batch(batch(fragment("Installed 3 spools.")), lambda **_: {"observations": [item]})
    assert not result.errors
    assert result.observations[0].evidence[0].fragment_id == "f1"
    assert result.observations[0].evidence[0].quote == "Installed 3 spools."
    assert any("identifier restored" in w for w in result.observations[0].warnings)


@pytest.mark.parametrize("source_id,quote", [
    ("f1 | wrong", "Installed 3 spools."), ("other | p1", "Installed 3 spools."),
    ("f1 | p1", "Erected 3 spools."), ("f1 | p1", "spools"),
])
def test_decorated_evidence_repair_never_guesses_source_or_rewrites_quote(source_id, quote):
    item = observation(quote)
    item["evidence"][0]["fragment_id"] = source_id
    result = extract_batch(batch(fragment("Installed 3 spools. Remaining spools arrived.")),
                           lambda **_: {"observations": [item]})
    assert not result.observations and result.errors


def test_v10_prompt_and_processing_stay_frozen():
    from hashlib import sha256
    from app.prompts.extraction_v1 import V10_PROMPT_VERSION, get_extraction_prompt
    text = "Installed 3 spools."
    item = observation(text)
    item["evidence"][0]["fragment_id"] = "f1 | p1"
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [item]}, prompt_version=V10_PROMPT_VERSION)
    assert not result.observations and result.errors
    assert sha256(get_extraction_prompt(V10_PROMPT_VERSION)[1].encode()).hexdigest() == "49835ff04ad824c956189383a6e7ceac2bb6baab2af130bf2b7cecdb526a85a9"


@pytest.mark.parametrize("text", [
    "Crane unavailable, so reinforcement fixing was held; Installed 3 spools.",
    "Installed 3 spools; testing has been suspended.",
])
def test_reversed_cause_or_standalone_stoppage_requires_completeness_review(text):
    item = observation("Installed 3 spools")
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [item]})
    assert len(result.observations) == 1
    assert any("no separate blocker" in w for w in result.observations[0].warnings)


def test_partial_evidence_rejection_marks_retained_work_for_completeness_review():
    text = "Installed 3 spools; fixing held for inspection."
    valid = observation("Installed 3 spools")
    invalid = observation("Fixing stopped because inspection.", quantity=None, quantity_kind="none", event_type="blocker")
    result = extract_batch(batch(fragment(text)), lambda **_: {"observations": [valid, invalid]})
    assert len(result.observations) == 1 and result.errors
    assert any("completeness check" in w for w in result.observations[0].warnings)
