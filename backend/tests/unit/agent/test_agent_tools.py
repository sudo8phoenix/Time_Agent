from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import inspect
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.context import AgentRuntimeContext
from app.agent.state import create_initial_state
from app.agent.tools import AgentToolError, AgentTools, ReportMetadata
from app.db.base import Base
from app.db.models import Activity, Fragment, Job, Project, Report, ScheduleVersion
from app.llm.extract import ExtractionError
from app.matching.selection import SelectionValidationError
from app.schemas.matching import Candidate
from app.schemas.observation import Observation


def uid() -> uuid.UUID:
    return uuid.uuid4()


class Fixture:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.project_id, self.report_id, self.schedule_id, self.job_id = (uid() for _ in range(4))
        self.fragment_id, self.activity_id = uid(), uid()
        self.token = "lease-secret"
        with Session(self.engine) as db:
            project = Project(id=self.project_id, name="P", active_schedule_version_id=self.schedule_id)
            schedule = ScheduleVersion(id=self.schedule_id, project_id=self.project_id, version_number=1,
                                       content_sha256="a" * 64, state="active")
            report = Report(id=self.report_id, project_id=self.project_id, content_hash="b" * 64,
                            report_date=date(2026, 9, 1), report_date_evidence="header")
            job = Job(id=self.job_id, project_id=self.project_id, report_id=self.report_id,
                      schedule_version_id=self.schedule_id, state="running", lease_token=self.token,
                      lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=2))
            fragment = Fragment(id=self.fragment_id, report_id=self.report_id, ordinal=1,
                                locator="p1", original_text="Installed 2 m of cable.",
                                normalised_text="Installed 2 m of cable.")
            activity = Activity(id=self.activity_id, schedule_version_id=self.schedule_id, external_id="A-1",
                                name="Cable installation", wbs="1", discipline="electrical",
                                work_type="cable_laying", is_leaf=True, measurement_basis="quantity_ratio")
            db.add_all([project, schedule, report, job, fragment, activity])
            db.commit()
        self.observation = Observation.model_validate({
            "discipline": "electrical", "work_type": "cable_laying", "event_type": "actual_progress",
            "observed_status": "in_progress", "area": None, "asset_tags": [], "explicit_activity_id": None,
            "work_date": "2026-09-01", "date_basis": "report_context", "quantity": "2",
            "quantity_kind": "delta", "unit": "m", "raw_unit": None, "reported_percent": None,
            "actual_start": None, "actual_finish": None, "blocker": None, "summary": "Installed 2 m of cable.",
            "evidence": [{"fields": ["quantity"], "fragment_id": str(self.fragment_id), "quote": "2 m of cable"}],
            "warnings": [],
        })
        self.candidate = Candidate(candidate_id=self.activity_id, external_id="A-1", activity_name="Cable installation",
                                   area=None, work_type="cable_laying", is_leaf=True, retrieval_rank=1, retrieval_score=0.8)
        self.model_calls = 0
        def model(**kwargs):
            self.model_calls += 1
            if "schema" in kwargs and "properties" in kwargs["schema"] and "candidate_id" in kwargs["schema"]["properties"]:
                return {"candidate_id": str(self.activity_id), "mapping_state": "suggested",
                        "evidence_fragment_ids": [str(self.fragment_id)], "reason_codes": ["DIRECT_MATCH"],
                        "explanation": "Supported by evidence.", "missing_information": []}
            return {"observations": [self.observation.model_dump(mode="json")]}
        self.context = AgentRuntimeContext(
            session_factory=lambda: Session(self.engine), lease_token=self.token,
            model_callable=model, embedder=None, heartbeat_callback=lambda *args: True,
            shutdown_callback=lambda: False, clock=lambda: datetime.now(timezone.utc),
        )
        self.persist_calls = []

    def tools(self, **kwargs):
        persistence = kwargs.pop("persistence_callback", lambda state, **kw: (
            self.persist_calls.append((state, kw)) or {
                "extracted_count": len(state.observation_drafts),
                "proposal_count": len(state.selection_drafts), "already_persisted": False,
            }
        ))
        return AgentTools(self.context, persistence_callback=persistence, **kwargs)

    def load(self, tools):
        return tools.load_job_context(str(self.job_id))


