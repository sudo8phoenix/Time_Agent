"""Graph-only intake prerequisites and repeated completion reads."""
import json

import pytest
from sqlalchemy import delete, select

from app.agent.runtime import process_job_with_graph
from app.db.models import AgentRun, Fragment, Job, Observation, Report
from app.db.session import session_factory
from test_agent_runtime import RuntimeFixture


@pytest.mark.parametrize("fragment_present", [True, False])
def test_untranscribed_report_cannot_become_empty_success(fragment_present):
    fixture = RuntimeFixture()
    try:
        with session_factory.begin() as db:
            report = db.get(Report, fixture.report_id)
            report.parsing_warnings = json.dumps(["NEEDS_TRANSCRIPTION:page:1"])
            if fragment_present:
                db.get(Fragment, fixture.fragment_id).ocr_status = "NEEDS_TRANSCRIPTION"
            else:
                db.execute(delete(Fragment).where(Fragment.report_id == fixture.report_id))

        def unexpected_model(**_kwargs):
            raise AssertionError("Unreadable input must not reach a model")

        fixture.model = unexpected_model
        result = fixture.run()
        assert result["state"] == "needs_transcription"
        assert result["extracted_count"] == result["proposal_count"] == 0
        with session_factory() as db:
            job = db.get(Job, fixture.job_id)
            assert job.state == "needs_transcription" and job.lease_token is None
            assert db.scalar(select(AgentRun).where(AgentRun.job_id == job.id)) is None
            assert db.scalar(select(Observation).where(Observation.job_id == job.id)) is None
    finally:
        fixture.cleanup()


def test_completed_graph_refreshes_counts_on_a_reused_job_instance():
    fixture = RuntimeFixture()
    try:
        with session_factory() as db:
            job = db.get(Job, fixture.job_id)
            kwargs = dict(token=fixture.token, session_factory=session_factory,
                          model_callable=fixture.model)
            first = process_job_with_graph(db, job, **kwargs)
            assert first["proposal_count"] == 1
            calls = list(fixture.calls)
            repeated = process_job_with_graph(db, job, **kwargs)
            assert repeated["state"] == "ready_for_review"
            assert repeated["extracted_count"] == repeated["proposal_count"] == 1
            assert fixture.calls == calls
    finally:
        fixture.cleanup()
