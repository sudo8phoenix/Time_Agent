from datetime import date
import json
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.review import ApprovalRequest, approve
from app.db.models import (
    Activity, ActivityState, Fragment, Job, Observation, Project, ProjectMembership,
    ProgressEvent, Proposal, Report, ScheduleVersion, User,
)
from app.db.session import engine
from app.agent.schedule_decision import candidate_for_activity
from app.llm.ollama import OllamaChatAdapter
from app.schemas.observation import Observation as Extracted
from backend.tests.graph_support import extraction_result, fixture_result, run_graph


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _job(db, *, with_fragment=True):
    project = Project(name=f"graph-{uuid4().hex}")
    db.add(project)
    db.flush()
    schedule = ScheduleVersion(project_id=project.id, version_number=1, content_sha256=uuid4().hex, state="active")
    db.add(schedule)
    db.flush()
    project.active_schedule_version_id = schedule.id
    activity = Activity(
        schedule_version_id=schedule.id, external_id="A-1", name="Install pipe", wbs="1",
        discipline="piping", work_type="pipe_spool_erection", area="A", is_leaf=True,
        measurement_basis="quantity_ratio", unit="spool",
    )
    report = Report(project_id=project.id, content_hash=uuid4().hex)
    db.add_all([activity, report])
    db.flush()
    fragment = None
    if with_fragment:
        fragment = Fragment(
            report_id=report.id, ordinal=1, locator="paragraph:1",
            original_text="Installed 2 spools in Area A", normalised_text="Installed 2 spools in Area A",
        )
        db.add(fragment)
        db.flush()
    job = Job(project_id=project.id, report_id=report.id, schedule_version_id=schedule.id)
    db.add(job)
    db.flush()
    return job, fragment, activity


def _obs(fragment):
    return Extracted.model_validate({
        "discipline": "piping", "work_type": "pipe_spool_erection", "event_type": "actual_progress",
        "observed_status": "completed", "area": "A", "asset_tags": [], "explicit_activity_id": None,
        "work_date": None, "date_basis": "unknown", "quantity": "2", "quantity_kind": "delta",
        "unit": "spool", "raw_unit": None, "reported_percent": None, "actual_start": None,
        "actual_finish": None, "blocker": None, "summary": "Installed 2 spools",
        "evidence": [{"fields": ["quantity"], "fragment_id": str(fragment.id), "quote": "Installed 2 spools"}],
        "warnings": [],
    })


def _extractor(observations=(), *, errors=()):
    return lambda _inputs, _model, **_kwargs: extraction_result(observations, errors=errors)


def _retrieve(activity):
    def retrieve(_observation, _version, activities):
        return [candidate_for_activity(next(row for row in activities if row.id == activity.id))]
    return retrieve


def _select(observation, candidates, _fragments, **_kwargs):
    if not candidates:
        return {
            "candidate_id": None, "mapping_state": "unmatched", "match_strength": "unresolved",
            "evidence_fragment_ids": [], "reason_codes": ["NO_CANDIDATES"],
            "explanation": "No candidates.", "missing_information": [], "candidates": [],
            "review_state": "pending", "proposed_effects": {},
        }
    return {
        "candidate_id": str(candidates[0].candidate_id), "mapping_state": "suggested",
        "match_strength": "review", "evidence_fragment_ids": [str(item.fragment_id) for item in observation.evidence],
        "reason_codes": [], "explanation": "Matched to the supplied schedule row.",
        "missing_information": [], "candidates": [item.model_dump(mode="json") for item in candidates],
        "review_state": "pending", "proposed_effects": {},
    }


def test_graph_no_fragments_is_safe_terminal(db):
    job, _, _ = _job(db, with_fragment=False)
    result = run_graph(db, job, model_callable=lambda **_: pytest.fail("empty input must not call a model"))
    assert result["state"] == "ready_for_review"
    assert result["extracted_count"] == result["proposal_count"] == 0


def test_graph_all_rejected_extractions_are_visible_failure(db):
    job, _, _ = _job(db)
    result = run_graph(
        db, job, model_callable=lambda **_: fixture_result({}),
        extraction_service=_extractor(errors=("invalid evidence",)),
        retrieval_service=lambda *_: [], selection_service=_select,
    )
    assert result["state"] == "failed"
    assert result["error_code"] in {"AGENT_TOOL_FAILED", "AGENT_REPAIR_LIMIT"}
    assert db.query(Observation).filter(Observation.job_id == job.id).count() == 0
    assert db.query(Proposal).join(Observation).filter(Observation.job_id == job.id).count() == 0


