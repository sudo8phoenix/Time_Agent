"""Metamorphic runtime/scorer boundaries, not semantic model evaluations."""
from copy import deepcopy
from datetime import date
from itertools import permutations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingest.reports import _normalise, ingest_report
from app.db.models import FileRecord, Fragment, Project, Report
from app.llm.extract import (ExtractionError, FragmentInput, build_batches,
                            deduplicate_results, extract_batch)
from app.agent.schedule_decision import shortlist_activities
from evaluation.metrics import atomic_extraction, critical_fields
from test_extraction import observation
from test_retrieval_batch23 import activity
from backend.tests.unit.agent.test_agent_tools import Fixture


TEXT = "On 2026-09-21, erected 3 spools on line 24-XX in AREA-A."


def extract(text=TEXT, item=None, fragments=None):
    supplied = deepcopy(item if item is not None else observation(TEXT))
    batch = build_batches(fragments or [FragmentInput("f1", "p1", text)])[0]
    return extract_batch(batch, lambda **_: {"observations": [supplied]})



@pytest.mark.parametrize("summary", ["Three spools erected.", "Erection of three spools was reported."])
def test_rob01_paraphrased_summary_does_not_change_structured_scorer_identity(summary):
    event = {"event_type": "actual_progress", "quantity": "3", "unit": "spool"}
    gold = [{"case_id": "case", "atomic_events": [
        {"expected_event_type": "actual_progress", "expected_quantity": "3", "expected_unit": "spool"}]}]
    predicted = {**event, "summary": summary}
    assert atomic_extraction(gold, [{"case_id": "case", "atomic_events": [predicted]}])["f1"] == 1
    predicted["quantity"] = "30"
    assert atomic_extraction(gold, [{"case_id": "case", "atomic_events": [predicted]}])["f1"] == 0


@pytest.mark.parametrize("text", [" Installed  2 m. ", "\nInstalled\t2\nm.\n"])
def test_rob02_ingestion_whitespace_normalization_preserves_case_and_punctuation(text):
    assert _normalise(text) == "Installed 2 m."
    assert _normalise("INSTALLED 2 m!") == "INSTALLED 2 m!"
    assert _normalise("Installed 20 m.") != _normalise(text)


@pytest.mark.parametrize("order", list(permutations(["A-01", "A_01", "A-001"])))
def test_rob03_candidate_order_does_not_corrupt_identity_mapping(order):
    rows = [activity(identifier) for identifier in order]
    def adapter(**request):
        # Select by a request fact, never by first/last position.
        target = next(row for row in request["user"]["schedule_activities"] if row["external_id"] == "A_01")
        return {"candidate_ids": [target["id"]]}
    actual = shortlist_activities({}, "pinned", rows, model_call=adapter, short_ids=True)
    assert str(actual[0].candidate_id) == "A_01"


@pytest.mark.parametrize("field,new", [("quantity", "4"), ("unit", "m"),
                                        ("work_date", "2026-09-22")])
def test_rob04_one_critical_field_mutation_only_penalizes_that_field(field, new):
    base = {"quantity": "3", "unit": "spool", "work_date": "2026-09-21"}
    gold = [{"case_id": "case", **{f"expected_{key}": value for key, value in base.items()}}]
    changed = {**base, field: new}
    result = critical_fields(gold, [{"case_id": "case", **changed}])
    assert {key: result[key]["correct"] for key in base} == {key: int(key != field) for key in base}


def test_rob05_irrelevant_fragment_cannot_launder_evidence_attribution():
    wrong = observation(TEXT)
    wrong["evidence"][0]["fragment_id"] = "admin"
    fragments = [FragmentInput("f1", "p1", TEXT), FragmentInput("admin", "p2", "Meeting at noon.")]
    rejected = extract(item=wrong, fragments=fragments)
    assert not rejected.observations and rejected.errors
    accepted = extract(fragments=fragments)
    assert len(accepted.observations) == 1
    assert accepted.observations[0].evidence[0].fragment_id == "f1"


def test_rob06_actual_sqlite_ingestion_replay_does_not_duplicate_sources(monkeypatch):
    fixture = Fixture()
    stored = []
    monkeypatch.setattr("app.ingest.reports._store_original", lambda *args: stored.append(args))
    raw = TEXT.encode()
    with Session(fixture.engine) as db:
        project = db.get(Project, fixture.project_id)
        before = {model: db.scalar(select(func.count()).select_from(model)) for model in [Report, Fragment, FileRecord]}
        first, duplicate = ingest_report(db, project, raw, filename="daily.txt", report_date=date(2026, 9, 21),
                                         parsed_parts=[("p1", TEXT)])
        assert duplicate is False
        db.commit()
        again, duplicate = ingest_report(db, project, raw, filename="renamed.txt", report_date=date(2026, 9, 21),
                                         parsed_parts=[("p1", TEXT)])
        assert duplicate is True and again.id == first.id
        assert all(db.scalar(select(func.count()).select_from(model)) == count + 1 for model, count in before.items())
        assert len(stored) == 1
    result = extract()
    assert len(deduplicate_results([result, result, result])) == 1


