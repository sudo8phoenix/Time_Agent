"""Fixture-only parity checks for quantity-free lifecycle extraction and review.

These deterministic injected services exercise the persistence and approval
paths. They do not measure live model accuracy.
"""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.endpoints.review import ApprovalRequest, approve
from app.db.models import (
    Activity,
    ActivityState,
    AgentRun,
    AgentStep,
    Fragment,
    Job,
    Project,
    ProjectMembership,
    Observation,
    ProgressEvent,
    Proposal,
    Report,
    ScheduleVersion,
    User,
)
from app.db.session import engine
from app.jobs.pipeline import process_job
from app.llm.extract import ExtractionMetadata, ExtractionResult
from app.schemas.events import Endpoint, LifecycleEffect, LifecycleKind, LifecycleScope
from app.schemas.matching import Candidate
from app.schemas.observation import Observation as Extracted


@pytest.fixture
def transaction_factory():
    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield factory
    finally:
        outer.rollback()
        connection.close()


def _candidate(activity):
    return Candidate(
        candidate_id=activity.id,
        external_id=activity.external_id,
        activity_name=activity.name,
        area=activity.area,
        work_type=activity.work_type,
        is_leaf=True,
        asset_tags=[],
        wbs=activity.wbs,
        discipline=activity.discipline,
        aliases=None,
        # Keep fixture fields identical across ORM-backed legacy and
        # graph-backed SimpleNamespace candidates.
        measurement_basis="unsupported",
        planned_quantity=None,
        unit=None,
        planned_start=None,
        planned_finish=None,
        retrieval_rank=1,
        retrieval_score=1.0,
    ).model_dump(mode="json")


def _services(activity_id, precision):
    """Build identical injected extraction, retrieval and selection fixtures."""
    def extraction(inputs, _model_call=None, **_kwargs):
        observations = []
        for index, item in enumerate(inputs):
            is_start = index == 0
            kind = LifecycleKind.actual_start if is_start else LifecycleKind.actual_finish
            day = date(2026, 9, 1) if is_start else date(2026, 9, 3)
            local_time = (time(8, 15) if is_start else time(17, 45)) if precision == "minute" else None
            endpoint = Endpoint(
                local_date=day,
                local_time=local_time,
                precision=precision,
                timezone="Asia/Kolkata",
                basis="explicit",
                raw_expression=item.text,
            )
            evidence = {
                "fields": [kind.value],
                "fragment_id": item.fragment_id,
                "quote": item.text,
            }
            effect = LifecycleEffect(
                kind=kind,
                scope=LifecycleScope.whole_activity,
                endpoint=endpoint,
                evidence=[evidence],
            )
            observations.append(Extracted.model_validate({
                "discipline": "piping",
                "work_type": "pipe_spool_erection",
                "event_type": kind.value,
                "observed_status": "in_progress" if is_start else "completed",
                "area": "A",
                "asset_tags": [],
                "explicit_activity_id": None,
                "work_date": day.isoformat(),
                "date_basis": "explicit",
                "quantity": None,
                "quantity_kind": "none",
                "unit": None,
                "raw_unit": None,
                "reported_percent": None,
                "actual_start": day.isoformat() if is_start else None,
                "actual_finish": None if is_start else day.isoformat(),
                "blocker": None,
                "summary": item.text,
                "evidence": [evidence],
                "warnings": [],
                "lifecycle_effects": [effect.model_dump(mode="json")],
            }))
        return [ExtractionResult(
            observations=tuple(observations),
            metadata=ExtractionMetadata(
                prompt_version="fixture-lifecycle-extraction-v1",
                prompt_hash="a" * 64,
                settings_hash="b" * 64,
                model="fixture-model",
                model_digest="fixture-digest",
                runtime="fixture",
                batch_id="fixture-batch",
            ),
        )]

    def retrieval(_observation, _schedule_version_id, activities):
        activity = next(item for item in activities if str(item.id) == str(activity_id))
        return [Candidate.model_validate(_candidate(activity))]

    def selection(observation, candidates, _fragments, **_kwargs):
        chosen = candidates[0]
        chosen_id = str(getattr(chosen, "candidate_id", getattr(chosen, "id", "")))
        candidate = chosen.model_dump(mode="json") if hasattr(chosen, "model_dump") else _candidate(chosen)
        return {
            "candidate_id": chosen_id,
            "mapping_state": "suggested",
            "match_strength": "review",
            "evidence_fragment_ids": [item.fragment_id for item in observation.evidence],
            "reason_codes": ["FIXTURE_LIFECYCLE_MATCH"],
            "explanation": "Deterministic fixture links the dated source to the schedule activity.",
            "missing_information": [],
            "candidates": [candidate],
            "review_state": "pending",
            "proposed_effects": {},
        }

    return extraction, retrieval, selection


