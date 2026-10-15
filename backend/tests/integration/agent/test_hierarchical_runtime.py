"""PostgreSQL coverage for v2 run dispatch, task persistence, and resume behavior."""
from __future__ import annotations

from datetime import timedelta

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select

import test_agent_runtime as runtime_tests
import app.agent.hierarchy as hierarchy_module
from app.agent.runtime import AgentRuntimeError
from app.db.models import AgentRun, AgentTask, Job, ProgressEvent, Observation, Proposal, Project
from app.db.session import session_factory
from app.jobs.service import claim_job, retry_job
from app.jobs.worker import WorkerShutdown
from app.settings import get_settings


@pytest.fixture
def runtime_fixture():
    fixture = runtime_tests.RuntimeFixture()
    try:
        yield fixture
    finally:
        fixture.cleanup()


def _set_hierarchy(monkeypatch, enabled: bool) -> None:
    monkeypatch.setattr(get_settings(), "agent_hierarchy_enabled", enabled)


def _expire_and_claim(fixture):
    with session_factory.begin() as db:
        job = db.get(Job, fixture.job_id)
        job.lease_expires_at = runtime_tests._utcnow() - timedelta(seconds=1)
    with session_factory.begin() as db:
        job, token = claim_job(db)
        assert job.id == fixture.job_id
    return token


def _run_for_job(db, job_id):
    return db.scalar(select(AgentRun).where(AgentRun.job_id == job_id))


def _crash_at_matching_after_extraction(monkeypatch):
    original_nodes = hierarchy_module._nodes

    def with_crash(tools, policy):
        nodes = original_nodes(tools, policy)
        if getattr(tools, "role", None) == "matching":
            def crash(_state):
                raise WorkerShutdown()
            nodes["retrieve"] = crash
        return nodes

    monkeypatch.setattr(hierarchy_module, "_nodes", with_crash)
    return original_nodes


def _retry_after_failure(fixture):
    with session_factory.begin() as db:
        retry_job(db, db.get(Job, fixture.job_id))
    with session_factory.begin() as db:
        job, token = claim_job(db)
        assert job.id == fixture.job_id
    return token


