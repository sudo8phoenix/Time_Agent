from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.budgets import BudgetExceeded, BudgetLimits, RootBudget
from app.agent.contracts import AgentRole, TaskEnvelope, TaskOutcome, TaskResult, stable_task_id
from app.agent.registry import DelegationError, validate_child
from app.agent.task_store import TaskStore, TaskStoreError, input_fingerprint
from app.db.base import Base
from app.db.models import AgentRun, AgentTask, Job, Project, Report, ScheduleVersion


def envelope(role: AgentRole, *, parent=None, run=None, project=None, source=None, schedule=None,
             observation_key=None, attempt=1):
    run = run or uuid4()
    project = project or uuid4()
    source = source or uuid4()
    schedule = schedule or uuid4()
    task_id = stable_task_id(run_id=run, parent_task_id=parent, agent_role=role,
                             observation_key=observation_key, attempt=attempt)
    return TaskEnvelope(
        task_id=task_id, parent_task_id=parent, run_id=run, agent_role=role,
        project_id=project, source_id=source, schedule_version_id=schedule,
        observation_key=observation_key, attempt=attempt,
    )


def test_contract_identity_and_registered_hierarchy_reject_scope_changes():
    root = envelope(AgentRole.ROOT)
    analysis = envelope(AgentRole.ANALYSIS, parent=root.task_id, run=root.run_id,
                        project=root.project_id, source=root.source_id, schedule=root.schedule_version_id)
    validate_child(root, analysis)
    illicit = envelope(AgentRole.SELECTION, parent=root.task_id, run=root.run_id,
                       project=root.project_id, source=root.source_id, schedule=root.schedule_version_id,
                       observation_key="obs-0001")
    with pytest.raises(DelegationError):
        validate_child(root, illicit)
    changed_scope = analysis.model_copy(update={"schedule_version_id": uuid4()})
    with pytest.raises(DelegationError):
        validate_child(root, changed_scope)
    assert stable_task_id(run_id=root.run_id, parent_task_id=None, agent_role="root", attempt=1) == root.task_id


def test_result_must_echo_task_identity_and_failure_has_typed_error():
    task = envelope(AgentRole.ROOT)
    result = TaskResult(
        task_id=task.task_id, parent_task_id=None, run_id=task.run_id, agent_role=task.agent_role,
        project_id=task.project_id, source_id=task.source_id,
        schedule_version_id=task.schedule_version_id, outcome=TaskOutcome.COMPLETED,
    )
    assert result.validate_for(task) is result
    with pytest.raises(ValueError, match="identity or pinned scope"):
        result.model_copy(update={"project_id": uuid4()}).validate_for(task)
    with pytest.raises(ValueError, match="require an error"):
        TaskResult(
            task_id=task.task_id, parent_task_id=None, run_id=task.run_id, agent_role=task.agent_role,
            project_id=task.project_id, source_id=task.source_id,
            schedule_version_id=task.schedule_version_id, outcome=TaskOutcome.FAILED,
        )


def test_root_budget_reserves_before_work_and_failed_attempts_stay_charged():
    budget = RootBudget(limits=BudgetLimits(model_calls=1))
    with pytest.raises(RuntimeError):
        budget.reserve_model_call()
        raise RuntimeError("simulated failed model call")
    assert budget.snapshot()["used"]["model_calls"] == 1
    with pytest.raises(BudgetExceeded):
        budget.reserve_model_call()


def make_store():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    project_id, report_id, schedule_id = uuid4(), uuid4(), uuid4()
    run_id, job_id = uuid4(), uuid4()
    with sessions() as session:
        project = Project(id=project_id, name="Test")
        schedule = ScheduleVersion(
            id=schedule_id, project_id=project_id, version_number=1,
            content_sha256="a" * 64, state="active",
        )
        report = Report(id=report_id, project_id=project_id, content_hash="b" * 64)
        job = Job(id=job_id, project_id=project_id, report_id=report_id,
                  schedule_version_id=schedule_id, state="running")
        run = AgentRun(
            id=run_id, job_id=job_id, graph_version="v2", state_schema_version="v2",
            framework_version="test", thread_id=str(uuid4()), execution_mode="graph",
            state="running", counters={}, model_metadata={}, prompt_metadata={}, config_metadata={},
        )
        session.add_all([project, schedule, report, job, run])
        session.commit()
    return engine, sessions, TaskStore(sessions, run_id), (run_id, project_id, report_id, schedule_id)


