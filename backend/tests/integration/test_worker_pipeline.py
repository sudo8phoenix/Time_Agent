from uuid import uuid4
from datetime import date
import json
import pytest
from sqlalchemy import event, inspect
from sqlalchemy.orm import sessionmaker
from app.db.session import engine
from app.db.models import Project, ScheduleVersion, Report, Job, Fragment, Activity, ActivityEmbedding, Observation, Proposal, ProgressEvent, ActivityState
from app.jobs.pipeline import process_job
from app.jobs.worker import run_once
from app.llm.ollama import LLMResult, OllamaChatAdapter
from app.schemas.observation import Observation as Extracted

@pytest.fixture
def db():
    connection = engine.connect(); transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    session = factory()
    try:
        yield session
    finally:
        session.close(); transaction.rollback(); connection.close()

def test_pipeline_no_fragments_is_safe_terminal(db):
    project = Project(name=f"pipeline-{uuid4().hex}")
    db.add(project); db.flush()
    version = ScheduleVersion(project_id=project.id, version_number=1, content_sha256=uuid4().hex)
    db.add(version); db.flush()
    report = Report(project_id=project.id, content_hash=uuid4().hex)
    db.add(report); db.flush()
    job = Job(project_id=project.id, report_id=report.id, schedule_version_id=version.id)
    db.add(job); db.flush()
    result = process_job(db, job)
    assert result["state"] == "ready_for_review"
    assert result["extracted_count"] == result["proposal_count"] == 0

def _job(db):
    project = Project(name=f"pipeline-{uuid4().hex}"); db.add(project); db.flush()
    version = ScheduleVersion(project_id=project.id, version_number=1, content_sha256=uuid4().hex); db.add(version); db.flush()
    activity = Activity(schedule_version_id=version.id, external_id="A-1", name="Install pipe", wbs="1", discipline="piping", work_type="pipe_spool_erection", area="A", is_leaf=True, measurement_basis="quantity_ratio", unit="spool"); db.add(activity)
    report = Report(project_id=project.id, content_hash=uuid4().hex); db.add(report); db.flush()
    fragment = Fragment(report_id=report.id, ordinal=1, locator="paragraph:1", original_text="Installed 2 spools in Area A", normalised_text="Installed 2 spools in Area A"); db.add(fragment); db.flush()
    job = Job(project_id=project.id, report_id=report.id, schedule_version_id=version.id); db.add(job); db.flush(); return job, fragment, activity

def _obs(fragment):
    return Extracted.model_validate({"discipline":"piping","work_type":"pipe_spool_erection","event_type":"actual_progress","observed_status":"completed","area":"A","asset_tags":[],"explicit_activity_id":None,"work_date":None,"date_basis":"unknown","quantity":"2","quantity_kind":"delta","unit":"spool","raw_unit":None,"reported_percent":None,"actual_start":None,"actual_finish":None,"blocker":None,"summary":"Installed 2 spools","evidence":[{"fields":["quantity"],"fragment_id":str(fragment.id),"quote":"Installed 2 spools"}],"warnings":[]})

def test_pipeline_persists_traceable_proposal_and_is_idempotent(db):
    job, fragment, activity = _job(db); calls=[]
    def extract(_): calls.append(1); return [_obs(fragment)]
    def select(obs, candidates, fragments): return {"candidate_id":str(activity.id),"mapping_state":"suggested","match_strength":"review","evidence_fragment_ids":[str(fragment.id)],"reason_codes":[],"explanation":"matched","missing_information":[],"candidates":[{"candidate_id":str(activity.id),"external_id":"A-1","activity_name":"Install pipe","area":"A","work_type":"pipe_spool_erection","is_leaf":True,"retrieval_rank":1,"retrieval_score":1.0}],"review_state":"pending","proposed_effects":{}}
    result=process_job(db,job,extraction_call=extract,selection_call=select,
                       retrieve_call=lambda *args: [activity]); db.commit()
    assert result["extracted_count"]==result["proposal_count"]==1
    row=db.query(Observation).filter(Observation.job_id == job.id).one()
    proposal=db.query(Proposal).filter(Proposal.observation_id == row.id).one()
    assert row.fragment_id==fragment.id; assert proposal.chosen_activity_id==activity.id
    assert db.query(ProgressEvent).filter(ProgressEvent.observation_id == row.id).count()==0
    assert db.query(ActivityState).filter(ActivityState.activity_id == activity.id).count()==0
    again=process_job(db,job,extraction_call=lambda *_: (_ for _ in ()).throw(AssertionError("called")))
    assert again["extracted_count"]==again["proposal_count"]==1
    assert db.query(Observation).filter(Observation.job_id == job.id).count()==1