def test_six_tool_happy_path_and_persistence_idempotency():
    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    extracted = tools.extract_observations(scope.fragment_ids, ReportMetadata(
        report_date=date(2026, 9, 1), report_date_trusted=True,
    ))
    assert extracted.observations == [fixture.observation]
    retrieved = tools.retrieve_candidates("obs-0001", fixture.observation, scope.schedule_version_id)
    assert len(retrieved.candidates) == 1
    assert str(retrieved.candidates[0].candidate_id) == str(fixture.activity_id)
    proposal = tools.select_candidate("obs-0001", fixture.observation, retrieved.candidates, scope.fragment_ids)
    assert str(proposal.candidate_id) == str(fixture.activity_id)
    state = create_initial_state(
        run_id=str(uid()), job_id=scope.job_id, project_id=scope.project_id,
        report_id=scope.report_id, schedule_version_id=scope.schedule_version_id,
        fragment_ids=scope.fragment_ids, activity_ids=scope.activity_ids,
        observation_drafts=extracted.observations,
        candidate_sets={"obs-0001": retrieved.candidates}, selection_drafts={"obs-0001": proposal},
        next_action="persist",
    )
    assert tools.validate_proposal_drafts(state).valid
    result = tools.persist_review_proposals(state)
    assert result.extracted_count == result.proposal_count == 1
    assert tools.persist_review_proposals(state) == result
    assert len(fixture.persist_calls) == 1
    assert fixture.persist_calls[0][1] == {"idempotency_key": state.run_id}


def test_scope_missing_lease_and_schedule_failures():
    fixture = Fixture()
    tools = fixture.tools()
    with pytest.raises(AgentToolError, match="loaded"):
        tools.retrieve_candidates("obs-0001", fixture.observation, str(fixture.schedule_id))
    with Session(fixture.engine) as db:
        job = db.get(Job, fixture.job_id)
        job.lease_token = "different"
        db.commit()
    with pytest.raises(AgentToolError) as exc:
        fixture.load(tools)
    assert exc.value.code == "JOB_LEASE_LOST"

    fixture2 = Fixture()
    tools2 = fixture2.tools()
    with Session(fixture2.engine) as db:
        project = db.get(Project, fixture2.project_id)
        project.active_schedule_version_id = uid()
        db.commit()
    with pytest.raises(AgentToolError) as exc:
        fixture2.load(tools2)
    assert exc.value.code == "SCHEDULE_VERSION_STALE"


def test_report_metadata_is_private_fresh_and_requires_loaded_scope():
    fixture = Fixture()
    tools = fixture.tools()
    with pytest.raises(AgentToolError) as exc:
        _ = tools.report_metadata
    assert exc.value.code == "AGENT_TOOL_FAILED"
    fixture.load(tools)
    first = tools.report_metadata
    assert first.report_date == date(2026, 9, 1)
    assert first.report_date_trusted is True
    first.report_date = date(2000, 1, 1)
    first.report_date_trusted = False
    second = tools.report_metadata
    assert second is not first
    assert second.report_date == date(2026, 9, 1)
    assert second.report_date_trusted is True


@pytest.mark.parametrize("mutation", ["expired", "wrong_report", "wrong_project", "wrong_schedule"])
def test_load_context_rejects_expired_lease_and_inconsistent_relations(mutation):
    fixture = Fixture()
    with Session(fixture.engine) as db:
        job = db.get(Job, fixture.job_id)
        if mutation == "expired":
            job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif mutation == "wrong_report":
            job.report_id = uid()
        elif mutation == "wrong_project":
            job.project_id = uid()
        else:
            job.schedule_version_id = uid()
        db.commit()
    with pytest.raises(AgentToolError):
        fixture.load(fixture.tools())


