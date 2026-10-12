"""Golden acceptance for graph-produced proposals with deterministic stage outputs."""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.models import Activity, AgentRun, Fragment, Job, Observation, ProgressEvent, Proposal
from app.db.session import session_factory
from app.agent.runtime import process_job_with_graph
from app.llm.extract import ExtractionMetadata, ExtractionResult
from app.schemas.matching import Candidate, Proposal as Selection
from app.schemas.observation import Observation as ObservationSchema
from app.settings import get_settings
from test_agent_runtime import RuntimeFixture


def _candidate(fixture):
    with session_factory() as db:
        activity = db.get(Activity, fixture.activity_id)
        return Candidate.model_validate({
            "candidate_id": str(activity.id), "external_id": activity.external_id,
            "activity_name": activity.name, "area": activity.area,
            "work_type": activity.work_type, "is_leaf": activity.is_leaf,
            "asset_tags": [], "wbs": activity.wbs, "discipline": activity.discipline,
            "aliases": activity.aliases, "measurement_basis": activity.measurement_basis,
            "planned_quantity": None, "unit": activity.unit, "planned_start": None,
            "planned_finish": None, "retrieval_rank": None, "retrieval_score": None,
        })


def _run(fixture, *, observations=None, mode="chosen", candidate_list=None):
    candidate = _candidate(fixture)
    candidates = candidate_list if candidate_list is not None else [candidate]
    if observations is None:
        observations = [fixture.lifecycle_observation] if fixture.lifecycle else [
            ObservationSchema.model_validate({
                "discipline": "electrical", "work_type": "cable_laying",
                "event_type": "actual_progress", "observed_status": "in_progress",
                "area": None, "asset_tags": [], "explicit_activity_id": None,
                "work_date": "2026-09-24", "date_basis": "report_context",
                "quantity": "2", "quantity_kind": "delta", "unit": "m",
                "raw_unit": None, "reported_percent": None, "actual_start": None,
                "actual_finish": None, "blocker": None,
                "summary": "Installed 2 m of cable.",
                "evidence": [{"fields": ["quantity"], "fragment_id": str(fixture.fragment_id),
                              "quote": "2 m of cable"}], "warnings": [],
            })
        ]
    metadata = ExtractionMetadata(
        prompt_version="fixture-extraction-v1", prompt_hash="c" * 64,
        settings_hash="a" * 64, model="fixture-model", model_digest="fixture-digest",
        runtime="fixture-runtime", batch_id="fixture-batch",
    )

    def extraction(*_args, **_kwargs):
        return [ExtractionResult(tuple(observations), metadata)]

    def retrieval(*_args, **_kwargs):
        return candidates

    def selection(observation, ranked, *_args, **_kwargs):
        chosen = mode == "chosen"
        mapping = "suggested" if chosen else mode
        return Selection(
            candidate_id=candidate.candidate_id if chosen else None,
            mapping_state=mapping, match_strength="review" if chosen else "unresolved",
            evidence_fragment_ids=[str(fixture.fragment_id)],
            reason_codes=["DIRECT_MATCH"] if chosen else [],
            explanation="Supported by the supplied evidence." if chosen
                        else "No supported schedule candidate.",
            missing_information=[], candidates=list(ranked), review_state="pending",
            proposed_effects={},
        )

    with session_factory() as db:
        return process_job_with_graph(
            db, db.get(Job, fixture.job_id), token=fixture.token,
            session_factory=session_factory, database_url=get_settings().database_url,
            model_callable=fixture.model, extraction_service=extraction,
            retrieval_service=retrieval, selection_service=selection,
        )


def _persisted(fixture):
    with session_factory() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.job_id == fixture.job_id))
        rows = list(db.scalars(select(Observation).where(
            Observation.job_id == fixture.job_id
        ).order_by(Observation.ordinal)))
        proposals = [db.scalar(select(Proposal).where(Proposal.observation_id == row.id))
                     for row in rows]
        return run, rows, proposals


def test_graph_quantity_proposal_persists_candidate_order_effects_and_provenance():
    fixture = RuntimeFixture()
    try:
        candidate = _candidate(fixture)
        result = _run(fixture, candidate_list=[candidate])
        assert result["state"] == "ready_for_review"
        assert result["extracted_count"] == result["proposal_count"] == 1
        run, rows, proposals = _persisted(fixture)
        assert run.state == "ready_for_review"
        assert len(rows) == len(proposals) == 1
        proposal = proposals[0]
        assert str(proposal.chosen_activity_id) == candidate.candidate_id
        assert proposal.mapping_state == "suggested"
        assert [item["candidate_id"] for item in proposal.candidates] == [candidate.candidate_id]
        assert proposal.review_state == "pending"
        assert proposal.warnings == []
        assert proposal.proposed_effects["quantity"] == "2"
        assert rows[0].fields["quantity"] == "2"
        provenance = rows[0].field_evidence["provenance"]
        assert provenance["version"]
        assert provenance["confidence"]
        assert provenance["validation"]
        assert provenance["model_metadata"]
        assert provenance["original_fields"]["quantity"] == "2"
        assert provenance["original_selection"]["candidate_id"] == candidate.candidate_id
        assert provenance["evidence"][0]["quote"] == "2 m of cable"
        with session_factory() as db:
            assert db.scalar(select(func.count()).select_from(ProgressEvent).join(
                Observation, ProgressEvent.observation_id == Observation.id
            ).where(Observation.job_id == fixture.job_id)) == 0
    finally:
        fixture.cleanup()


