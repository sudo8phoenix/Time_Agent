"""Reports retain their extraction contract across restarts and code defaults."""
from datetime import datetime, timezone

import pytest
import test_agent_runtime as runtime_tests
from sqlalchemy import select

from app.agent import runtime
from app.db.models import AgentRun, Job
from app.db.session import session_factory
from app.prompts.extraction_v1 import PROMPT_VERSION, LEGACY_PROMPT_VERSION, V10_PROMPT_VERSION, get_extraction_prompt


@pytest.mark.parametrize("hierarchical", [False, True])
@pytest.mark.parametrize("legacy", [False, True, "v10"])
def test_report_prompt_survives_default_change(hierarchical, legacy, monkeypatch):
    monkeypatch.setattr(runtime.get_settings(), "agent_hierarchy_enabled", hierarchical)
    fixture = runtime_tests.RuntimeFixture()
    try:
        with session_factory.begin() as db:
            run = runtime._create_or_load_run(db, db.get(Job, fixture.job_id),
                clock=lambda: datetime.now(timezone.utc))
            assert run.config_metadata["extraction_prompt_version"] == PROMPT_VERSION
            if legacy == "v10":
                run.config_metadata = {**run.config_metadata, "extraction_prompt_version": V10_PROMPT_VERSION}
            elif legacy:
                config = dict(run.config_metadata)
                config.pop("extraction_prompt_version")
                run.config_metadata = config
        expected = get_extraction_prompt(V10_PROMPT_VERSION if legacy == "v10" else LEGACY_PROMPT_VERSION if legacy else PROMPT_VERSION)[1]
        original = fixture.model
        prompts = []
        def model(**kwargs):
            if "observations" in kwargs["schema"].get("properties", {}):
                prompts.append(kwargs["system"])
            return original(**kwargs)
        fixture.model = model
        monkeypatch.setattr(runtime, "PROMPT_VERSION", "future-default")
        assert fixture.run()["state"] == "ready_for_review"
        assert prompts == [expected]
        with session_factory() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.job_id == fixture.job_id))
            assert run.config_metadata.get("extraction_prompt_version") == (V10_PROMPT_VERSION if legacy == "v10" else None if legacy else PROMPT_VERSION)
    finally:
        fixture.cleanup()