def test_empty_retrieval_skips_selection_model_and_embeddings_fallback():
    fixture = Fixture()
    tools = fixture.tools(retrieval_service=lambda *args, **kwargs: type("Result", (), {"candidates": []})())
    scope = fixture.load(tools)
    tools.extract_observations(scope.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    empty = tools.retrieve_candidates("obs-0001", fixture.observation, scope.schedule_version_id)
    before = fixture.model_calls
    proposal = tools.select_candidate("obs-0001", fixture.observation, empty.candidates, scope.fragment_ids)
    assert proposal.candidate_id is None
    assert fixture.model_calls == before

    fixture2 = Fixture()
    fixture2.context = AgentRuntimeContext(
        session_factory=fixture2.context.session_factory, lease_token=fixture2.token,
        model_callable=fixture2.context.model_callable,
        embedder=lambda _: (_ for _ in ()).throw(RuntimeError("secret")),
        heartbeat_callback=lambda *args: True, shutdown_callback=lambda: False,
        clock=lambda: datetime.now(timezone.utc),
    )
    tools2 = fixture2.tools()
    scope2 = fixture2.load(tools2)
    tools2.extract_observations(scope2.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    result = tools2.retrieve_candidates("obs-0001", fixture2.observation, scope2.schedule_version_id)
    assert result.candidates and result.warnings[0].code == "EMBEDDINGS_UNAVAILABLE"


def test_candidate_validation_budgets_and_bad_selection_rejected():
    fixture = Fixture()
    tools = fixture.tools(retrieval_service=lambda *args, **kwargs: [fixture.candidate] * 9)
    scope = fixture.load(tools)
    tools.extract_observations(scope.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    with pytest.raises(AgentToolError):
        tools.retrieve_candidates("obs-0001", fixture.observation, scope.schedule_version_id)

    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    tools.extract_observations(scope.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    candidates = tools.retrieve_candidates("obs-0001", fixture.observation, scope.schedule_version_id).candidates
    forged = candidates[0].model_copy(update={"activity_name": "forged"})
    with pytest.raises(AgentToolError) as exc:
        tools.select_candidate("obs-0001", fixture.observation, [forged], scope.fragment_ids)
    assert exc.value.stage is None and exc.value.retryable is False


@pytest.mark.parametrize("bad", ["duplicate", "unknown", "summary", "nan"])
def test_retrieval_rejects_duplicate_unknown_summary_and_nonfinite_candidates(bad):
    fixture = Fixture()
    row = fixture.candidate
    if bad == "duplicate":
        output = [row, row]
    elif bad == "unknown":
        output = [row.model_copy(update={"candidate_id": uid()})]
    elif bad == "summary":
        output = [row.model_copy(update={"is_leaf": False})]
    else:
        output = [row.model_copy(update={"retrieval_score": float("nan")})]
    tools = fixture.tools(retrieval_service=lambda *args, **kwargs: output)
    scope = fixture.load(tools)
    tools.extract_observations(scope.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    with pytest.raises(AgentToolError):
        tools.retrieve_candidates("obs-0001", fixture.observation, scope.schedule_version_id)


def test_retrieval_rejects_wrong_schedule_version():
    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    tools.extract_observations(scope.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    with pytest.raises(AgentToolError):
        tools.retrieve_candidates("obs-0001", fixture.observation, str(uid()))


def test_exact_fragments_metadata_model_failures_and_budgets():
    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    metadata = ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True)
    with pytest.raises(AgentToolError):
        tools.extract_observations([], metadata)
    with pytest.raises(AgentToolError):
        tools.extract_observations(scope.fragment_ids, ReportMetadata(report_date=None, report_date_trusted=False))
    tools.extract_observations(scope.fragment_ids, metadata)
    tools.extract_observations(scope.fragment_ids, metadata)
    with pytest.raises(AgentToolError) as exc:
        tools.extract_observations(scope.fragment_ids, metadata)
    assert exc.value.code == "AGENT_REPAIR_LIMIT"

    def malformed_extraction(*args, **kwargs):
        raise ExtractionError("private raw extraction details")
    broken = fixture.tools(extraction_service=malformed_extraction)
    broken.load_job_context(str(fixture.job_id))
    with pytest.raises(AgentToolError) as exc:
        broken.extract_observations(scope.fragment_ids, metadata)
    assert (exc.value.code, exc.value.stage, exc.value.retryable) == ("AGENT_TOOL_FAILED", "extraction", True)
    with pytest.raises(AttributeError):
        exc.value.retryable = False
    unknown = fixture.tools(extraction_service=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret")))
    unknown.load_job_context(str(fixture.job_id))
    with pytest.raises(AgentToolError) as exc:
        unknown.extract_observations(scope.fragment_ids, metadata)
    assert exc.value.stage is None and exc.value.retryable is False


def test_selection_budget_effect_and_scope_relationship_rechecked():
    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    tools.extract_observations(scope.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    candidates = tools.retrieve_candidates("obs-0001", fixture.observation, scope.schedule_version_id).candidates
    tools.select_candidate("obs-0001", fixture.observation, candidates, scope.fragment_ids)
    tools.select_candidate("obs-0001", fixture.observation, candidates, scope.fragment_ids)
    with pytest.raises(AgentToolError) as exc:
        tools.select_candidate("obs-0001", fixture.observation, candidates, scope.fragment_ids)
    assert exc.value.code == "AGENT_REPAIR_LIMIT"

    invalid = fixture.tools(selection_service=lambda *args, **kwargs: {
        "candidate_id": str(fixture.activity_id), "mapping_state": "suggested", "match_strength": "review",
        "evidence_fragment_ids": [str(fixture.fragment_id)], "reason_codes": [], "explanation": "x",
        "missing_information": [], "candidates": [fixture.candidate.model_dump(mode="json")],
        "review_state": "pending", "proposed_effects": {"quantity": "2"},
    })
    scope2 = invalid.load_job_context(str(fixture.job_id))
    invalid.extract_observations(scope2.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    cs = invalid.retrieve_candidates("obs-0001", fixture.observation, scope2.schedule_version_id).candidates
    with pytest.raises(AgentToolError):
        invalid.select_candidate("obs-0001", fixture.observation, cs, scope2.fragment_ids)

    malformed = fixture.tools(selection_service=lambda *args, **kwargs: {"nonsense": True})
    scope3 = malformed.load_job_context(str(fixture.job_id))
    malformed.extract_observations(scope3.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    cs3 = malformed.retrieve_candidates("obs-0001", fixture.observation, scope3.schedule_version_id).candidates
    with pytest.raises(AgentToolError):
        malformed.select_candidate("obs-0001", fixture.observation, cs3, scope3.fragment_ids)

    mismatch = fixture.tools(selection_service=lambda *args, **kwargs: {
        "candidate_id": str(fixture.activity_id), "mapping_state": "suggested", "match_strength": "review",
        "evidence_fragment_ids": [str(uid())], "reason_codes": [], "explanation": "x",
        "missing_information": [], "candidates": [], "review_state": "pending", "proposed_effects": {},
    })
    scope4 = mismatch.load_job_context(str(fixture.job_id))
    mismatch.extract_observations(scope4.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    cs4 = mismatch.retrieve_candidates("obs-0001", fixture.observation, scope4.schedule_version_id).candidates
    with pytest.raises(AgentToolError):
        mismatch.select_candidate("obs-0001", fixture.observation, cs4, scope4.fragment_ids)

    malformed_selection = fixture.tools(selection_service=lambda *args, **kwargs: {
        "not_a_proposal": "private output",
    })
    scope5 = malformed_selection.load_job_context(str(fixture.job_id))
    malformed_selection.extract_observations(scope5.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    cs5 = malformed_selection.retrieve_candidates("obs-0001", fixture.observation, scope5.schedule_version_id).candidates
    with pytest.raises(AgentToolError) as exc:
        malformed_selection.select_candidate("obs-0001", fixture.observation, cs5, scope5.fragment_ids)
    assert (exc.value.code, exc.value.stage, exc.value.retryable) == ("AGENT_TOOL_FAILED", "selection", True)

    known_selection_error = fixture.tools(selection_service=lambda *args, **kwargs: (_ for _ in ()).throw(SelectionValidationError("raw detail")))
    scope6 = known_selection_error.load_job_context(str(fixture.job_id))
    known_selection_error.extract_observations(scope6.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    cs6 = known_selection_error.retrieve_candidates("obs-0001", fixture.observation, scope6.schedule_version_id).candidates
    with pytest.raises(AgentToolError) as exc:
        known_selection_error.select_candidate("obs-0001", fixture.observation, cs6, scope6.fragment_ids)
    assert exc.value.stage == "selection" and exc.value.retryable is True

    unknown_selection = fixture.tools(selection_service=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret")))
    scope7 = unknown_selection.load_job_context(str(fixture.job_id))
    unknown_selection.extract_observations(scope7.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    cs7 = unknown_selection.retrieve_candidates("obs-0001", fixture.observation, scope7.schedule_version_id).candidates
    with pytest.raises(AgentToolError) as exc:
        unknown_selection.select_candidate("obs-0001", fixture.observation, cs7, scope7.fragment_ids)
    assert exc.value.stage is None and exc.value.retryable is False

    with Session(fixture.engine) as db:
        job = db.get(Job, fixture.job_id)
        job.report_id = uid()
        db.commit()
    with pytest.raises(AgentToolError):
        tools.persist_review_proposals(create_initial_state(
            run_id=str(uid()), job_id=scope.job_id, project_id=scope.project_id,
            report_id=scope.report_id, schedule_version_id=scope.schedule_version_id,
            fragment_ids=scope.fragment_ids, activity_ids=scope.activity_ids,
        ))


def test_validation_rejects_mutated_candidates_proposal_expansion_and_unscoped_evidence():
    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    extracted = tools.extract_observations(scope.fragment_ids, ReportMetadata(report_date=date(2026, 9, 1), report_date_trusted=True))
    candidates = tools.retrieve_candidates("obs-0001", extracted.observations[0], scope.schedule_version_id).candidates
    proposal = tools.select_candidate("obs-0001", extracted.observations[0], candidates, scope.fragment_ids)

    def state_for(observation, candidate_set, selected):
        return create_initial_state(run_id=str(uid()), job_id=scope.job_id, project_id=scope.project_id,
            report_id=scope.report_id, schedule_version_id=scope.schedule_version_id,
            fragment_ids=scope.fragment_ids, activity_ids=scope.activity_ids,
            observation_drafts=[observation], candidate_sets={"obs-0001": candidate_set},
            selection_drafts={"obs-0001": selected})

    altered = candidates[0].model_copy(update={"activity_name": "changed"})
    provenance = tools.validate_proposal_drafts(state_for(extracted.observations[0], [altered], proposal))
    assert not provenance.valid
    assert provenance.errors[0].stage == "retrieval" and provenance.errors[0].retryable is False
    expanded = proposal.model_copy(update={"candidates": [altered]})
    repairable = tools.validate_proposal_drafts(state_for(extracted.observations[0], candidates, expanded))
    assert not repairable.valid
    assert repairable.errors[0].stage == "selection" and repairable.errors[0].retryable is True
    bad_observation = extracted.observations[0].model_copy(update={
        "evidence": [extracted.observations[0].evidence[0].model_copy(update={"fragment_id": str(uid())})],
    })
    evidence = tools.validate_proposal_drafts(state_for(bad_observation, candidates, proposal))
    assert not evidence.valid
    assert evidence.errors[0].stage == "extraction" and evidence.errors[0].retryable is False
    identity = create_initial_state(**{
        **state_for(extracted.observations[0], candidates, proposal).model_dump(mode="python"),
        "project_id": str(uid()),
    })
    identity_result = tools.validate_proposal_drafts(identity)
    assert not identity_result.valid
    assert identity_result.errors[0].stage == "state" and identity_result.errors[0].retryable is False


def test_persistence_failure_invalid_result_and_no_retry():
    fixture = Fixture()
    tools = fixture.tools(persistence_callback=lambda *args, **kwargs: {"extracted_count": -1})
    scope = fixture.load(tools)
    empty_state = create_initial_state(
        run_id=str(uid()), job_id=scope.job_id, project_id=scope.project_id, report_id=scope.report_id,
        schedule_version_id=scope.schedule_version_id, fragment_ids=scope.fragment_ids, activity_ids=scope.activity_ids,
    )
    with pytest.raises(AgentToolError):
        tools.persist_review_proposals(empty_state)

    calls = []
    def broken(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("secret body")
    tools2 = fixture.tools(persistence_callback=broken)
    scope2 = tools2.load_job_context(str(fixture.job_id))
    state2 = create_initial_state(run_id=str(uid()), job_id=scope2.job_id, project_id=scope2.project_id,
                                  report_id=scope2.report_id, schedule_version_id=scope2.schedule_version_id,
                                  fragment_ids=scope2.fragment_ids, activity_ids=scope2.activity_ids)
    for _ in range(2):
        with pytest.raises(AgentToolError):
            tools2.persist_review_proposals(state2)
    assert calls == [1]

    partial = fixture.tools(persistence_callback=lambda *args, **kwargs: {
        "extracted_count": 1, "proposal_count": 0, "already_persisted": False,
    })
    scope3 = partial.load_job_context(str(fixture.job_id))
    state3 = create_initial_state(run_id=str(uid()), job_id=scope3.job_id, project_id=scope3.project_id,
                                  report_id=scope3.report_id, schedule_version_id=scope3.schedule_version_id,
                                  fragment_ids=scope3.fragment_ids, activity_ids=scope3.activity_ids)
    with pytest.raises(AgentToolError):
        partial.persist_review_proposals(state3)


def test_public_signature_forbidden_names_and_no_approval_progress_imports():
    from app.agent import tools as module

    forbidden = {"sql", "path", "url", "endpoint", "token", "prompt", "model", "command", "code", "python", "shell"}
    expected = {
        "load_job_context": ["job_id"],
        "extract_observations": ["fragment_ids", "report_metadata"],
        "retrieve_candidates": ["observation_key", "observation", "schedule_version_id"],
        "select_candidate": ["observation_key", "observation", "candidates", "fragment_ids"],
        "validate_proposal_drafts": ["state"], "persist_review_proposals": ["state"],
    }
    for name, params in expected.items():
        signature = inspect.signature(getattr(AgentTools, name))
        assert list(signature.parameters)[1:] == params
        assert not any(any(word in parameter.lower() for word in forbidden) for parameter in params)
    source = inspect.getsource(module)
    assert "app.progress" not in source and "app.api" not in source
    assert "tool_registry" not in source and "dispatcher" not in source
