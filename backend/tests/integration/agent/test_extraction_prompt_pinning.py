"""Reports retain their extraction contract across restarts and code defaults."""
from datetime import datetime, timezone
from dataclasses import replace

import pytest
import test_agent_runtime as runtime_tests
from sqlalchemy import select

from app.agent import runtime
from app.db.models import AgentRun, Job, Observation, Proposal
from app.db.session import session_factory
from app.prompts.extraction_v1 import PROMPT_VERSION, LEGACY_PROMPT_VERSION, V10_PROMPT_VERSION, V11_PROMPT_VERSION, get_extraction_prompt


@pytest.mark.parametrize("hierarchical", [False, True])
@pytest.mark.parametrize("legacy", [False, True, "v10", "v11"])
def test_report_prompt_survives_default_change(hierarchical, legacy, monkeypatch):
    monkeypatch.setattr(runtime.get_settings(), "agent_hierarchy_enabled", hierarchical)
    fixture = runtime_tests.RuntimeFixture()
    try:
        with session_factory.begin() as db:
            run = runtime._create_or_load_run(db, db.get(Job, fixture.job_id),
                clock=lambda: datetime.now(timezone.utc))
            assert run.config_metadata["extraction_prompt_version"] == PROMPT_VERSION
            if legacy in ("v10", "v11"):
                run.config_metadata = {**run.config_metadata, "extraction_prompt_version":
                    V10_PROMPT_VERSION if legacy == "v10" else V11_PROMPT_VERSION}
            elif legacy:
                config = dict(run.config_metadata)
                config.pop("extraction_prompt_version")
                run.config_metadata = config
        version = V11_PROMPT_VERSION if legacy == "v11" else V10_PROMPT_VERSION if legacy == "v10" else LEGACY_PROMPT_VERSION if legacy else PROMPT_VERSION
        expected = get_extraction_prompt(version)[1]
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
            assert run.config_metadata.get("extraction_prompt_version") == (None if legacy is True else version)
    finally:
        fixture.cleanup()


@pytest.mark.parametrize("hierarchical", [False, True])
@pytest.mark.parametrize("version", ["extraction-v18-nullable-source-contract", "extraction-v19-lifecycle-clause-completeness", "extraction-v20-short-schedule-ids"])
def test_explicit_contract_and_compact_decisions_survive_default_change(hierarchical, version, monkeypatch):
    monkeypatch.setattr(runtime.get_settings(), "agent_hierarchy_enabled", hierarchical)
    fixture = runtime_tests.RuntimeFixture()
    try:
        with session_factory.begin() as db:
            job = db.get(Job, fixture.job_id)
            job.config_snapshot = {**(job.config_snapshot or {}), "extraction_prompt_version": version}
            runtime._create_or_load_run(db, job, clock=lambda: datetime.now(timezone.utc))
        original = fixture.model
        calls = []
        def model(**kwargs):
            calls.append(kwargs)
            result = original(**kwargs)
            if version == "extraction-v20-short-schedule-ids":
                if 'candidate_ids' in result.value:
                    result = replace(result, value={'candidate_ids': ['row1']})
                elif 'candidate_id' in result.value:
                    result = replace(result, value={**result.value, 'candidate_id': 'row1'})
            return result
        fixture.model = model
        monkeypatch.setattr(runtime, "PROMPT_VERSION", "future-default")
        assert fixture.run()["state"] == "ready_for_review"
        extraction = [c for c in calls if "observations" in c["schema"].get("properties", {})]
        assert extraction[0]["system"] == get_extraction_prompt(version)[1]
        decisions = [c for c in calls if "observations" not in c["schema"].get("properties", {})]
        assert decisions and all(c["settings"]["num_predict"] == 768 for c in decisions)
        if version == "extraction-v20-short-schedule-ids":
            assert decisions[0]['user']['schedule_activities'][0]['id'] == 'row1'
            assert decisions[-1]['user']['candidates'][0]['candidate_id'] == 'row1'
        with session_factory() as db:
            proposal = db.scalar(select(Proposal).join(Observation,
                Observation.id == Proposal.observation_id).where(Observation.job_id == fixture.job_id))
            assert proposal.chosen_activity_id == fixture.activity_id
    finally:
        fixture.cleanup()
