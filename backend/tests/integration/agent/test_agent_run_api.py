from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    AgentRun,
    AgentStep,
    AgentTask,
    Fragment,
    Job,
    Project,
    ProjectMembership,
    Report,
    ScheduleVersion,
    User,
)
from app.db.passwords import hash_password
from app.db.session import engine, get_session
from app.main import app

SECRET_MARKERS = (
    "https://private.invalid/secret-endpoint",
    "private-token-value",
    "prompt text must never appear",
    "report body must never appear",
    "checkpoint blob must never appear",
)


@pytest.fixture
def client():
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

    def database_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_session] = database_session
    try:
        yield TestClient(app), factory
    finally:
        app.dependency_overrides.clear()
        transaction.rollback()
        connection.close()


def _seed(factory, *, role="reviewer", include_run=True, execution_mode="graph",
          state="running", error_code=None, graph_version="report-analysis-v1",
          framework_version="langgraph-1.2.12/checkpoint-postgres-3.1.2", steps=True):
    db = factory()
    user = User(username=f"w37-{uuid4().hex}", password_hash=hash_password("test-password"), role=role)
    project = Project(name=f"W37 {uuid4().hex}", timezone="Asia/Kolkata")
    db.add_all([user, project])
    db.flush()
    db.add(ProjectMembership(project_id=project.id, user_id=user.id))
    version = ScheduleVersion(project_id=project.id, version_number=1, content_sha256=uuid4().hex)
    db.add(version)
    db.flush()
    project.active_schedule_version_id = version.id
    report = Report(project_id=project.id, content_hash=uuid4().hex)
    db.add(report)
    db.flush()
    db.add(Fragment(report_id=report.id, ordinal=1, locator="fixture:1",
                    original_text=SECRET_MARKERS[3], normalised_text=SECRET_MARKERS[3]))
    job = Job(project_id=project.id, report_id=report.id, schedule_version_id=version.id)
    db.add(job)
    db.flush()
    run = None
    if include_run:
        now = datetime.now(timezone.utc)
        run = AgentRun(
            job_id=job.id,
            graph_version=graph_version,
            state_schema_version="agent-state-v1",
            framework_version=framework_version,
            thread_id=str(uuid4()),
            execution_mode=execution_mode,
            state=state,
            current_node="record_failure" if state in {"failed", "stale"} else "load_context",
            counters={"node_executions": 3, "extraction_calls": 1, "selection_calls": 0,
                      "corrective_retries": 0, "untrusted_extra": "must be hidden"},
            model_metadata={"model_tag": SECRET_MARKERS[1], "endpoint": SECRET_MARKERS[0]},
            prompt_metadata={"prompt": SECRET_MARKERS[2]},
            config_metadata={"database_url": SECRET_MARKERS[0], "token": SECRET_MARKERS[1]},
            started_at=now,
            updated_at=now,
            completed_at=now if state in {"failed", "stale"} else None,
            error_code=error_code,
            error_message=f"{SECRET_MARKERS[0]} {SECRET_MARKERS[1]} {SECRET_MARKERS[2]} {SECRET_MARKERS[3]}" if error_code else None,
        )
        db.add(run)
        db.flush()
        db.execute(text("""INSERT INTO checkpoints
            (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
            VALUES (:thread_id, '', :checkpoint_id, NULL, 'json', CAST(:payload AS jsonb), '{}'::jsonb)"""),
            {"thread_id": run.thread_id, "checkpoint_id": "w37-fixture",
             "payload": json.dumps({"secret": SECRET_MARKERS[4]})})
        if steps:
            # Insert out of order; the public endpoint must return ordinal order.
            for ordinal, node in ((2, "extract"), (1, "load_context")):
                failed = state in {"failed", "stale"} and ordinal == 2
                db.add(AgentStep(
                    run_id=run.id,
                    ordinal=ordinal,
                    node=node,
                    attempt=1,
                    state="failed" if failed else "succeeded",
                    input_hash="a" * 64,
                    output_hash="b" * 64,
                    sanitized_summary={"raw": " ".join(SECRET_MARKERS)},
                    started_at=now,
                    finished_at=now,
                    duration_ms=ordinal * 7,
                    error_code="untrusted://code" if failed else None,
                    error_message=" ".join(SECRET_MARKERS) if failed else None,
                ))
    db.commit()
    result = {"job_id": job.id, "project_id": project.id,
              "run_id": run.id if run else None, "user_id": user.id}
    db.close()
    return result


