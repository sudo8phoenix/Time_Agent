from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import delete, func, select, text

import app.agent.runtime as runtime_module
from app.agent.runtime import process_job_with_graph
from app.db.models import (
    Activity,
    AgentRun,
    AgentStep,
    AgentToolCall,
    Fragment,
    Job,
    Observation,
    ProgressEvent,
    Project,
    Proposal,
    Report,
    ScheduleVersion,
)
from app.db.session import session_factory
from app.jobs.service import claim_job, heartbeat, retry_job
from app.jobs.worker import WorkerShutdown
from app.llm.ollama import LLMResult
from app.agent.tools import AgentToolError
from ops.prune_agent_checkpoints import prune


def _utcnow():
    return datetime.now(timezone.utc)


class RuntimeFixture:
    def __init__(self):
        self.token = uuid4().hex
        self.calls: list[str] = []
        with session_factory.begin() as db:
            project = Project(name=f"agent-runtime-{uuid4().hex}")
            db.add(project)
            db.flush()
            schedule = ScheduleVersion(
                project_id=project.id,
                version_number=1,
                content_sha256=uuid4().hex,
                state="active",
            )
            db.add(schedule)
            db.flush()
            project.active_schedule_version_id = schedule.id
            report = Report(
                project_id=project.id,
                content_hash=uuid4().hex,
                report_date=date(2026, 9, 24),
                report_date_evidence="header",
            )
            db.add(report)
            db.flush()
            fragment = Fragment(
                report_id=report.id,
                ordinal=1,
                locator="paragraph:1",
                original_text="Installed 2 m of cable.",
                normalised_text="Installed 2 m of cable.",
            )
            activity = Activity(
                schedule_version_id=schedule.id,
                external_id="A-1",
                name="Cable installation",
                wbs="1",
                discipline="electrical",
                work_type="cable_laying",
                is_leaf=True,
                measurement_basis="quantity_ratio",
                unit="m",
            )
            job = Job(
                project_id=project.id,
                report_id=report.id,
                schedule_version_id=schedule.id,
                state="running",
                stage="parse",
                attempts=1,
                lease_token=self.token,
                lease_expires_at=_utcnow() + timedelta(minutes=5),
                heartbeat_at=_utcnow(),
            )
            db.add_all([fragment, activity, job])
            db.flush()
            self.project_id = project.id
            self.schedule_id = schedule.id
            self.report_id = report.id
            self.fragment_id = fragment.id
            self.activity_id = activity.id
            self.job_id = job.id

    def model(self, **kwargs):
        is_selection = "candidate_id" in kwargs["schema"].get("properties", {})
        is_schedule = "candidate_ids" in kwargs["schema"].get("properties", {})
        self.calls.append("selection" if is_selection else "schedule" if is_schedule else "extraction")
        if is_schedule:
            value = {"candidate_ids": [str(self.activity_id)]}
        elif is_selection:
            value = {
                "candidate_id": str(self.activity_id),
                "mapping_state": "suggested",
                "evidence_fragment_ids": [str(self.fragment_id)],
                "reason_codes": ["DIRECT_MATCH"],
                "explanation": "Supported by the supplied evidence.",
                "missing_information": [],
            }
        else:
            value = {"observations": [{
                "discipline": "electrical",
                "work_type": "cable_laying",
                "event_type": "actual_progress",
                "observed_status": "in_progress",
                "area": None,
                "asset_tags": [],
                "explicit_activity_id": None,
                "work_date": "2026-09-24",
                "date_basis": "report_context",
                "quantity": "2",
                "quantity_kind": "delta",
                "unit": "m",
                "raw_unit": None,
                "reported_percent": None,
                "actual_start": None,
                "actual_finish": None,
                "blocker": None,
                "summary": "Installed 2 m of cable.",
                "evidence": [{
                    "fields": ["quantity"],
                    "fragment_id": str(self.fragment_id),
                    "quote": "2 m of cable",
                }],
                "warnings": [],
            }]}
        return LLMResult(
            value=value,
            model="fixture-model",
            model_digest="fixture-digest",
            runtime="fixture-runtime",
            elapsed_ms=1,
            settings_hash="a" * 64,
            prompt_hash=("b" if is_selection else "c") * 64,
        )

    def run(
        self, *, token=None, should_stop=None, checkpointer=None, heartbeat_callback=None
    ):
        with session_factory() as db:
            return process_job_with_graph(
                db,
                db.get(Job, self.job_id),
                token=token or self.token,
                session_factory=session_factory,
                database_url=(
                    "postgresql+psycopg://progress:progress@127.0.0.1:5432/progress_test"
                ),
                should_stop=should_stop,
                heartbeat_callback=heartbeat_callback,
                model_callable=self.model,
                checkpointer=checkpointer,
            )

    def cleanup(self):
        with session_factory.begin() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.job_id == self.job_id))
            if run is not None:
                for table in ("checkpoint_writes", "checkpoints", "checkpoint_blobs"):
                    db.execute(text(f"DELETE FROM {table} WHERE thread_id = :thread_id"), {
                        "thread_id": run.thread_id
                    })
            project = db.get(Project, self.project_id)
            if project is not None:
                project.active_schedule_version_id = None
                db.flush()
                db.execute(delete(Project).where(Project.id == self.project_id))