def _first_difference(left, right, path="root"):
    if type(left) is not type(right):
        return path, left, right
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return f"{path}.keys", sorted(left.keys()), sorted(right.keys())
        for key in left:
            difference = _first_difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}.length", len(left), len(right)
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            difference = _first_difference(left_item, right_item, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if isinstance(left, tuple):
        if len(left) != len(right):
            return f"{path}.length", len(left), len(right)
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            difference = _first_difference(left_item, right_item, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if left != right:
        return path, left, right
    return None


def _normalize_ids(value, aliases):
    if isinstance(value, dict):
        return {key: _normalize_ids(item, aliases) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_ids(item, aliases) for item in value]
    if isinstance(value, str):
        return aliases.get(value, value)
    return value


def _case(factory, *, mode, precision):
    token = uuid4().hex
    project = Project(name=f"lifecycle-parity-{mode}-{precision}-{uuid4().hex}", timezone="UTC")
    with factory.begin() as db:
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
        activity = Activity(
            schedule_version_id=schedule.id,
            external_id="PIPE-A-1",
            name="Install pipe spools",
            wbs="1.1",
            discipline="piping",
            work_type="pipe_spool_erection",
            area="A",
            is_leaf=True,
            measurement_basis="unsupported",
        )
        report = Report(project_id=project.id, content_hash=uuid4().hex)
        db.add_all([activity, report])
        db.flush()
        start_text = "Crew started pipe installation on 2026-09-01."
        finish_text = "Crew completed pipe installation on 2026-09-03."
        if precision == "minute":
            start_text = "Crew started pipe installation at 08:15 on 2026-09-01."
            finish_text = "Crew completed pipe installation at 17:45 on 2026-09-03."
        fragments = [
            Fragment(report_id=report.id, ordinal=1, locator="paragraph:1", original_text=start_text, normalised_text=start_text),
            Fragment(report_id=report.id, ordinal=2, locator="paragraph:2", original_text=finish_text, normalised_text=finish_text),
        ]
        job = Job(
            project_id=project.id,
            report_id=report.id,
            schedule_version_id=schedule.id,
            state="running",
            stage="parse",
            attempts=1,
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            heartbeat_at=datetime.now(timezone.utc),
        )
        reviewer = User(username=f"lifecycle-parity-{uuid4().hex}", password_hash="unused", role="reviewer")
        db.add_all([*fragments, job, reviewer])
        db.flush()
        db.add(ProjectMembership(project_id=project.id, user_id=reviewer.id))
        db.flush()
        ids = (
            project.id,
            schedule.id,
            activity.id,
            report.id,
            job.id,
            reviewer.id,
            tuple(fragment.id for fragment in fragments),
        )

    extraction, retrieval, selection = _services(ids[2], precision)
    if mode == "legacy":
        with factory() as db:
            job = db.get(Job, ids[4])
            result = process_job(
                db,
                job,
                extraction_call=extraction,
                retrieve_call=retrieval,
                selection_call=selection,
            )
            db.commit()
    else:
        from langgraph.checkpoint.memory import MemorySaver
        from app.agent.runtime import process_job_with_graph

        with factory() as db:
            job = db.get(Job, ids[4])
            result = process_job_with_graph(
                db,
                job,
                token=token,
                session_factory=factory,
                model_callable=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("fixture services must not call a model")),
                extraction_service=extraction,
                retrieval_service=retrieval,
                selection_service=selection,
                checkpointer=MemorySaver(),
            )
    graph_run = None
    graph_steps = []
    if mode == "graph":
        with factory() as db:
            graph_run = db.query(AgentRun).filter(AgentRun.job_id == ids[4]).one()
            graph_steps = list(db.query(AgentStep).filter(
                AgentStep.run_id == graph_run.id
            ).order_by(AgentStep.ordinal))
        step_details = [
            {
                "node": step.node,
                "state": step.state,
                "error_code": step.error_code,
                "error_message": step.error_message,
                "summary": step.sanitized_summary,
            }
            for step in graph_steps
        ]
        diagnostic = (
            f"graph result={result}; run state={graph_run.state}; "
            f"error_code={graph_run.error_code}; error_message={graph_run.error_message}; "
            f"steps={step_details}"
        )
    else:
        diagnostic = f"legacy result={result}"
    assert result["state"] == "ready_for_review", diagnostic
    assert result["extracted_count"] == result["proposal_count"] == 2, diagnostic
    if mode == "graph":
        expected_steps = [
            "load_context", "extract", "validate_extraction", "retrieve",
            "select", "validate_selection", "persist", "finalize",
        ]
        assert [step.node for step in graph_steps] == expected_steps, diagnostic
        assert graph_run.state == "ready_for_review", diagnostic
        assert graph_run.error_code is None and graph_run.error_message is None, diagnostic

    with factory() as db:
        # Persisted observation ordinals retain source order; use that instead
        # of UUID ordering to make start/finish approval order deterministic.
        proposals = list(db.query(Proposal).join(
            Observation, Observation.id == Proposal.observation_id
        ).filter(Proposal.project_id == ids[0]).order_by(Observation.ordinal))
        assert len(proposals) == 2
        normalized = []
        id_aliases = {
            str(ids[0]): "<project>",
            str(ids[1]): "<schedule>",
            str(ids[2]): "<activity>",
            str(ids[3]): "<report>",
            str(ids[4]): "<job>",
            str(ids[5]): "<reviewer>",
            str(ids[6][0]): "<fragment:1>",
            str(ids[6][1]): "<fragment:2>",
        }
        for index, proposal in enumerate(proposals, 1):
            observation = db.get(Observation, proposal.observation_id)
            id_aliases[str(observation.id)] = f"<observation:{index}>"
            id_aliases[str(proposal.id)] = f"<proposal:{index}>"
            provenance = observation.field_evidence["provenance"]
            assert observation.fields["quantity"] is None
            assert observation.fields["lifecycle_effects"][0]["endpoint"]["precision"] == precision
            assert provenance["version"] == "proposal-provenance-v1"
            assert provenance["validation"]["status"] == "requires_authorized_review"
            assert provenance["evidence"] == observation.fields["evidence"]
            assert provenance["original_fields"] == observation.fields
            assert provenance["original_selection"]["candidate_id"] == str(ids[2])
            assert proposal.proposed_effects["event_type"] in {"actual_start", "actual_finish"}
            assert "quantity" not in proposal.proposed_effects
            normalized.append({
                "effects": proposal.proposed_effects,
                "original_fields": provenance["original_fields"],
                "original_selection": provenance["original_selection"],
                "evidence": provenance["evidence"],
                "confidence": {
                    stage: {key: value for key, value in details.items() if key != "version"}
                    for stage, details in provenance["confidence"].items()
                },
            })
        proposal_ids = [item.id for item in proposals]
        for index, proposal_id in enumerate(proposal_ids):
            result = approve(
                proposal_id,
                ApprovalRequest(
                    expected_proposal_revision=1,
                    expected_activity_revision=index,
                    idempotency_key=f"{mode}-{precision}-{index}-{uuid4().hex}",
                ),
                db.get(User, ids[5]),
                db,
            )
            db.commit()
            assert result["state_revision"] == index + 1
        state = db.get(ActivityState, ids[2])
        events = list(db.query(ProgressEvent).filter(
            ProgressEvent.activity_id == ids[2]
        ).order_by(ProgressEvent.effective_date, ProgressEvent.effect_kind))
        assert len(events) == 2
        final_state = {
            "actual_start": state.actual_start.isoformat(),
            "actual_start_time": state.actual_start_time.isoformat() if state.actual_start_time else None,
            "actual_start_precision": state.actual_start_precision,
            "actual_finish": state.actual_finish.isoformat(),
            "actual_finish_time": state.actual_finish_time.isoformat() if state.actual_finish_time else None,
            "actual_finish_precision": state.actual_finish_precision,
            "lifecycle_status": state.lifecycle_status,
            "completed_quantity": str(state.completed_quantity),
            "physical_percent": str(state.physical_percent) if state.physical_percent is not None else None,
        }
        assert all(proposal.review_state == "approved" for proposal in proposals)
        assert all(event.approved_values["event_type"] in {"actual_start", "actual_finish"} for event in events)
    return _normalize_ids(normalized, id_aliases), final_state


@pytest.mark.parametrize("precision", ["date", "minute"])
def test_legacy_and_graph_lifecycle_paths_have_equal_reviewed_effects(transaction_factory, precision):
    legacy = _case(transaction_factory, mode="legacy", precision=precision)
    graph = _case(transaction_factory, mode="graph", precision=precision)

    difference = _first_difference(legacy, graph)
    assert difference is None, f"legacy/graph parity differs at {difference}"
    effects, final = legacy
    assert [item["effects"]["event_type"] for item in effects] == ["actual_start", "actual_finish"]
    assert final == {
        "actual_start": "2026-09-01",
        "actual_start_time": "08:15:00" if precision == "minute" else None,
        "actual_start_precision": precision,
        "actual_finish": "2026-09-03",
        "actual_finish_time": "17:45:00" if precision == "minute" else None,
        "actual_finish_precision": precision,
        "lifecycle_status": "completed",
        "completed_quantity": "0.0000",
        "physical_percent": None,
    }