def _username(factory, user_id):
    db = factory()
    value = db.get(User, user_id).username
    db.close()
    return value


@pytest.mark.parametrize("role", ["reviewer", "viewer"])
def test_member_reads_strict_ordered_status_without_internal_fields(client, role):
    browser, factory = client
    seeded = _seed(factory, role=role)
    user = _username(factory, seeded["user_id"])
    login = browser.post("/api/v1/auth/login", json={"username": user, "password": "test-password"})
    assert login.status_code == 200
    response = browser.get(f"/api/v1/jobs/{seeded['job_id']}/agent-run")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"id", "job_id", "graph_version", "framework_version", "state",
        "current_stage", "counters", "steps", "tasks", "hierarchy_usage", "error_code", "error_message", "started_at",
        "updated_at", "completed_at"}
    assert payload["id"] == str(seeded["run_id"])
    assert payload["current_stage"] == "Loading context"
    assert [step["ordinal"] for step in payload["steps"]] == [1, 2]
    assert [step["label"] for step in payload["steps"]] == ["Loading context", "Extracting observations"]
    assert all(set(step) == {"ordinal", "node", "label", "state", "attempt", "duration_ms", "error_code"}
               for step in payload["steps"])
    assert payload["counters"] == {"node_executions": 3, "extraction_calls": 1,
        "selection_calls": 0, "corrective_retries": 0}
    assert payload["tasks"] == []
    assert payload["hierarchy_usage"] is None
    assert response.headers["cache-control"] == "no-store"
    serialized = response.content.decode()
    assert not any(secret in serialized for secret in SECRET_MARKERS)


def test_v2_tasks_and_usage_are_sanitized_and_public(client):
    browser, factory = client
    seeded = _seed(factory, graph_version="report-analysis-v2")
    db = factory()
    run = db.get(AgentRun, seeded["run_id"])
    run.current_node = "analysis"
    run.config_metadata = {"hierarchy_usage": {"delegations": 2,
        "supervisor_transitions": 3, "model_calls": 4, "tool_calls": 5},
        "private_config": SECRET_MARKERS[0]}
    now = datetime.now(timezone.utc)
    run.updated_at = max(now, run.started_at)
    root_id = uuid4()
    child_id = uuid4()
    common = {"run_id": run.id, "project_id": seeded["project_id"],
        "source_id": run.job.report_id,
        "schedule_version_id": run.job.schedule_version_id,
        "contract_version": "agent-task-v1", "input_fingerprint": "c" * 64,
        "input_references": [SECRET_MARKERS[3]], "output_references": [SECRET_MARKERS[4]],
        "evidence_references": [], "warnings": ["AGENT_INTERNAL_ERROR"],
        "actual_usage": {"model_calls": 1}, "safe_summary": {"status": "completed"},
        "status": "succeeded", "outcome": "completed", "error_code": SECRET_MARKERS[1],
        "started_at": now, "finished_at": now}
    child_common = {**common, "started_at": now + timedelta(microseconds=1),
        "finished_at": now + timedelta(microseconds=1)}
    db.add_all([
        AgentTask(id=root_id, parent_task_id=None, agent_role="root", attempt=1,
            observation_key=None, **common),
        AgentTask(id=child_id, parent_task_id=root_id, agent_role="analysis", attempt=1,
            observation_key=None, **child_common),
    ])
    db.add(AgentStep(run_id=run.id, ordinal=3, node="analysis", attempt=1,
        state="succeeded", started_at=now, finished_at=now, duration_ms=8))
    db.commit()
    db.close()
    browser.post("/api/v1/auth/login", json={"username": _username(factory, seeded["user_id"]),
                             "password": "test-password"})
    response = browser.get(f"/api/v1/jobs/{seeded['job_id']}/agent-run")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["graph_version"] == "report-analysis-v2"
    assert payload["current_stage"] == "Analyzing report"
    assert payload["steps"][-1]["label"] == "Analyzing report"
    assert [(task["role"], task["parent_task_id"], task["attempt"], task["outcome"])
            for task in payload["tasks"]] == [
        ("root", None, 1, "completed"), ("analysis", str(root_id), 1, "completed")]
    assert payload["hierarchy_usage"] == {"delegations": 2, "supervisor_transitions": 3,
        "model_calls": 4, "tool_calls": 5}
    serialized = response.content.decode()
    assert not any(secret in serialized for secret in SECRET_MARKERS)


