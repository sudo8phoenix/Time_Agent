from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.agent.runtime import AgentRuntimeError, _ensure_active, _guard_model_calls
from app.db.models import Job, Project
from app.jobs.service import cancel_job
from app.llm.extract import FragmentInput, extract_fragments
from test_agent_tools import Fixture


@pytest.mark.parametrize("change,code", [("cancel", "JOB_LEASE_LOST"),
                                         ("lease", "JOB_LEASE_LOST"),
                                         ("schedule", "SCHEDULE_VERSION_STALE")])
def test_multibatch_extraction_stops_after_ownership_changes(change, code):
    fixture = Fixture()
    calls = []

    def active():
        _ensure_active(lambda: Session(fixture.engine), fixture.job_id, fixture.token,
                       job_for_heartbeat=None, heartbeat_callback=None, should_stop=None,
                       clock=lambda: datetime.now(timezone.utc))

    def model(**kwargs):
        calls.append(kwargs)
        with Session(fixture.engine) as db, db.begin():
            job = db.get(Job, fixture.job_id)
            if change == "cancel":
                cancel_job(db, job)
            elif change == "lease":
                job.lease_token = "replacement-owner"
            else:
                db.get(Project, fixture.project_id).active_schedule_version_id = uuid4()
        return {"observations": []}

    fragments = [FragmentInput(str(uuid4()), f"p{i}", "Synthetic note.", i) for i in range(9)]
    with pytest.raises(AgentRuntimeError) as error:
        extract_fragments(fragments, _guard_model_calls(model, active))
    assert error.value.code == code
    assert len(calls) == 1
    # The same retained callable cannot initiate a later provider request either.
    with pytest.raises(AgentRuntimeError):
        _guard_model_calls(model, active)(system="dummy")
    assert len(calls) == 1


def test_live_multibatch_extraction_still_processes_all_batches():
    calls = []
    def model(**kwargs):
        calls.append(kwargs)
        return {"observations": []}
    fragments = [FragmentInput(str(uuid4()), f"p{i}", "Synthetic note.", i) for i in range(9)]
    result = extract_fragments(fragments, _guard_model_calls(model, lambda: None))
    assert len(result) == len(calls) == 2