@pytest.fixture
def runtime_fixture():
    fixture = RuntimeFixture()
    try:
        yield fixture
    finally:
        fixture.cleanup()


def _stop_on_check(target: int):
    calls = {"value": 0}

    def stop():
        calls["value"] += 1
        return calls["value"] >= target

    return stop


def test_postgres_graph_happy_path_has_sanitized_trace(runtime_fixture):
    result = runtime_fixture.run()
    assert result["state"] == "ready_for_review"
    assert result["extracted_count"] == result["proposal_count"] == 1
    with session_factory() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.job_id == runtime_fixture.job_id))
        steps = list(db.scalars(select(AgentStep).where(
            AgentStep.run_id == run.id
        ).order_by(AgentStep.ordinal)))
        tools = list(db.scalars(select(AgentToolCall).join(
            AgentStep, AgentToolCall.step_id == AgentStep.id
        ).where(AgentStep.run_id == run.id)))
        assert run.state == "ready_for_review"
        assert [step.node for step in steps] == [
            "load_context", "extract", "validate_extraction", "retrieve",
            "select", "validate_selection", "persist", "finalize",
        ]
        assert all(step.state == "succeeded" for step in steps)
        assert {call.tool_name for call in tools} == {
            "load_job_context", "extract_observations", "retrieve_candidates",
            "select_candidate", "validate_proposal_drafts", "persist_review_proposals",
        }
        serialized = json.dumps([
            run.model_metadata, run.prompt_metadata, run.config_metadata,
            *[step.sanitized_summary for step in steps],
            *[call.sanitized_input_summary for call in tools],
            *[call.sanitized_output_summary for call in tools],
        ])
        for secret in (
            runtime_fixture.token,
            "Installed 2 m of cable",
            "http://127.0.0.1",
            "Choose a schedule activity",
        ):
            assert secret not in serialized
        assert db.scalar(select(func.count()).select_from(ProgressEvent).join(
            Observation, ProgressEvent.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 0


@pytest.mark.parametrize(
    ("stop_check", "expected_additional_model_calls"),
    [(5, 2), (11, 0)],
    ids=["after-extraction", "after-selection"],
)
def test_postgres_restart_rehydrates_provenance_without_repeating_completed_model_stage(
    runtime_fixture, stop_check, expected_additional_model_calls
):
    with pytest.raises(WorkerShutdown):
        runtime_fixture.run(should_stop=_stop_on_check(stop_check))
    before = len(runtime_fixture.calls)
    result = runtime_fixture.run()
    assert result["state"] == "ready_for_review"
    assert len(runtime_fixture.calls) - before == expected_additional_model_calls
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun).where(
            AgentRun.job_id == runtime_fixture.job_id
        )) == 1
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 1


def test_expired_lease_is_replaced_and_new_owner_resumes(runtime_fixture):
    with pytest.raises(WorkerShutdown):
        runtime_fixture.run(should_stop=_stop_on_check(5))
    before = len(runtime_fixture.calls)
    with session_factory.begin() as db:
        job = db.get(Job, runtime_fixture.job_id)
        job.lease_expires_at = _utcnow() - timedelta(seconds=1)
    with session_factory.begin() as db:
        job, replacement = claim_job(db)
        assert job.id == runtime_fixture.job_id
    result = runtime_fixture.run(token=replacement)
    assert result["state"] == "ready_for_review"
    assert len(runtime_fixture.calls) - before == 2
    with session_factory() as db:
        job = db.get(Job, runtime_fixture.job_id)
        assert job.attempts == 2
        assert job.lease_token is None