def test_unauthenticated_and_cross_project_access_are_not_found_or_authorized(client):
    browser, factory = client
    target = _seed(factory)
    unauthenticated = browser.get(f"/api/v1/jobs/{target['job_id']}/agent-run")
    assert unauthenticated.status_code == 401
    outsider = _seed(factory, role="viewer", include_run=False)
    login = browser.post("/api/v1/auth/login", json={"username": _username(factory, outsider["user_id"]),
                                    "password": "test-password"})
    assert login.status_code == 200
    cross_project = browser.get(f"/api/v1/jobs/{target['job_id']}/agent-run")
    assert cross_project.status_code == 404


@pytest.mark.parametrize("include_run,execution_mode", [(False, "graph"), (True, "legacy")])
def test_legacy_job_or_job_without_graph_run_returns_404(client, include_run, execution_mode):
    browser, factory = client
    seeded = _seed(factory, include_run=include_run, execution_mode=execution_mode)
    browser.post("/api/v1/auth/login", json={"username": _username(factory, seeded["user_id"]),
                             "password": "test-password"})
    response = browser.get(f"/api/v1/jobs/{seeded['job_id']}/agent-run")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("state", "error_code", "expected_code", "expected_message"),
    [
        ("failed", "AGENT_TOOL_FAILED", "AGENT_TOOL_FAILED", "The report analysis tool failed safely."),
        ("stale", "SCHEDULE_VERSION_STALE", "SCHEDULE_VERSION_STALE", "The project schedule changed during this run."),
        ("failed", "https://untrusted.invalid/token", "AGENT_INTERNAL_ERROR", "The report analysis run failed safely."),
    ],
)
def test_failed_and_stale_errors_are_allowlisted_and_sanitized(
    client, state, error_code, expected_code, expected_message
):
    browser, factory = client
    seeded = _seed(factory, state=state, error_code=error_code)
    browser.post("/api/v1/auth/login", json={"username": _username(factory, seeded["user_id"]),
                             "password": "test-password"})
    response = browser.get(f"/api/v1/jobs/{seeded['job_id']}/agent-run")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["error_code"] == expected_code
    assert payload["error_message"] == expected_message
    assert payload["current_stage"] == ("Stale" if state == "stale" else "Failed")
    assert [step["label"] for step in payload["steps"]] == ["Loading context", "Extracting observations"]
    assert payload["steps"][1]["error_code"] == "AGENT_INTERNAL_ERROR"
    serialized = response.content.decode()
    assert not any(secret in serialized for secret in SECRET_MARKERS)
    assert "untrusted.invalid" not in serialized


def test_version_mismatches_use_safe_placeholders(client):
    browser, factory = client
    seeded = _seed(factory, graph_version="https://private.invalid/token",
                   framework_version="private-token-value")
    browser.post("/api/v1/auth/login", json={"username": _username(factory, seeded["user_id"]),
                             "password": "test-password"})
    response = browser.get(f"/api/v1/jobs/{seeded['job_id']}/agent-run")
    assert response.status_code == 200, response.text
    assert response.json()["graph_version"] == "unrecognized"
    assert response.json()["framework_version"] == "unrecognized"


@pytest.mark.parametrize("role", ["reviewer", "viewer"])
def test_job_cancellation_requires_reviewer_csrf_and_membership(client, role):
    browser, factory = client
    seeded = _seed(factory, role=role, steps=False)
    url = f"/api/v1/jobs/{seeded['job_id']}/cancel"
    assert browser.post(url).status_code == 401
    login = browser.post("/api/v1/auth/login", json={
        "username": _username(factory, seeded["user_id"]), "password": "test-password"})
    assert browser.post(url).status_code == 403
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    response = browser.post(url, headers=headers)
    if role == "viewer":
        assert response.status_code == 403
        return
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "cancelled"
    assert browser.post(url, headers=headers).json() == response.json()
    with factory() as db:
        assert db.get(AgentRun, seeded["run_id"]).state == "cancelled"
        assert db.get(Job, seeded["job_id"]).lease_token is None
    public = browser.get(f"/api/v1/jobs/{seeded['job_id']}/agent-run")
    assert public.json()["error_code"] == "JOB_CANCELLED"
    assert public.json()["error_message"] == "The job was cancelled."
    outsider = _seed(factory, steps=False)
    assert browser.post(f"/api/v1/jobs/{outsider['job_id']}/cancel", headers=headers).status_code == 404