def test_task_store_persists_validated_children_and_reuses_success_by_fingerprint():
    engine, sessions, store, ids = make_store()
    run_id, project_id, source_id, schedule_id = ids
    root = envelope(AgentRole.ROOT, run=run_id, project=project_id, source=source_id, schedule=schedule_id)
    fingerprint = input_fingerprint({"input_ref": "report:123"})
    first = store.begin_task(root, input_fingerprint=fingerprint)
    assert first.status == "running"
    analysis = envelope(AgentRole.ANALYSIS, parent=root.task_id, run=run_id, project=project_id,
                        source=source_id, schedule=schedule_id)
    store.begin(analysis, input_fingerprint=input_fingerprint("analysis-v1"))
    child_result = TaskResult(
        task_id=analysis.task_id, parent_task_id=root.task_id, run_id=run_id,
        agent_role=AgentRole.ANALYSIS, project_id=project_id, source_id=source_id,
        schedule_version_id=schedule_id, outcome=TaskOutcome.COMPLETED,
        output_references=["observations:1"], evidence_references=["fragment:9"],
        actual_usage={"model_calls": 1},
    )
    done = store.finish_task(analysis, child_result, safe_summary={"observation_count": 1})
    assert done.status == "succeeded" and done.safe_summary["observation_count"] == 1
    reused = store.begin(analysis, input_fingerprint=input_fingerprint("analysis-v1"))
    assert reused.reused and reused.output_references == ("observations:1",)
    with pytest.raises(TaskStoreError, match="fingerprint"):
        store.begin(analysis, input_fingerprint=input_fingerprint("changed"))
    with pytest.raises(TaskStoreError, match="sensitive"):
        store.begin(envelope(AgentRole.REVIEW, parent=root.task_id, run=run_id, project=project_id,
                             source=source_id, schedule=schedule_id), input_fingerprint=input_fingerprint("another"),
                    safe_summary={"source_text": "raw source"})
    engine.dispose()


def test_task_store_does_not_persist_error_message_and_budget_reservations_survive():
    engine, sessions, store, ids = make_store()
    run_id, project_id, source_id, schedule_id = ids
    root = envelope(AgentRole.ROOT, run=run_id, project=project_id, source=source_id, schedule=schedule_id)
    store.begin(root, input_fingerprint=input_fingerprint("safe"))
    failure = TaskResult(
        task_id=root.task_id, parent_task_id=None, run_id=run_id, agent_role=AgentRole.ROOT,
        project_id=project_id, source_id=source_id, schedule_version_id=schedule_id,
        outcome=TaskOutcome.FAILED, error={"code": "PROVIDER_ERROR", "safe_message": "SECRET SOURCE EXCERPT"},
    )
    failed = store.finish(root, failure)
    assert failed.error_code == "PROVIDER_ERROR"
    with sessions() as session:
        row = session.get(AgentRun, run_id)
        assert "SECRET SOURCE EXCERPT" not in str(row.counters)
    assert store.reserve_budget("model_calls", limits=BudgetLimits(model_calls=2)) == 1
    restored = store.budget_snapshot(limits=BudgetLimits(model_calls=2))
    assert restored["used"]["model_calls"] == 1
    with pytest.raises(BudgetExceeded):
        store.reserve_budget("model_calls", 2, limits=BudgetLimits(model_calls=2))
    engine.dispose()


def test_task_store_rejects_late_child_after_parent_finishes():
    engine, sessions, store, ids = make_store()
    run_id, project_id, source_id, schedule_id = ids
    root = envelope(AgentRole.ROOT, run=run_id, project=project_id, source=source_id, schedule=schedule_id)
    store.begin(root, input_fingerprint=input_fingerprint("root"))
    root_result = TaskResult(
        task_id=root.task_id, parent_task_id=None, run_id=run_id, agent_role=AgentRole.ROOT,
        project_id=project_id, source_id=source_id, schedule_version_id=schedule_id,
        outcome=TaskOutcome.COMPLETED,
    )
    store.finish(root, root_result)

    late_child = envelope(AgentRole.ANALYSIS, parent=root.task_id, run=run_id, project=project_id,
                          source=source_id, schedule=schedule_id)
    with pytest.raises(TaskStoreError, match="parent task is not active"):
        store.begin(late_child, input_fingerprint=input_fingerprint("late"))
    engine.dispose()


def test_task_store_rejects_forged_child_result_and_conflicting_duplicate_finish():
    engine, sessions, store, ids = make_store()
    run_id, project_id, source_id, schedule_id = ids
    root = envelope(AgentRole.ROOT, run=run_id, project=project_id, source=source_id, schedule=schedule_id)
    store.begin(root, input_fingerprint=input_fingerprint("root"))
    child = envelope(AgentRole.ANALYSIS, parent=root.task_id, run=run_id, project=project_id,
                     source=source_id, schedule=schedule_id)
    store.begin(child, input_fingerprint=input_fingerprint("child"))
    good = TaskResult(
        task_id=child.task_id, parent_task_id=root.task_id, run_id=run_id,
        agent_role=AgentRole.ANALYSIS, project_id=project_id, source_id=source_id,
        schedule_version_id=schedule_id, outcome=TaskOutcome.COMPLETED,
        output_references=["observations:good"],
    )
    forged = good.model_copy(update={"project_id": uuid4()})
    with pytest.raises(ValueError, match="identity or pinned scope"):
        store.finish(child, forged)
    with sessions() as session:
        row = session.get(AgentTask, child.task_id)
        assert row.status == "running"
        assert row.output_references == []
    used_before_retry = store.reserve_budget("model_calls")
    assert used_before_retry == 1

    store.finish(child, good)
    with pytest.raises(TaskStoreError, match="different result"):
        store.finish(child, good.model_copy(update={"output_references": ["observations:forged"]}))
    assert store.budget_snapshot()["used"]["model_calls"] == used_before_retry
    engine.dispose()