def test_v2_happy_path_persists_hierarchy_and_keeps_ledger_behind_approval(
    runtime_fixture, monkeypatch
):
    _set_hierarchy(monkeypatch, True)
    result = runtime_fixture.run()
    assert result["state"] == "ready_for_review"
    assert result["extracted_count"] == result["proposal_count"] == 1

    with session_factory() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        tasks = list(db.scalars(select(AgentTask).where(AgentTask.run_id == run.id)))
        by_id = {task.id: task for task in tasks}
        assert run.graph_version == "report-analysis-v2"
        assert {task.agent_role for task in tasks} >= {
            "root", "intake", "analysis", "extraction", "matching", "selection", "evidence", "review"
        }
        assert all(task.status == "succeeded" for task in tasks)
        for task in tasks:
            if task.agent_role == "root":
                assert task.parent_task_id is None
                continue
            parent = by_id[task.parent_task_id]
            assert parent.run_id == task.run_id
            assert (parent.project_id, parent.source_id, parent.schedule_version_id) == (
                task.project_id, task.source_id, task.schedule_version_id
            )
        assert db.scalar(select(func.count()).select_from(Proposal).join(
            Observation, Proposal.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 1
        assert db.scalar(select(func.count()).select_from(ProgressEvent).join(
            Observation, ProgressEvent.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 0


@pytest.mark.parametrize("started_v2", [False, True], ids=["v1-run-resumes-v1", "v2-run-resumes-v2"])
def test_run_version_is_pinned_when_rollout_flag_changes(
    runtime_fixture, monkeypatch, started_v2
):
    _set_hierarchy(monkeypatch, started_v2)
    if started_v2:
        original_nodes = _crash_at_matching_after_extraction(monkeypatch)
        with pytest.raises(WorkerShutdown):
            runtime_fixture.run()
        monkeypatch.setattr(hierarchy_module, "_nodes", original_nodes)
    else:
        with pytest.raises(WorkerShutdown):
            runtime_fixture.run(should_stop=runtime_tests._stop_on_check(5))
    with session_factory() as db:
        first = _run_for_job(db, runtime_fixture.job_id)
        pinned_graph = first.graph_version
        first_run_id = first.id
    assert pinned_graph == ("report-analysis-v2" if started_v2 else "report-analysis-v1")

    _set_hierarchy(monkeypatch, not started_v2)
    replacement = _expire_and_claim(runtime_fixture)
    result = runtime_fixture.run(token=replacement)
    assert result["state"] == "ready_for_review", result
    with session_factory() as db:
        runs = list(db.scalars(select(AgentRun).where(AgentRun.job_id == runtime_fixture.job_id)))
        assert len(runs) == 1
        assert runs[0].id == first_run_id
        assert runs[0].graph_version == pinned_graph


def test_v2_resume_after_extraction_reuses_completed_child_without_repeating_model_call(
    runtime_fixture, monkeypatch
):
    _set_hierarchy(monkeypatch, True)
    original_nodes = _crash_at_matching_after_extraction(monkeypatch)
    with pytest.raises(WorkerShutdown):
        runtime_fixture.run()
    monkeypatch.setattr(hierarchy_module, "_nodes", original_nodes)
    assert runtime_fixture.calls.count("extraction") == 1
    with session_factory() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        completed_extraction = db.scalar(select(AgentTask).where(
            AgentTask.run_id == run.id,
            AgentTask.agent_role == "extraction",
            AgentTask.status == "succeeded",
        ))
        assert completed_extraction is not None

    replacement = _expire_and_claim(runtime_fixture)
    # New-run dispatch now selects v1, but this already-created run must resume
    # through its pinned v2 hierarchy.
    _set_hierarchy(monkeypatch, False)
    runtime_fixture.model = runtime_tests.RuntimeFixture.model.__get__(runtime_fixture)
    result = runtime_fixture.run(token=replacement)
    assert result["state"] == "ready_for_review", result
    assert runtime_fixture.calls.count("extraction") == 1
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 1


def test_v2_schedule_change_marks_run_stale_without_applying_ledger(runtime_fixture, monkeypatch):
    _set_hierarchy(monkeypatch, True)
    original = runtime_fixture.model

    def changing_model(**kwargs):
        value = original(**kwargs)
        if runtime_fixture.calls == ["extraction"]:
            with session_factory.begin() as db:
                project = db.get(Project, runtime_fixture.project_id)
                from app.db.models import ScheduleVersion
                newer = ScheduleVersion(
                    project_id=project.id,
                    version_number=2,
                    content_sha256=runtime_tests.uuid4().hex,
                    state="active",
                )
                db.add(newer)
                db.flush()
                project.active_schedule_version_id = newer.id
        return value

    runtime_fixture.model = changing_model
    result = runtime_fixture.run()
    assert result["state"] == "stale"
    assert result["error_code"] == "SCHEDULE_VERSION_STALE"
    with session_factory() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        assert run.state == "stale"
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 0
        assert db.scalar(select(func.count()).select_from(ProgressEvent).join(
            Observation, ProgressEvent.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 0


def test_v2_lease_loss_can_be_reclaimed_and_resumed(runtime_fixture, monkeypatch):
    _set_hierarchy(monkeypatch, True)
    original = runtime_fixture.model

    def lose_lease(**kwargs):
        value = original(**kwargs)
        if runtime_fixture.calls == ["extraction"]:
            with session_factory.begin() as db:
                job = db.get(Job, runtime_fixture.job_id)
                job.lease_token = "replacement-owner"
                job.lease_expires_at = runtime_tests._utcnow() + timedelta(minutes=5)
        return value

    runtime_fixture.model = lose_lease
    with pytest.raises(AgentRuntimeError) as error:
        runtime_fixture.run()
    assert error.value.code == "JOB_LEASE_LOST"

    result = runtime_fixture.run(token="replacement-owner")
    assert result["state"] == "ready_for_review", result
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 1
        assert db.scalar(select(func.count()).select_from(ProgressEvent).join(
            Observation, ProgressEvent.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 0


def test_v2_persistence_checkpoint_failure_resumes_without_duplicate_proposals(
    runtime_fixture, monkeypatch
):
    _set_hierarchy(monkeypatch, True)

    class FailAfterCommit(MemorySaver):
        failed = False

        def put(self, config, checkpoint, metadata, new_versions):
            with session_factory() as db:
                persisted = db.scalar(select(func.count()).select_from(Observation).where(
                    Observation.job_id == runtime_fixture.job_id
                ))
            if persisted and not self.failed:
                self.failed = True
                raise RuntimeError("injected checkpoint failure")
            return super().put(config, checkpoint, metadata, new_versions)

    saver = FailAfterCommit()
    interrupted = runtime_fixture.run(checkpointer=saver)
    assert interrupted["state"] == "failed"
    assert interrupted["error_code"] == "AGENT_CHECKPOINT_FAILED"
    replacement = _retry_after_failure(runtime_fixture)
    resumed = runtime_fixture.run(token=replacement, checkpointer=saver)
    with session_factory() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        task_states = list(db.execute(select(
            AgentTask.agent_role, AgentTask.attempt, AgentTask.status,
            AgentTask.outcome, AgentTask.error_code,
        ).where(AgentTask.run_id == run.id, AgentTask.status != "succeeded")))
    assert resumed["state"] == "ready_for_review", {
        "result": resumed, "tasks": task_states,
    }
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 1
        assert db.scalar(select(func.count()).select_from(Proposal).join(
            Observation, Proposal.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 1
        assert db.scalar(select(func.count()).select_from(ProgressEvent).join(
            Observation, ProgressEvent.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 0