def test_pipeline_failure_leaves_no_partial_rows(db):
    job, fragment, activity = _job(db)
    def extract(_): return [_obs(fragment)]
    def fail(*_): raise RuntimeError("selection failed")
    with pytest.raises(RuntimeError): process_job(db,job,extraction_call=extract,selection_call=fail,
                                                 retrieve_call=lambda *args: [activity])
    db.rollback()
    assert db.query(Observation).filter(Observation.job_id == job.id).count()==0
    assert (
        db.query(Proposal)
        .join(Observation, Proposal.observation_id == Observation.id)
        .filter(Observation.job_id == job.id)
        .count()
        == 0
    )


def test_typed_extraction_through_ollama_selection_produces_approvable_effects(db):
    from app.api.endpoints.review import approve, ApprovalRequest
    from app.db.models import User, ProjectMembership

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
        assert isinstance(content, str), "Ollama requires text message content"
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
    process_job(db, job, model_call=adapter.chat)
    proposal = db.query(Proposal).join(Observation).filter(Observation.job_id == job.id).one()
    assert calls == ["extract", "schedule", "select"]
    assert proposal.chosen_activity_id == activity.id
    assert proposal.proposed_effects == {"event_type": "actual_progress", "quantity_semantics": "delta",
                                         "quantity": "2", "unit": "spool", "effective_date": "2026-01-02"}
    reviewer = User(username=f"flow-{uuid4().hex}", password_hash="unused", role="reviewer")
    db.add(reviewer); db.flush()
    db.add(ProjectMembership(project_id=job.project_id, user_id=reviewer.id)); db.flush()
    approve(proposal.id, ApprovalRequest(expected_proposal_revision=1, expected_activity_revision=0,
                                        idempotency_key=str(uuid4())), reviewer, db)
    assert db.get(ActivityState, activity.id).completed_quantity == 2
    assert proposal.review_state == "approved"


def test_pipeline_does_not_lock_job_row_before_model_calls(db):
    job, fragment, _ = _job(db)
    db.add(Fragment(
        report_id=fragment.report_id,
        ordinal=2,
        locator="paragraph:2",
        original_text="Installed 3 spools in Area A",
        normalised_text="Installed 3 spools in Area A",
    ))
    db.flush()
    job_metadata_flushed = False
    heartbeat_calls = 0

    def observe_flush(session, _context):
        nonlocal job_metadata_flushed
        state = inspect(job)
        if any(
            state.attrs[name].history.has_changes()
            for name in ("model_version", "prompt_version", "config_version")
        ):
            job_metadata_flushed = True

    event.listen(db, "after_flush", observe_flush)

    def heartbeat(_job, _token):
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        assert not job_metadata_flushed, "job row was locked before a model call"
        return True

    calls = 0

    def model_call(**_kwargs):
        nonlocal calls
        calls += 1
        return LLMResult(
            value={"observations": []},
            model="fixture-model",
            model_digest="fixture-digest",
            runtime="fixture-runtime",
            elapsed_ms=1,
            settings_hash="fixture-settings",
            prompt_hash="fixture-prompt",
        )

    try:
        result = process_job(
            db,
            job,
            model_call=model_call,
            heartbeat_callback=heartbeat,
            lease_token="fixture-lease",
            max_chars=40,
        )
    finally:
        event.remove(db, "after_flush", observe_flush)

    assert result["proposal_count"] == 0
    assert heartbeat_calls == calls == 2
    assert job.model_version == "fixture-model"
    assert job.prompt_version is not None
    assert job.config_version is not None