def test_graph_empty_shortlist_produces_unmatched_review_proposal():
    fixture = RuntimeFixture()
    try:
        result = _run(fixture, mode="unmatched", candidate_list=[])
        assert result["state"] == "ready_for_review", result
        _run_record, rows, proposals = _persisted(fixture)
        assert len(rows) == len(proposals) == 1
        assert proposals[0].mapping_state == "unmatched"
        assert proposals[0].chosen_activity_id is None
        assert proposals[0].candidates == []
        assert proposals[0].review_state == "pending"
    finally:
        fixture.cleanup()


def test_graph_ambiguous_shortlist_preserves_ranked_candidates_without_target():
    fixture = RuntimeFixture()
    try:
        first = _candidate(fixture)
        from app.db.models import Activity
        with session_factory.begin() as db:
            other = Activity(
                schedule_version_id=fixture.schedule_id, external_id="A-2",
                name="Cable installation north", wbs="2", discipline="electrical",
                work_type="cable_laying", is_leaf=True,
                measurement_basis="quantity_ratio", unit="m",
            )
            db.add(other)
            db.flush()
            second = Candidate.model_validate({
                **first.model_dump(mode="json"), "candidate_id": str(other.id),
                "external_id": other.external_id, "activity_name": other.name, "wbs": other.wbs,
            })
        _run(fixture, mode="ambiguous", candidate_list=[first, second])
        _run_record, _rows, proposals = _persisted(fixture)
        assert proposals[0].mapping_state == "ambiguous"
        assert proposals[0].chosen_activity_id is None
        assert [item["candidate_id"] for item in proposals[0].candidates] == [
            first.candidate_id, second.candidate_id,
        ]
    finally:
        fixture.cleanup()


def test_graph_lifecycle_proposal_keeps_endpoint_effect_evidence():
    fixture = RuntimeFixture(lifecycle=True)
    try:
        result = _run(fixture)
        assert result["state"] == "ready_for_review"
        _run_record, rows, proposals = _persisted(fixture)
        assert len(rows) == len(proposals) == 1
        effects = proposals[0].proposed_effects
        assert effects["event_type"] == "actual_start"
        assert effects["effective_date"] == "2026-09-24"
        assert effects["evidence"][0]["quote"] == "Started on 2026-09-24."
        assert rows[0].fields["lifecycle_effects"][0]["kind"] == "actual_start"
    finally:
        fixture.cleanup()


def test_graph_two_observations_keep_extraction_order_and_terminal_counts():
    fixture = RuntimeFixture(lifecycle=True)
    try:
        with session_factory.begin() as db:
            fragment = db.get(Fragment, fixture.fragment_id)
            fragment.original_text = "Installed 2 m of cable. Started on 2026-09-24."
            fragment.normalised_text = fragment.original_text
        quantity = ObservationSchema.model_validate({
            "discipline": "electrical", "work_type": "cable_laying",
            "event_type": "actual_progress", "observed_status": "in_progress",
            "area": None, "asset_tags": [], "explicit_activity_id": None,
            "work_date": "2026-09-24", "date_basis": "report_context",
            "quantity": "2", "quantity_kind": "delta", "unit": "m",
            "raw_unit": None, "reported_percent": None, "actual_start": None,
            "actual_finish": None, "blocker": None, "summary": "Installed 2 m of cable.",
            "evidence": [{"fields": ["quantity"], "fragment_id": str(fixture.fragment_id),
                          "quote": "2 m of cable"}], "warnings": [],
        })
        result = _run(fixture, observations=[quantity, fixture.lifecycle_observation])
        if result["state"] != "ready_for_review":
            with session_factory() as db:
                run = db.scalar(select(AgentRun).where(AgentRun.job_id == fixture.job_id))
                details = [(step.node, step.error_code, step.sanitized_summary) for step in run.steps]
            pytest.fail(f"graph run failed: {result}; steps={details}")
        assert result["extracted_count"] == result["proposal_count"] == 2
        _run_record, rows, proposals = _persisted(fixture)
        assert rows[0].ordinal < rows[1].ordinal
        assert [row.fields["event_type"] for row in rows] == ["actual_progress", "actual_start"]
        assert len(proposals) == 2
    finally:
        fixture.cleanup()
