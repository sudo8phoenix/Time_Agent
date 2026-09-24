from uuid import uuid4
import pytest
from sqlalchemy.orm import sessionmaker
from app.db.session import engine
from app.db.models import Project, ScheduleVersion, Report, Job, Fragment, Activity, ActivityEmbedding, Observation, Proposal, ProgressEvent, ActivityState
from app.jobs.pipeline import process_job
from app.jobs.worker import run_once
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
    result=process_job(db,job,extraction_call=extract,selection_call=select); db.commit()
    assert result["extracted_count"]==result["proposal_count"]==1
    row=db.query(Observation).filter(Observation.job_id == job.id).one()
    proposal=db.query(Proposal).filter(Proposal.observation_id == row.id).one()
    assert row.fragment_id==fragment.id; assert proposal.chosen_activity_id==activity.id
    assert db.query(ProgressEvent).filter(ProgressEvent.observation_id == row.id).count()==0
    assert db.query(ActivityState).filter(ActivityState.activity_id == activity.id).count()==0
    again=process_job(db,job,extraction_call=lambda *_: (_ for _ in ()).throw(AssertionError("called")))
    assert again["extracted_count"]==again["proposal_count"]==1
    assert db.query(Observation).filter(Observation.job_id == job.id).count()==1

def test_pipeline_persists_embeddings_without_leaking_embed_into_extraction(db):
    job, fragment, activity = _job(db)

    class Embedder:
        model_revision = "fixture-embedding-v1"

        def __call__(self, text):
            return [float(len(text)), 1.0]

    def extract(_):
        return [_obs(fragment)]

    def select(obs, candidates, fragments):
        return {
            "candidate_id": str(activity.id),
            "mapping_state": "suggested",
            "match_strength": "review",
            "evidence_fragment_ids": [str(fragment.id)],
            "reason_codes": [],
            "explanation": "matched",
            "missing_information": [],
            "candidates": [],
            "review_state": "pending",
            "proposed_effects": {},
        }

    result = process_job(
        db,
        job,
        extraction_call=extract,
        selection_call=select,
        embed=Embedder(),
    )
    db.flush()
    assert result["proposal_count"] == 1
    stored = db.query(ActivityEmbedding).filter(
        ActivityEmbedding.activity_id == activity.id,
        ActivityEmbedding.model_revision == "fixture-embedding-v1",
    ).one()
    assert stored.activity_id == activity.id
    assert stored.model_revision == "fixture-embedding-v1"

def test_pipeline_failure_leaves_no_partial_rows(db):
    job, fragment, _ = _job(db)
    def extract(_): return [_obs(fragment)]
    def fail(*_): raise RuntimeError("selection failed")
    with pytest.raises(RuntimeError): process_job(db,job,extraction_call=extract,selection_call=fail)
    db.rollback()
    assert db.query(Observation).filter(Observation.job_id == job.id).count()==0
    assert (
        db.query(Proposal)
        .join(Observation, Proposal.observation_id == Observation.id)
        .filter(Observation.job_id == job.id)
        .count()
        == 0
    )