def test_runtime_renews_heartbeat_at_node_boundaries(runtime_fixture):
    beats = []

    def beat(job, token):
        with session_factory.begin() as db:
            owned = heartbeat(db, job.id, token)
            if owned:
                beats.append(job.id)
            return owned

    result = runtime_fixture.run(heartbeat_callback=beat)
    assert result["state"] == "ready_for_review"
    assert len(beats) >= 2 * 8 + 1


def test_incompatible_framework_version_fails_same_run(runtime_fixture):
    with pytest.raises(WorkerShutdown):
        runtime_fixture.run(should_stop=_stop_on_check(5))
    with session_factory.begin() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.job_id == runtime_fixture.job_id))
        run.framework_version = "incompatible-version"
        original_run_id = run.id
    result = runtime_fixture.run()
    assert result["state"] == "failed"
    assert result["error_code"] == "AGENT_CHECKPOINT_INCOMPATIBLE"
    with session_factory() as db:
        runs = list(db.scalars(select(AgentRun).where(
            AgentRun.job_id == runtime_fixture.job_id
        )))
        assert [run.id for run in runs] == [original_run_id]


def test_schedule_change_before_persistence_marks_run_stale(runtime_fixture):
    original = runtime_fixture.model

    def changing_model(**kwargs):
        value = original(**kwargs)
        if runtime_fixture.calls == ["extraction"]:
            with session_factory.begin() as db:
                project = db.get(Project, runtime_fixture.project_id)
                newer = ScheduleVersion(
                    project_id=project.id,
                    version_number=2,
                    content_sha256=uuid4().hex,
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
        run = db.scalar(select(AgentRun).where(AgentRun.job_id == runtime_fixture.job_id))
        assert run.state == "stale"
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 0


def test_injected_persistence_failure_rolls_back_all_domain_rows(
    runtime_fixture, monkeypatch
):
    def fail_mid_transaction(session_factory_arg, token, state, *, idempotency_key):
        with session_factory_arg.begin() as db:
            db.add(Observation(
                job_id=UUID(state.job_id),
                fragment_id=UUID(state.fragment_ids[0]),
                ordinal=1,
                fields={"should": "rollback"},
                field_evidence={},
            ))
            db.flush()
            raise AgentToolError("AGENT_TOOL_FAILED", "Persistence failed safely.")

    monkeypatch.setattr(runtime_module, "_persistence_callback", fail_mid_transaction)
    result = runtime_fixture.run()
    assert result["state"] == "failed"
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 0
        assert db.scalar(select(func.count()).select_from(Proposal).join(
            Observation, Proposal.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 0


def test_checkpoint_failure_after_domain_commit_resumes_without_duplicates(runtime_fixture):
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
    failed = runtime_fixture.run(checkpointer=saver)
    assert failed["state"] == "failed"
    assert failed["error_code"] == "AGENT_CHECKPOINT_FAILED"
    with session_factory.begin() as db:
        job = db.get(Job, runtime_fixture.job_id)
        assert job.extracted_count == job.proposal_count == 1
        retry_job(db, job)
    with session_factory.begin() as db:
        job, replacement = claim_job(db)
        assert job.id == runtime_fixture.job_id
    resumed = runtime_fixture.run(token=replacement, checkpointer=saver)
    assert resumed["state"] == "ready_for_review", resumed
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 1
        assert db.scalar(select(func.count()).select_from(Proposal).join(
            Observation, Proposal.observation_id == Observation.id
        ).where(Observation.job_id == runtime_fixture.job_id)) == 1


def test_pruning_is_dry_run_by_default_and_exact(runtime_fixture):
    runtime_fixture.run()
    with session_factory.begin() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.job_id == runtime_fixture.job_id))
        run.completed_at = _utcnow() - timedelta(days=10)
        run.updated_at = run.completed_at
        run_id = str(run.id)
    preview = prune(age=timedelta(days=1), execute=False)
    assert preview["run_ids"] == [run_id]
    assert preview["checkpoint_rows"]["checkpoints"] > 0
    executed = prune(age=timedelta(days=1), execute=True)
    assert executed["run_ids"] == [run_id]
    assert executed["deleted_rows"] == preview["checkpoint_rows"]
    with session_factory() as db:
        assert db.get(AgentRun, UUID(run_id)) is not None
        assert db.scalar(select(func.count()).select_from(Observation).where(
            Observation.job_id == runtime_fixture.job_id
        )) == 1
        assert db.execute(text(
            "SELECT count(*) FROM checkpoints WHERE thread_id = :thread_id"
        ), {"thread_id": run_id}).scalar_one() == 0
