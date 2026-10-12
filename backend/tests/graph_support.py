"""Small test adapters that execute the production LangGraph report runtime."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import sessionmaker

from app.agent.runtime import process_job_with_graph
from app.agent.schedule_decision import select_activity, shortlist_activities
from app.llm.extract import ExtractionMetadata, ExtractionResult, extract_fragments
from app.llm.ollama import LLMResult


def fixture_result(value, *, model="fixture-model"):
    return LLMResult(
        value=value,
        model=model,
        model_digest="fixture-digest",
        runtime="fixture-runtime",
        elapsed_ms=1,
        settings_hash="a" * 64,
        prompt_hash="b" * 64,
    )


def extraction_result(observations=(), *, errors=()):
    metadata = ExtractionMetadata(
        prompt_version="fixture-extraction-v1",
        prompt_hash="c" * 64,
        settings_hash="a" * 64,
        model="fixture-model",
        model_digest="fixture-digest",
        runtime="fixture-runtime",
        batch_id="fixture-batch",
    )
    return (ExtractionResult(tuple(observations), metadata, tuple(errors)),)


def retrieval_for_activity(activity_id):
    from app.agent.schedule_decision import candidate_for_activity

    def retrieve(_observation, _schedule_version_id, activities):
        row = next(item for item in activities if str(item.id) == str(activity_id))
        return [candidate_for_activity(row)]

    return retrieve


def select_first_candidate(observation, candidates, _fragments, **_kwargs):
    from app.schemas.matching import Proposal

    if not candidates:
        return Proposal(
            candidate_id=None, mapping_state="unmatched", match_strength="unresolved",
            evidence_fragment_ids=[], reason_codes=["NO_CANDIDATES"], explanation="No candidates were returned.",
            missing_information=[], candidates=[], review_state="pending", proposed_effects={},
        )
    return Proposal(
        candidate_id=candidates[0].candidate_id, mapping_state="suggested", match_strength="review",
        evidence_fragment_ids=[item.fragment_id for item in observation.evidence], reason_codes=[],
        explanation="Selected from the typed retrieval result.", missing_information=[],
        candidates=candidates, review_state="pending", proposed_effects={},
    )


def run_graph(
    db,
    job,
    *,
    model_callable,
    extraction_service=extract_fragments,
    retrieval_service=shortlist_activities,
    selection_service=select_activity,
    heartbeat_callback=None,
    should_stop=None,
    token=None,
):
    """Run the real graph and tools on the caller's transaction-bound DB connection."""
    db.flush()
    db.refresh(job)
    token = token or job.lease_token or uuid4().hex
    if job.state != "ready_for_review":
        now = datetime.now(timezone.utc)
        job.state = "running"
        job.lease_token = token
        job.lease_expires_at = now + timedelta(minutes=5)
        job.heartbeat_at = now
    db.flush()
    bind = db.get_bind()
    factory = sessionmaker(
        bind=bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    return process_job_with_graph(
        db,
        job,
        token=token,
        session_factory=factory,
        model_callable=model_callable,
        extraction_service=extraction_service,
        retrieval_service=retrieval_service,
        selection_service=selection_service,
        heartbeat_callback=heartbeat_callback,
        should_stop=should_stop,
        checkpointer=MemorySaver(),
    )
