"""PostgreSQL coverage for v2 run dispatch, task persistence, and resume behavior."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import sleep

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select

import test_agent_runtime as runtime_tests
import app.agent.hierarchy as hierarchy_module
from app.agent.runtime import AgentRuntimeError
from app.agent.contracts import AgentRole, TaskError, TaskEnvelope, TaskOutcome, TaskResult, stable_task_id
from app.agent.task_store import TaskStore, TaskStoreError, input_fingerprint
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


def test_v2_cancel_during_model_call_rejects_late_child_completion(
    runtime_fixture, monkeypatch
):
    """A response arriving after cancellation cannot complete or spawn work."""
    _set_hierarchy(monkeypatch, True)
    original = runtime_fixture.model

    def cancel_while_model_is_in_flight(**kwargs):
        result = original(**kwargs)
        if runtime_fixture.calls == ["extraction"]:
            with session_factory.begin() as db:
                job = db.get(Job, runtime_fixture.job_id)
                job.state = "cancelled"
        return result

    runtime_fixture.model = cancel_while_model_is_in_flight
    with pytest.raises(AgentRuntimeError) as error:
        runtime_fixture.run()
    assert error.value.code == "JOB_LEASE_LOST"
    assert runtime_fixture.calls == ["extraction"]

    with session_factory() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        tasks = list(db.scalars(select(AgentTask).where(AgentTask.run_id == run.id)))
        assert run.state == "cancelled"
        assert tasks and all(task.status != "running" for task in tasks)
        assert all(task.error_code == "JOB_CANCELLED" for task in tasks if task.status == "failed")
        assert not any(task.agent_role in {"matching", "selection", "review"} for task in tasks)
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 0
        assert db.scalar(select(func.count()).select_from(Proposal).join(
            Observation, Proposal.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 0
        usage = run.config_metadata["hierarchy_usage"]
        assert usage["model_calls"] >= 1
        # The model call reservation survives cancellation; it is not refunded
        # or reset when the late response is discarded.


def test_v2_failed_child_retry_uses_new_attempt_and_keeps_root_budget(
    runtime_fixture,
):
    """A failed child remains auditable while a bounded retry completes."""
    with session_factory.begin() as db:
        job = db.get(Job, runtime_fixture.job_id)
        run = AgentRun(
            job_id=job.id, graph_version="report-analysis-v2",
            state_schema_version="agent-state-v2", framework_version="test",
            thread_id=runtime_tests.uuid4().hex, execution_mode="graph", state="running",
            counters={}, model_metadata={}, prompt_metadata={}, config_metadata={},
            started_at=runtime_tests._utcnow(),
        )
        db.add(run)
        db.flush()
        run_id = run.id

    store = TaskStore(session_factory, run_id)
    def envelope(role, parent=None, attempt=1):
        return TaskEnvelope(
            task_id=stable_task_id(run_id=run_id,
                parent_task_id=parent.task_id if parent else None,
                agent_role=role, attempt=attempt),
            parent_task_id=parent.task_id if parent else None,
            run_id=run_id, agent_role=role, project_id=runtime_fixture.project_id,
            source_id=runtime_fixture.report_id, schedule_version_id=runtime_fixture.schedule_id,
            attempt=attempt,
        )

    root = envelope(AgentRole.ROOT)
    store.begin(root, input_fingerprint=input_fingerprint("run"))
    failed_child = envelope(AgentRole.ANALYSIS, root)
    store.begin(failed_child, input_fingerprint=input_fingerprint("analysis-attempt-1"))
    charged = store.reserve_budget("model_calls")
    failed_result = TaskResult(
        task_id=failed_child.task_id, parent_task_id=root.task_id, run_id=run_id,
        agent_role=AgentRole.ANALYSIS, project_id=runtime_fixture.project_id,
        source_id=runtime_fixture.report_id, schedule_version_id=runtime_fixture.schedule_id,
        outcome=TaskOutcome.FAILED,
        error=TaskError(code="PROVIDER_TIMEOUT", safe_message="private source excerpt"),
        actual_usage={"model_calls": 1},
    )
    failed_record = store.finish(failed_child, failed_result)
    assert failed_record.status == "failed"
    assert failed_record.error_code == "PROVIDER_TIMEOUT"

    retry_child = envelope(AgentRole.ANALYSIS, root, attempt=2)
    store.begin(retry_child, input_fingerprint=input_fingerprint("analysis-attempt-2"))
    retry_result = TaskResult(
        task_id=retry_child.task_id, parent_task_id=root.task_id, run_id=run_id,
        agent_role=AgentRole.ANALYSIS, project_id=runtime_fixture.project_id,
        source_id=runtime_fixture.report_id, schedule_version_id=runtime_fixture.schedule_id,
        outcome=TaskOutcome.COMPLETED, output_references=["observations:retry"],
    )
    assert store.finish(retry_child, retry_result).status == "succeeded"
    assert store.budget_snapshot()["used"]["model_calls"] == charged
    with session_factory() as db:
        children = list(db.scalars(select(AgentTask).where(
            AgentTask.run_id == run_id, AgentTask.parent_task_id == root.task_id
        ).order_by(AgentTask.attempt)))
        assert [(child.attempt, child.status, child.error_code) for child in children] == [
            (1, "failed", "PROVIDER_TIMEOUT"), (2, "succeeded", None)
        ]
        assert "private source excerpt" not in str(children[0].safe_summary)


def test_task_store_serializes_child_creation_with_parent_completion(runtime_fixture):
    """A child cannot slip in after a concurrently committed parent finish."""
    with session_factory.begin() as db:
        job = db.get(Job, runtime_fixture.job_id)
        run = AgentRun(
            job_id=job.id, graph_version="report-analysis-v2",
            state_schema_version="agent-state-v2", framework_version="test",
            thread_id=runtime_tests.uuid4().hex, execution_mode="graph", state="running",
            counters={}, model_metadata={}, prompt_metadata={}, config_metadata={},
            started_at=runtime_tests._utcnow(),
        )
        db.add(run)
        db.flush()
        run_id = run.id
    store = TaskStore(session_factory, run_id)

    def make_envelope(role, parent=None):
        return TaskEnvelope(
            task_id=stable_task_id(run_id=run_id,
                parent_task_id=parent.task_id if parent else None, agent_role=role, attempt=1),
            parent_task_id=parent.task_id if parent else None, run_id=run_id,
            agent_role=role, project_id=runtime_fixture.project_id,
            source_id=runtime_fixture.report_id, schedule_version_id=runtime_fixture.schedule_id,
            attempt=1,
        )

    root = make_envelope(AgentRole.ROOT)
    store.begin(root, input_fingerprint=input_fingerprint("root"))
    parent = make_envelope(AgentRole.ANALYSIS, root)
    store.begin(parent, input_fingerprint=input_fingerprint("parent"))
    late_child = make_envelope(AgentRole.EXTRACTION, parent)

    lock_acquired, allow_parent_commit = Event(), Event()
    child_started, child_done = Event(), Event()

    def finish_parent():
        with session_factory.begin() as db:
            row = db.scalar(select(AgentTask).where(
                AgentTask.id == parent.task_id
            ).with_for_update())
            row.status, row.outcome = "succeeded", "completed"
            row.finished_at = runtime_tests._utcnow()
            lock_acquired.set()
            if not allow_parent_commit.wait(timeout=5):
                raise TimeoutError("parent lock release was not signalled")

    def begin_child():
        child_started.set()
        try:
            return store.begin(late_child, input_fingerprint=input_fingerprint("late child"))
        finally:
            child_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        finish_future = pool.submit(finish_parent)
        assert lock_acquired.wait(timeout=5)
        child_future = pool.submit(begin_child)
        assert child_started.wait(timeout=5)
        sleep(0.1)
        assert not child_done.is_set(), "child begin did not wait for parent row lock"
        allow_parent_commit.set()
        finish_future.result(timeout=5)
        with pytest.raises(TaskStoreError, match="parent task is not active"):
            child_future.result(timeout=5)

    with session_factory() as db:
        parent_row = db.get(AgentTask, parent.task_id)
        assert parent_row.status == "succeeded"
        assert db.get(AgentTask, late_child.task_id) is None


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


def _task_tree_fixture(fixture):
    with session_factory.begin() as db:
        run = AgentRun(job_id=fixture.job_id, graph_version="report-analysis-v2",
            state_schema_version="agent-state-v2", framework_version="test",
            thread_id=runtime_tests.uuid4().hex, execution_mode="graph", state="running",
            counters={}, model_metadata={}, prompt_metadata={}, config_metadata={})
        db.add(run)
        db.flush()
        run_id = run.id
    def envelope(role, parent=None):
        return TaskEnvelope(task_id=stable_task_id(run_id=run_id,
            parent_task_id=parent.task_id if parent else None, agent_role=role, attempt=1),
            parent_task_id=parent.task_id if parent else None, run_id=run_id,
            agent_role=role, project_id=fixture.project_id, source_id=fixture.report_id,
            schedule_version_id=fixture.schedule_id, attempt=1)
    store = TaskStore(session_factory, run_id)
    root = envelope(AgentRole.ROOT)
    parent = envelope(AgentRole.ANALYSIS, root)
    child = envelope(AgentRole.EXTRACTION, parent)
    for task in (root, parent, child):
        store.begin(task, input_fingerprint=input_fingerprint(task.agent_role.value))
    return store, root, parent, child


def _completed(task):
    return TaskResult(**{key: getattr(task, key) for key in (
        "task_id", "parent_task_id", "run_id", "agent_role", "project_id",
        "source_id", "schedule_version_id")}, outcome=TaskOutcome.COMPLETED)


def test_task_store_rejects_parent_completion_until_child_terminal(runtime_fixture):
    store, root, parent, child = _task_tree_fixture(runtime_fixture)
    with pytest.raises(TaskStoreError, match="unfinished children"):
        store.finish(parent, _completed(parent))
    assert store.finish(child, _completed(child)).status == "succeeded"
    assert store.finish(parent, _completed(parent)).status == "succeeded"
    # A duplicate child completion remains idempotent after its parent closes.
    assert store.finish(child, _completed(child)).reused
    assert store.finish(root, _completed(root)).status == "succeeded"


def test_task_finish_waits_for_cancellation_and_closes_entire_tree(runtime_fixture):
    store, root, parent, child = _task_tree_fixture(runtime_fixture)
    charged = store.reserve_budget("model_calls")
    locked, release, finished = Event(), Event(), Event()
    def cancel():
        with session_factory.begin() as db:
            job = db.scalar(select(Job).where(Job.id == runtime_fixture.job_id).with_for_update())
            job.state = "cancelled"
            locked.set()
            assert release.wait(timeout=5)
    def finish():
        try:
            return store.finish(child, _completed(child))
        finally:
            finished.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        cancellation = pool.submit(cancel)
        assert locked.wait(timeout=5)
        completion = pool.submit(finish)
        sleep(0.1)
        assert not finished.is_set()
        release.set()
        cancellation.result(timeout=5)
        with pytest.raises(TaskStoreError, match="job is cancelled"):
            completion.result(timeout=5)
    with session_factory() as db:
        tasks = list(db.scalars(select(AgentTask).where(AgentTask.run_id == root.run_id)))
        assert len(tasks) == 3
        assert all(task.status == "failed" and task.error_code == "JOB_CANCELLED"
                   and task.finished_at is not None for task in tasks)
        assert db.get(AgentRun, root.run_id).state == "cancelled"
    assert store.budget_snapshot()["used"]["model_calls"] == charged
    with pytest.raises(TaskStoreError, match="job is cancelled"):
        store.begin(child, input_fingerprint=input_fingerprint("extraction"))


def test_v2_final_publication_observes_cancellation_and_keeps_success_history(runtime_fixture):
    from app.agent.runtime import _finalize
    from types import SimpleNamespace
    store, root, parent, child = _task_tree_fixture(runtime_fixture)
    store.finish(child, _completed(child))
    with session_factory.begin() as db:
        db.get(Job, runtime_fixture.job_id).state = "cancelled"
    with pytest.raises(AgentRuntimeError) as error:
        _finalize(session_factory, runtime_fixture.job_id, runtime_fixture.token,
                  root.run_id, SimpleNamespace(terminal_state="ready_for_review"))
    assert error.value.code == "JOB_LEASE_LOST"
    with session_factory() as db:
        assert db.get(Job, runtime_fixture.job_id).state == "cancelled"
        assert db.get(AgentRun, root.run_id).state == "cancelled"
        assert db.get(AgentTask, child.task_id).status == "succeeded"
        assert db.get(AgentTask, parent.task_id).error_code == "JOB_CANCELLED"
        assert db.get(AgentTask, root.task_id).error_code == "JOB_CANCELLED"


def test_analysis_scope_does_not_merge_pending_extraction(runtime_fixture):
    from app.agent.tools import AgentToolError
    store, root, parent, child = _task_tree_fixture(runtime_fixture)
    execution = hierarchy_module.HierarchyExecution.__new__(hierarchy_module.HierarchyExecution)
    execution.sessions, execution.store, execution.task_usage = session_factory, store, {}
    with pytest.raises(AgentToolError) as error:
        execution.finish_analysis_scope(parent)
    assert error.value.code == "AGENT_DEPENDENCY_PENDING"
    with session_factory() as db:
        assert db.get(AgentTask, parent.task_id).status == "running"
    store.finish(child, _completed(child))
    execution.finish_analysis_scope(parent)
    with session_factory() as db:
        assert db.get(AgentTask, parent.task_id).status == "succeeded"


def test_cancellation_fence_refreshes_previously_loaded_job(runtime_fixture):
    store, root, parent, child = _task_tree_fixture(runtime_fixture)
    with session_factory() as reader:
        cached_job = reader.get(Job, runtime_fixture.job_id)
        cached_run = reader.get(AgentRun, root.run_id)
        assert cached_job.state == "running"
        assert cached_run.state == "running"
        with session_factory.begin() as writer:
            writer.get(Job, runtime_fixture.job_id).state = "cancelled"
        # PostgreSQL READ COMMITTED sees cancellation in the locked SELECT;
        # populate_existing must also refresh the ORM identity map.
        with pytest.raises(TaskStoreError, match="job is cancelled"):
            store.lock_active_job(reader)
    with session_factory() as db:
        assert db.get(AgentRun, root.run_id).state == "cancelled"
        assert db.get(AgentTask, child.task_id).error_code == "JOB_CANCELLED"


def test_cancel_service_closes_idle_tree_atomically_without_worker(runtime_fixture):
    from app.jobs.service import cancel_job
    store, root, parent, child = _task_tree_fixture(runtime_fixture)
    store.reserve_budget("model_calls")
    with session_factory() as db:
        before = db.get(AgentRun, root.run_id)
        started, counters, metadata = before.started_at, dict(before.counters), dict(before.config_metadata)
    with session_factory.begin() as db:
        cancelled = cancel_job(db, db.get(Job, runtime_fixture.job_id))
        assert cancelled.lease_token is None and cancelled.lease_expires_at is None
    with session_factory() as db:
        run = db.get(AgentRun, root.run_id)
        completed = run.completed_at
        assert (run.started_at, run.counters, run.config_metadata) == (started, counters, metadata)
        assert run.state == "cancelled"
        tasks = list(db.scalars(select(AgentTask).where(AgentTask.run_id == run.id)))
        assert all(t.status == "failed" and t.error_code == "JOB_CANCELLED" for t in tasks)
    with session_factory.begin() as db:
        cancel_job(db, db.get(Job, runtime_fixture.job_id))
    with session_factory() as db:
        assert db.get(AgentRun, root.run_id).completed_at == completed
        with pytest.raises(ValueError, match="JOB_NOT_RETRYABLE"):
            retry_job(db, db.get(Job, runtime_fixture.job_id))
    with pytest.raises(AgentRuntimeError) as error:
        runtime_fixture.run()
    assert error.value.code == "JOB_LEASE_LOST"
    assert not runtime_fixture.calls


def test_cancel_service_rolls_back_job_run_and_tasks_together(runtime_fixture):
    from app.jobs.service import cancel_job
    store, root, parent, child = _task_tree_fixture(runtime_fixture)
    with session_factory() as db:
        cancel_job(db, db.get(Job, runtime_fixture.job_id))
        db.rollback()
    with session_factory() as db:
        assert db.get(Job, runtime_fixture.job_id).state == "running"
        assert db.get(AgentRun, root.run_id).state == "running"
        assert db.get(AgentTask, child.task_id).status == "running"


def test_repeated_expired_owner_resume_keeps_original_deadline_and_usage(runtime_fixture, monkeypatch):
    _set_hierarchy(monkeypatch, True)
    original_nodes = _crash_at_matching_after_extraction(monkeypatch)
    saver = MemorySaver()
    started = None
    previous_usage = {}
    token = runtime_fixture.token
    for _ in range(2):
        with pytest.raises(WorkerShutdown):
            runtime_fixture.run(token=token, checkpointer=saver)
        with session_factory() as db:
            run = _run_for_job(db, runtime_fixture.job_id)
            started = started or run.started_at
            assert run.started_at == started
            usage = dict(run.config_metadata["hierarchy_usage"])
            assert all(usage.get(key, 0) >= count for key, count in previous_usage.items())
            previous_usage = usage
        token = _expire_and_claim(runtime_fixture)
    with pytest.raises(AgentRuntimeError) as error:
        runtime_fixture.run(token=runtime_fixture.token, checkpointer=saver)
    assert error.value.code == "JOB_LEASE_LOST"
    monkeypatch.setattr(hierarchy_module, "_nodes", original_nodes)
    result = runtime_fixture.run(token=token, checkpointer=saver)
    assert result["state"] == "ready_for_review", result
    assert runtime_fixture.calls.count("extraction") == 1
    with session_factory() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        assert run.started_at == started
        assert all(run.config_metadata["hierarchy_usage"].get(key, 0) >= count
                   for key, count in previous_usage.items())
        assert db.get(Job, runtime_fixture.job_id).attempts == 3
    # Terminal resume is a read-only replay even for a previous owner.
    replay = runtime_fixture.run(token=runtime_fixture.token, checkpointer=saver)
    assert replay["state"] == "ready_for_review"
    assert runtime_fixture.calls.count("extraction") == 1
    with session_factory() as db:
        assert _run_for_job(db, runtime_fixture.job_id).started_at == started


def test_missing_parent_dependency_rejects_child_without_persisting(runtime_fixture):
    store, root, parent, child = _task_tree_fixture(runtime_fixture)
    unavailable = child.model_copy(update={"parent_task_id": runtime_tests.uuid4(),
                                            "task_id": runtime_tests.uuid4()})
    with pytest.raises(TaskStoreError, match="parent task does not exist"):
        store.begin(unavailable, input_fingerprint=input_fingerprint("missing-parent"))
    with session_factory() as db:
        assert db.get(AgentTask, unavailable.task_id) is None
        assert db.get(AgentTask, child.task_id).status == "running"


def test_resume_does_not_extend_exhausted_root_deadline(runtime_fixture, monkeypatch):
    _set_hierarchy(monkeypatch, True)
    original_nodes = _crash_at_matching_after_extraction(monkeypatch)
    saver = MemorySaver()
    with pytest.raises(WorkerShutdown):
        runtime_fixture.run(checkpointer=saver)
    with session_factory.begin() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        run.started_at = runtime_tests._utcnow() - timedelta(seconds=1801)
        pinned_start = run.started_at
        prior_calls = run.config_metadata["hierarchy_usage"]["model_calls"]
    token = _expire_and_claim(runtime_fixture)
    monkeypatch.setattr(hierarchy_module, "_nodes", original_nodes)
    result = runtime_fixture.run(token=token, checkpointer=saver)
    assert result["state"] == "failed", result
    assert result["error_code"] == "AGENT_DEADLINE", result
    assert runtime_fixture.calls.count("extraction") == 1
    with session_factory() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        assert run.started_at == pinned_start
        assert run.config_metadata["hierarchy_usage"]["model_calls"] == prior_calls


def test_unavailable_matching_dependency_fails_tree_without_selection(runtime_fixture, monkeypatch):
    from app.agent.tools import AgentToolError
    _set_hierarchy(monkeypatch, True)
    original_nodes = hierarchy_module._nodes
    def unavailable(tools, policy):
        nodes = original_nodes(tools, policy)
        if getattr(tools, "role", None) == "matching":
            def fail(_state):
                raise AgentToolError("AGENT_DEPENDENCY_UNAVAILABLE", "The matching dependency is unavailable.")
            nodes["retrieve"] = fail
        return nodes
    monkeypatch.setattr(hierarchy_module, "_nodes", unavailable)
    result = runtime_fixture.run()
    assert result["state"] == "failed", result
    assert result["error_code"] == "AGENT_DEPENDENCY_UNAVAILABLE", result
    assert runtime_fixture.calls == ["extraction"]
    with session_factory() as db:
        run = _run_for_job(db, runtime_fixture.job_id)
        tasks = list(db.scalars(select(AgentTask).where(AgentTask.run_id == run.id)))
        assert tasks and not any(task.status == "running" for task in tasks)
        assert db.scalar(select(func.count()).select_from(Proposal).join(
            Observation, Proposal.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 0