@pytest.mark.parametrize("label", ["AREA-A", "Real refinery west rack", "ZONE-Delta-916"])
def test_rob07_consistent_project_label_rename_preserves_evidence_and_facts(label):
    text = TEXT.replace("AREA-A", label)
    item = observation(text)
    item["area"] = label
    result = extract(text, item)
    assert not result.errors
    actual = result.observations[0]
    assert actual.area == label and str(actual.quantity) == "3"
    assert actual.evidence[0].quote == text
    # An inconsistent rename must not pass quote validation.
    if label != "AREA-A":
        assert extract(text, observation(TEXT)).observations == ()


def test_rob08_repeated_postprocessing_has_zero_critical_disagreement_and_stable_hashes():
    results = [extract() for _ in range(5)]
    dumps = [result.observations[0].model_dump_json() for result in results]
    assert len(set(dumps)) == 1
    assert len({result.metadata.settings_hash for result in results}) == 1
    assert len({result.metadata.prompt_hash for result in results}) == 1
    changed = extract(TEXT + " Administrative note.")
    assert changed.metadata.prompt_hash != results[0].metadata.prompt_hash
    assert changed.metadata.settings_hash == results[0].metadata.settings_hash


def test_rob09_single_and_multi_fragment_preserve_valid_output_and_reject_cross_fragment_quote():
    single = extract()
    multi = extract(fragments=[FragmentInput("f1", "p1", TEXT), FragmentInput("f2", "p2", "No work on another line.")])
    assert single.observations == multi.observations
    wrong = observation(TEXT)
    wrong["evidence"][0]["fragment_id"] = "f2"
    failed = extract(item=wrong, fragments=[FragmentInput("f1", "p1", TEXT), FragmentInput("f2", "p2", "No work on another line.")])
    assert failed.observations == () and len(failed.errors) == 1


def test_rob10_context_pressure_preserves_all_fragments_and_malformed_output_is_failure():
    fragments = [FragmentInput(f"f{i}", str(i), TEXT) for i in range(19)]
    batches = build_batches(fragments, max_chars=len(TEXT) * 3)
    assert [fragment for batch in batches for fragment in batch.fragments] == fragments
    assert all(sum(len(f.text) for f in batch.fragments) <= len(TEXT) * 3 for batch in batches)
    with pytest.raises(ExtractionError, match="exceeds batch limit"):
        build_batches([FragmentInput("huge", "p1", TEXT)], max_chars=len(TEXT) - 1)
    with pytest.raises(ExtractionError, match="failed observation schema"):
        extract_batch(batches[0], lambda **_: {"observations": [{"quantity": "3"}]})


@pytest.mark.parametrize("field,new_value", [("aliases", "reviewed new cable alias"),
                                             ("name", "Revised cable package"),
                                             ("is_leaf", False)])
def test_ret13_checkpoint_reload_rejects_stale_schedule_candidate_after_db_edit(field, new_value):
    from app.agent.state import create_initial_state
    from app.agent.tools import AgentToolError
    from app.db.models import Activity
    from backend.tests.unit.agent.test_agent_tools import uid

    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    tools.extract_observations(scope.fragment_ids, tools.report_metadata)
    candidate = tools.retrieve_candidates("obs-0001", fixture.observation, scope.schedule_version_id).candidates[0]
    state = create_initial_state(
        run_id=str(uid()), job_id=scope.job_id, project_id=scope.project_id,
        report_id=scope.report_id, schedule_version_id=scope.schedule_version_id,
        fragment_ids=scope.fragment_ids, activity_ids=scope.activity_ids,
        observation_drafts=[fixture.observation], candidate_sets={"obs-0001": [candidate]},
        counters={"extraction_calls": 1, "node_executions": 1,
                  "selection_calls": 0, "corrective_retries": 0}, next_action="select",
    )
    # A fully populated old alias must become stale after a reviewed alias edit.
    if field == "aliases":
        with Session(fixture.engine) as db:
            db.get(Activity, fixture.activity_id).aliases = "old reviewed alias"
            db.commit()
        candidate.aliases = "old reviewed alias"
        state.candidate_sets["obs-0001"] = [candidate]
    fixture.tools().rehydrate_provenance(state)  # positive control before mutation
    with Session(fixture.engine) as db:
        setattr(db.get(Activity, fixture.activity_id), field, new_value)
        db.commit()
    with pytest.raises(AgentToolError, match="(?:candidate provenance|graph scope)"):
        fixture.tools().rehydrate_provenance(state)
    assert fixture.persist_calls == []
