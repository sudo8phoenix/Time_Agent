"""Actual runtime wiring: cancellation between mock calls must stop extraction."""
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
import pytest
from sqlalchemy import func, select

import test_agent_runtime as runtime_tests
from app.agent.runtime import AgentRuntimeError
from app.db.models import Fragment, Job, Observation, Proposal
from app.db.session import session_factory
from app.jobs.service import cancel_job
from app.settings import get_settings


@pytest.mark.parametrize("hierarchical", [False, True])
def test_committed_cancellation_stops_later_batch_and_publication(monkeypatch, hierarchical):
    monkeypatch.setattr(get_settings(), "agent_hierarchy_enabled", hierarchical)
    monkeypatch.setattr(get_settings(), "orchestrator_model_assisted", False)
    fixture = runtime_tests.RuntimeFixture()
    calls = []
    try:
        with session_factory.begin() as db:
            for ordinal in range(2, 10):
                db.add(Fragment(id=uuid4(), report_id=fixture.report_id, ordinal=ordinal,
                                locator=f"paragraph:{ordinal}",
                                original_text="Synthetic field note.",
                                normalised_text="Synthetic field note."))

        def model(**kwargs):
            calls.append(kwargs)
            with session_factory.begin() as db:
                cancel_job(db, db.get(Job, fixture.job_id))
            return {"observations": []}

        fixture.model = model
        with pytest.raises(AgentRuntimeError) as error:
            fixture.run(checkpointer=MemorySaver())
        assert error.value.code == "JOB_LEASE_LOST"
        assert len(calls) == 1
        with session_factory() as db:
            assert db.get(Job, fixture.job_id).state == "cancelled"
            assert db.scalar(select(func.count()).select_from(Observation).where(
                Observation.job_id == fixture.job_id)) == 0
            assert db.scalar(select(func.count()).select_from(Proposal).where(
                Proposal.project_id == fixture.project_id)) == 0
    finally:
        fixture.cleanup()
