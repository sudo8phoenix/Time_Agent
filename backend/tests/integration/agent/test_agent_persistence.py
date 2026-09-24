from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    AgentRun,
    AgentStep,
    AgentToolCall,
    Job,
    Project,
    Report,
    ScheduleVersion,
)
from app.db.session import engine


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _job(db) -> Job:
    project = Project(name=f"agent-persistence-{uuid4().hex}")
    db.add(project)
    db.flush()
    version = ScheduleVersion(
        project_id=project.id,
        version_number=1,
        content_sha256=uuid4().hex,
    )
    db.add(version)
    db.flush()
    project.active_schedule_version_id = version.id
    report = Report(project_id=project.id, content_hash=uuid4().hex)
    db.add(report)
    db.flush()
    job = Job(
        project_id=project.id,
        report_id=report.id,
        schedule_version_id=version.id,
    )
    db.add(job)
    db.flush()
    return job


def _run(job: Job) -> AgentRun:
    return AgentRun(
        job_id=job.id,
        graph_version="report-analysis-v1",
        state_schema_version="agent-state-v1",
        framework_version="1.2.12",
        thread_id=str(uuid4()),
        execution_mode="graph",
        state="running",
        current_node="load_context",
        counters={
            "node_executions": 1,
            "extraction_calls": 0,
            "selection_calls": 0,
            "corrective_retries": 0,
        },
        model_metadata={"model_tag": "fixture", "model_digest": "sha256:fixture"},
        prompt_metadata={"extraction_version": "v1", "extraction_hash": "a" * 64},
        config_metadata={"settings_hash": "b" * 64},
    )


def _step(run: AgentRun, *, ordinal: int = 1, node: str = "load_context") -> AgentStep:
    now = datetime.now(timezone.utc)
    return AgentStep(
        run_id=run.id,
        ordinal=ordinal,
        node=node,
        attempt=1,
        state="succeeded",
        input_hash="a" * 64,
        output_hash="b" * 64,
        sanitized_summary={"fragment_count": 2, "job_id": str(run.job_id)},
        started_at=now,
        finished_at=now,
        duration_ms=4,
    )


def test_agent_trace_records_round_trip_and_relationships_are_ordered(db):
    job = _job(db)
    run = _run(job)
    db.add(run)
    db.flush()
    later = _step(run, ordinal=2, node="extract")
    first = _step(run, ordinal=1)
    db.add_all([later, first])
    db.flush()
    tool = AgentToolCall(
        step_id=later.id,
        tool_name="extract_observations",
        attempt=1,
        state="succeeded",
        sanitized_input_summary={"fragment_count": 2},
        sanitized_output_summary={"observation_count": 1},
        started_at=later.started_at,
        finished_at=later.finished_at,
        duration_ms=3,
    )
    db.add(tool)
    db.flush()
    db.expire_all()

    stored = db.get(AgentRun, run.id)
    assert stored.job_id == job.id
    assert stored.state_schema_version == "agent-state-v1"
    assert [step.ordinal for step in stored.steps] == [1, 2]
    assert stored.steps[1].tool_calls[0].tool_name == "extract_observations"


def test_one_agent_run_per_job_and_unique_thread(db):
    first_job = _job(db)
    first = _run(first_job)
    db.add(first)
    db.flush()

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            duplicate_job = _run(first_job)
            db.add(duplicate_job)
            db.flush()

    second_job = _job(db)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            duplicate_thread = _run(second_job)
            duplicate_thread.thread_id = first.thread_id
            db.add(duplicate_thread)
            db.flush()


def test_step_ordinals_and_node_attempts_are_unique_within_run(db):
    run = _run(_job(db))
    db.add(run)
    db.flush()
    db.add(_step(run))
    db.flush()

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(_step(run, ordinal=1, node="extract"))
            db.flush()

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(_step(run, ordinal=2, node="load_context"))
            db.flush()


def test_tool_call_requires_real_step_and_unique_attempt(db):
    run = _run(_job(db))
    db.add(run)
    db.flush()
    step = _step(run)
    db.add(step)
    db.flush()
    values = {
        "step_id": step.id,
        "tool_name": "load_job_context",
        "attempt": 1,
        "state": "succeeded",
        "sanitized_input_summary": {"job_id": str(run.job_id)},
        "sanitized_output_summary": {"fragment_count": 2},
        "duration_ms": 1,
    }
    db.add(AgentToolCall(**values))
    db.flush()

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(AgentToolCall(**values))
            db.flush()

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            missing_step = dict(values, step_id=uuid4(), tool_name="retrieve_candidates")
            db.add(AgentToolCall(**missing_step))
            db.flush()


@pytest.mark.parametrize(
    ("model", "changes"),
    [
        ("run", {"state": "unexpected"}),
        ("step", {"ordinal": 0}),
        ("step", {"state": "running", "duration_ms": 1}),
        ("tool", {"attempt": 0}),
        ("tool", {"state": "succeeded", "error_code": "AGENT_TOOL_FAILED"}),
    ],
)
def test_database_rejects_invalid_trace_invariants(db, model, changes):
    run = _run(_job(db))
    db.add(run)
    db.flush()
    step = _step(run)
    db.add(step)
    db.flush()

    if model == "run":
        record = _run(_job(db))
    elif model == "step":
        record = _step(run, ordinal=2, node="extract")
    else:
        record = AgentToolCall(
            step_id=step.id,
            tool_name="load_job_context",
            attempt=1,
            state="succeeded",
            sanitized_input_summary={},
            sanitized_output_summary={},
        )
    for key, value in changes.items():
        setattr(record, key, value)

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(record)
            db.flush()
