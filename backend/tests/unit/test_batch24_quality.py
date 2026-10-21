"""Controlled post-model boundaries; injected responses never measure LLM accuracy."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.llm.extract import BatchInput, FragmentInput, ExtractionError, extract_batch
from app.progress.effects import build_effects
from app.progress.ledger import ActivityBaseline, ProgressEvent, quantity_ratio, recompute_progress
from app.schemas.events import Endpoint
from evaluation.metrics import atomic_extraction
from evaluation.score_paired_pilot import fields_exact

ROOT = Path(__file__).resolve().parents[3]
CORPUS = json.loads((ROOT / "evaluation/fixtures/regression/quality-corpus.json").read_text())


def observation(text, **updates):
    value = dict(discipline="piping", work_type="pipe_spool_erection", event_type="actual_progress",
                 observed_status="in_progress", area="AREA-A", asset_tags=["P-001"],
                 explicit_activity_id=None, work_date="2026-10-21", date_basis="explicit",
                 quantity="2", quantity_kind="delta", unit="spool", raw_unit="spools",
                 reported_percent=None, actual_start=None, actual_finish=None, blocker=None,
                 summary=text, warnings=[], lifecycle_effects=[],
                 evidence=[dict(fields=["quantity"], fragment_id="f1", quote=text)])
    value.update(updates)
    return value


def extract(text, rows, *, report=None, trusted=False, fragments=None):
    batch = BatchInput("controlled", tuple(fragments or [FragmentInput("f1", "page:1", text)]),
                       date.fromisoformat(report) if report else None, trusted)
    return extract_batch(batch, lambda **_: {"observations": deepcopy(rows)})


@pytest.mark.parametrize("case", CORPUS["atomic"], ids=lambda c: c["mode"])
def test_qual01_atomic_scorer_counts_all_omissions_inventions_duplicates_and_merges(case):
    gold = [dict(event_type="actual_progress", scope="AREA-A", quantity="2"),
            dict(event_type="actual_progress", scope="AREA-B", quantity="3")]
    predictions = deepcopy(gold)
    if case["mode"] == "omission":
        predictions.pop()
    elif case["mode"] == "invention":
        predictions.append(dict(event_type="actual_progress", scope="AREA-C", quantity="4"))
    elif case["mode"] == "duplicate":
        predictions.append(deepcopy(gold[0]))
    elif case["mode"] == "merge":
        predictions = [dict(event_type="actual_progress", scope="AREA-A+AREA-B", quantity="5")]
    result = atomic_extraction([dict(case_id="controlled", atomic_events=[
        {f"expected_{key}": value for key, value in row.items()} for row in gold])],
        [dict(case_id="controlled", atomic_events=predictions)])
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (case["tp"], case["fp"], case["fn"])
    assert result["status"] == "scored"


@pytest.mark.parametrize("case", CORPUS["non_progress"], ids=lambda c: c["event"])
def test_qual02_non_progress_never_builds_installed_effect_or_ledger_increment(case):
    row = observation(case["source"], event_type=case["event"], quantity="8")
    kept = extract(case["source"], [row]).observations[0]
    assert kept.quantity is None and kept.unit is None and kept.quantity_kind.value == "none"
    assert build_effects(kept) == {}
    result = recompute_progress(ActivityBaseline(100, "spool", 0), [
        ProgressEvent("bad", date(2026, 10, 21), 8, "spool", "delta", case["event"])])
    assert result.completed_quantity == 0 and result.applied_event_ids == []


@pytest.mark.parametrize("case", CORPUS["states"], ids=lambda c: c["source"])
def test_qual03_typed_states_survive_validation_without_synthetic_affirmative_effects(case):
    numeric = case["event"] == "actual_progress"
    row = observation(case["source"], event_type=case["event"], observed_status=case["status"],
                      quantity="2" if numeric else None, quantity_kind="delta" if numeric else "none")
    kept = extract(case["source"], [row]).observations[0]
    assert kept.event_type.value == case["event"] and kept.observed_status.value == case["status"]
    effect = build_effects(kept)
    if numeric:
        assert effect["quantity"] == "2"
    elif case["event"] == "blocker":
        assert effect["event_type"] == "blocker" and "quantity" not in effect
    else:
        assert effect == {}


@pytest.mark.parametrize("case", CORPUS["numbers"], ids=lambda c: c["value"])
def test_qual04_numeric_values_are_exact_or_rejected_without_guessing(case):
    text = f"Erected {case['value']} spools."
    row = observation(text, quantity=case["value"])
    if case["accepted"]:
        kept = extract(text, [row]).observations[0]
        assert kept.quantity == Decimal(case["value"])
    else:
        with pytest.raises(ExtractionError, match="observation schema"):
            extract(text, [row])


@pytest.mark.parametrize("case", CORPUS["percentages"], ids=lambda c: c["value"])
def test_qual04_percent_boundaries_are_independent_of_measured_quantity(case):
    text = f"Progress reported as {case['value']} percent."
    row = observation(text, quantity=None, quantity_kind="none", unit=None, reported_percent=case["value"])
    if case["accepted"]:
        kept = extract(text, [row]).observations[0]
        assert kept.quantity is None and kept.reported_percent == Decimal(case["value"])
    else:
        with pytest.raises(ExtractionError):
            extract(text, [row])


@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("position", ["completed", "planned", "baseline", "event"])
def test_qual04_nonfinite_numbers_never_escape_into_progress_or_crash_recomputation(value, position):
    if position in {"completed", "planned"}:
        with pytest.raises(ValueError):
            quantity_ratio(value if position == "completed" else 2,
                           value if position == "planned" else 10)
    else:
        result = recompute_progress(ActivityBaseline(100, "spool", value if position == "baseline" else 0), [
            ProgressEvent("unsafe", date(2026, 10, 21), value if position == "event" else 2, "spool", "delta")])
        assert result.conflicts and result.physical_percent is None
        assert result.completed_quantity.is_finite()


def test_qual05_ledger_daily_cumulative_correction_remaining_and_plan_boundaries():
    baseline = ActivityBaseline(100, "spool", 0)
    def event(name, day, quantity, semantics="delta", **kwargs):
        return ProgressEvent(name, date(2026, 10, day), quantity, "spool", semantics, **kwargs)
    events = [event("daily", 21, 3), event("total", 22, 5, "cumulative"), event("next", 23, 2)]
    assert recompute_progress(baseline, events).completed_quantity == 7
    corrected = recompute_progress(baseline, [*events, event("fix", 23, 1, correction_of="next")])
    assert corrected.completed_quantity == 6 and "next" not in corrected.applied_event_ids
    for semantics in ["remaining", "planned", "unknown"]:
        result = recompute_progress(baseline, [event("unsupported", 21, 20, semantics)])
        assert result.completed_quantity == 0 and result.conflicts and result.physical_percent is None
    plan = recompute_progress(baseline, [*events, event("plan", 24, 30, event_type="planned_work")])
    assert plan.completed_quantity == 7


@pytest.mark.parametrize("case", CORPUS["units"], ids=lambda c: f"{c['from']}-{c['to']}")
def test_qual06_supported_conversions_dimensions_and_absent_units(case):
    if case["ratio"] is None:
        with pytest.raises(ValueError):
            quantity_ratio(case["quantity"], 10, completed_unit=case["from"], planned_unit=case["to"])
    else:
        assert quantity_ratio(case["quantity"], 10, completed_unit=case["from"], planned_unit=case["to"]) == Decimal(case["ratio"])


def test_qual06_absent_source_unit_is_not_invented_by_extraction():
    text = "Erected 3; the report gives no unit."
    with pytest.raises(ExtractionError):
        extract(text, [observation(text, unit=None, raw_unit=None)])
    kept = extract(text, [observation(text, quantity=None, quantity_kind="unknown", unit=None, raw_unit=None)]).observations[0]
    assert kept.unit is None and kept.raw_unit is None and "unit" not in build_effects(kept)


@pytest.mark.parametrize("case", CORPUS["dates"], ids=lambda c: f"{c['report']}-{c['word']}")
@pytest.mark.parametrize("trusted", [True, False])
def test_qual07_relative_days_cross_calendar_boundaries_only_with_trusted_dates(case, trusted):
    text = f"{case['word']}: 2 spools delivered."
    row = observation(text, event_type="material_delivery", work_date=None, date_basis="unknown")
    kept = extract(text, [row], report=case["report"], trusted=trusted).observations[0]
    assert kept.work_date == (date.fromisoformat(case["expected"]) if trusted else None)
    assert kept.date_basis.value == ("relative_resolved" if trusted else "unknown")
    assert build_effects(kept) == {}


@pytest.mark.parametrize("text", ["Delivery today or tomorrow.", "Delivery on 03/04/2026.", "Delivery not today."])
def test_qual07_ambiguous_dates_are_not_resolved(text):
    row = observation(text, event_type="material_delivery", work_date=None, date_basis="unknown")
    kept = extract(text, [row], report="2026-10-21", trusted=True).observations[0]
    assert kept.work_date is None


def test_qual07_midnight_precision_retains_local_date_and_rejects_zoned_clock():
    endpoint = dict(local_date="2026-10-21", local_time="00:00", precision="minute",
                    timezone="Asia/Kolkata", basis="explicit", raw_expression="21 October at midnight")
    parsed = Endpoint.model_validate(endpoint)
    assert parsed.local_date == date(2026, 10, 21) and parsed.local_time.hour == 0
    assert parsed.normalized_instant is None
    with pytest.raises(ValidationError):
        Endpoint.model_validate({**endpoint, "local_time": "00:00Z"})


@pytest.mark.parametrize("case", CORPUS["locations"], ids=lambda c: c["first"])
def test_qual08_source_clause_location_pairs_preserved_and_cross_assignment_fails_scoring(case):
    first, second = case["source"].split(". ")
    rows = [observation(first + ".", area=case["first"]),
            observation(second, event_type="material_delivery", area=case["second"], quantity="5")]
    result = extract(case["source"], rows)
    values = [row.model_dump(mode="json") for row in result.observations]
    assert [row["area"] for row in values] == [case["first"], case["second"]]
    assert fields_exact(values, values)
    crossed = deepcopy(values)
    crossed[0]["area"], crossed[1]["area"] = crossed[1]["area"], crossed[0]["area"]
    assert not fields_exact(values, crossed)


@pytest.mark.parametrize("identity", CORPUS["identities"])
def test_qual09_short_punctuated_and_zero_prefixed_ids_survive_and_do_not_score_as_other_ids(identity):
    text = f"Activity {identity}: erected 2 spools on tag {identity}."
    kept = extract(text, [observation(text, asset_tags=[identity], explicit_activity_id=identity)]).observations[0]
    assert kept.explicit_activity_id == identity and kept.asset_tags == [identity]
    value = kept.model_dump(mode="json")
    for other in CORPUS["identities"]:
        assert fields_exact([value], [{**value, "asset_tags": [other]}]) is (other == identity)


@pytest.mark.parametrize("case", CORPUS["evidence"], ids=lambda c: c["mode"])
def test_qual10_lexical_source_validation_and_explicit_wrong_event_attribution_scoring(case):
    first = "Erected 2 spools in AREA-A."
    second = "Delivered 5 spools to AREA-B."
    text = first + " " + second
    row = observation(first)
    fragments = [FragmentInput("f1", "page:1", text), FragmentInput("f2", "page:2", "Administrative header.")]
    if case["mode"] == "invented":
        row["evidence"][0]["quote"] = "Erected 99 spools."
    elif case["mode"] in {"wrong_fragment", "missing_fragment"}:
        row["evidence"][0]["fragment_id"] = "f2" if case["mode"] == "wrong_fragment" else "missing"
    elif case["mode"] == "repeated":
        fragments[0] = FragmentInput("f1", "page:1", first + " " + first)
    elif case["mode"] == "wrong_event":
        row["evidence"][0]["quote"] = second
    result = extract(text, [row], fragments=fragments)
    assert bool(result.observations) is case["accepted"]
    if not case["accepted"]:
        assert result.errors
    if case["mode"] == "wrong_event":
        # Lexical validation is intentionally not a semantic attribution claim.
        expected = observation(first)
        assert not fields_exact([expected], [row])