def test_graph_persists_traceable_proposal_and_is_idempotent(db):
    job, fragment, activity = _job(db)
    extract_calls = []

    def extract(inputs, model, **kwargs):
        extract_calls.append(1)
        return extraction_result([_obs(fragment)])

    result = run_graph(
        db, job, model_callable=lambda **_: fixture_result({}), extraction_service=extract,
        retrieval_service=_retrieve(activity), selection_service=_select,
    )
    assert result["extracted_count"] == result["proposal_count"] == 1, result
    row = db.query(Observation).filter(Observation.job_id == job.id).one()
    proposal = db.query(Proposal).filter(Proposal.observation_id == row.id).one()
    assert row.field_evidence["provenance"]["original_fields"] == row.fields
    assert row.field_evidence["provenance"]["original_selection"]["candidate_id"] == str(activity.id)
    assert row.fragment_id == fragment.id and proposal.chosen_activity_id == activity.id
    assert db.query(ProgressEvent).filter(ProgressEvent.observation_id == row.id).count() == 0
    assert db.query(ActivityState).filter(ActivityState.activity_id == activity.id).count() == 0
    again = run_graph(db, job, model_callable=lambda **_: pytest.fail("ready run must not repeat model calls"))
    assert again["extracted_count"] == again["proposal_count"] == 1
    assert db.query(Observation).filter(Observation.job_id == job.id).count() == 1
    assert len(extract_calls) == 1


def test_graph_failure_leaves_no_partial_rows(db):
    job, fragment, activity = _job(db)
    result = run_graph(
        db, job, model_callable=lambda **_: fixture_result({}), extraction_service=_extractor([_obs(fragment)]),
        retrieval_service=_retrieve(activity),
        selection_service=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("selection failed")),
    )
    assert result["state"] == "failed"
    assert db.query(Observation).filter(Observation.job_id == job.id).count() == 0
    assert db.query(Proposal).join(Observation).filter(Observation.job_id == job.id).count() == 0


def test_typed_extraction_through_ollama_selection_produces_approvable_effects(db):
    job, fragment, activity = _job(db)
    activity.planned_quantity = 10
    activity.baseline_quantity = 0
    activity.baseline_date = date(2026, 1, 1)
    fragment.original_text = fragment.normalised_text = "On 2026-01-02, installed 2 spools in Area A."
    raw = _obs(fragment).model_dump(mode="json")
    raw.update(work_date="2026-01-02", date_basis="explicit")
    raw["evidence"][0]["quote"] = fragment.original_text
    calls = []

    def transport(method, url, payload, timeout, headers):
        content = payload["messages"][1]["content"]
        assert isinstance(content, str)
        if "observations" in payload["format"].get("properties", {}):
            calls.append("extract")
            assert fragment.original_text in content
            result = {"observations": [raw]}
        elif "candidate_ids" in payload["format"].get("properties", {}):
            calls.append("schedule")
            context = json.loads(content)
            assert context["observation"]["work_type"] == "pipe_spool_erection"
            assert context["schedule_activities"][0]["id"] == str(activity.id)
            result = {"candidate_ids": [str(activity.id)]}
        else:
            calls.append("select")
            context = json.loads(content)
            assert context["observation"]["work_type"] == "pipe_spool_erection"
            assert context["candidates"][0]["candidate_id"] == str(activity.id)
            result = {"candidate_id": str(activity.id), "mapping_state": "suggested",
                      "evidence_fragment_ids": [str(fragment.id)], "reason_codes": [],
                      "explanation": "Supported by the source.", "missing_information": []}
        return 200, {"message": {"content": json.dumps(result)}}

    adapter = OllamaChatAdapter("http://127.0.0.1:11434", "fixture", transport=transport)
    result = run_graph(db, job, model_callable=adapter.chat)
    proposal = db.query(Proposal).join(Observation).filter(Observation.job_id == job.id).one()
    assert result["state"] == "ready_for_review"
    assert calls == ["extract", "schedule", "select"]
    assert proposal.chosen_activity_id == activity.id
    assert proposal.proposed_effects == {
        "event_type": "actual_progress", "quantity_semantics": "delta", "quantity": "2",
        "unit": "spool", "effective_date": "2026-01-02",
    }
    reviewer = User(username=f"flow-{uuid4().hex}", password_hash="unused", role="reviewer")
    db.add(reviewer)
    db.flush()
    db.add(ProjectMembership(project_id=job.project_id, user_id=reviewer.id))
    db.flush()
    approve(proposal.id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
        idempotency_key=str(uuid4())), reviewer, db)
    assert db.get(ActivityState, activity.id).completed_quantity == 2
    assert proposal.review_state == "approved"


def test_graph_heartbeats_remain_available_during_model_calls(db):
    job, _, _ = _job(db)
    heartbeat_calls = 0
    model_calls = 0
    model_metadata_flushed = False

    def observe_flush(session, _context):
        nonlocal model_metadata_flushed
        if session is db and any(
            inspect(job).attrs[name].history.has_changes()
            for name in ("model_version", "prompt_version", "config_version")
        ):
            model_metadata_flushed = True

    event.listen(db, "after_flush", observe_flush)

    def heartbeat_callback(_job, _token):
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        assert not model_metadata_flushed
        return True

    def model_call(**_kwargs):
        nonlocal model_calls
        model_calls += 1
        assert heartbeat_callback(job, job.lease_token)
        return fixture_result({"observations": []})

    try:
        result = run_graph(db, job, model_callable=model_call, heartbeat_callback=heartbeat_callback)
    finally:
        event.remove(db, "after_flush", observe_flush)
    assert result["state"] == "ready_for_review"
    assert model_calls == 1
    assert heartbeat_calls > model_calls
