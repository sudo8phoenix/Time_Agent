"""Source drift must stop new durable work before calls or budget reservations."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.llm import durable_contract
from app.conversation import runtime
from app.db.models import ConversationTask
from backend.tests.unit.test_runtime_batch25 import durable, journal  # noqa: F401


def test_contract_covers_request_builders_and_contains_only_hashes():
    contract = durable_contract.source_contract()
    files = contract["files"]
    for name in (
        "llm/groq.py",
        "llm/openrouter.py",
        "llm/ollama.py",
        "llm/extract.py",
        "schemas/observation.py",
        "prompts/extraction_v1.py",
        "agent/schedule_decision.py",
        "conversation/runtime.py",
    ):
        assert name in files
    assert all(len(value) == 64 for value in files.values())
    assert durable_contract.compatible_contract({"source_contract": contract})


@pytest.mark.parametrize("value", [None, {}, {"version": 2, "files": {}}, "invalid"])
def test_malformed_pins_fail_closed(value):
    assert not durable_contract.compatible_contract({"source_contract": value})


def test_legacy_is_not_silently_backfilled():
    record = {"roles": {}}
    assert not durable_contract.compatible_contract(record)
    assert record == {"roles": {}}


@pytest.mark.parametrize("drift", [False, True])
def test_durable_conversation_contract_checked_before_call_or_reservation(
    durable, monkeypatch, drift  # noqa: F811
):
    sessions, ids = durable
    _, token = runtime.claim(sessions)
    with sessions() as db:
        original = deepcopy(db.get(ConversationTask, ids.task).config)
    assert "source_contract" in original
    if drift:
        changed = deepcopy(original["source_contract"])
        changed["files"]["llm/groq.py"] = "0" * 64
        monkeypatch.setattr(durable_contract, "source_contract", lambda *args: changed)
    calls = []

    def factory(role):
        calls.append(role)
        return lambda **kwargs: {"observations": []}

    call = journal(sessions, ids.task, token, factory).model("extraction")
    if drift:
        with pytest.raises(runtime.TaskStopped) as failure:
            call(user="same request")
        assert failure.value.code == "CONVERSATION_CHECKPOINT_CONFLICT"
    else:
        assert call(user="same request") == {"observations": []}
    with sessions() as db:
        task = db.get(ConversationTask, ids.task)
        assert task.config["source_contract"] == original["source_contract"]
        assert task.model_calls == (0 if drift else 1)
    assert calls == ([] if drift else ["extraction"])


@pytest.mark.parametrize("hierarchical", [False, True])
def test_report_resume_rejects_source_drift_without_rewriting_pin(monkeypatch, hierarchical):
    from app.agent import runtime as agent_runtime
    from app.db.models import AgentRun, Job
    from backend.tests.unit.agent.test_agent_tools import Fixture

    fixture = Fixture()
    monkeypatch.setattr(agent_runtime.get_settings(), "agent_hierarchy_enabled", hierarchical)
    try:
        with fixture.context.session_factory() as db:
            run = agent_runtime._create_or_load_run(
                db, db.get(Job, fixture.job_id), clock=lambda: datetime.now(timezone.utc)
            )
            original = deepcopy(run.config_metadata)
            run_id = run.id
            assert original["timeout"] > 0
            db.commit()
        changed = deepcopy(original["source_contract"])
        changed["files"]["schemas/observation.py"] = "0" * 64
        monkeypatch.setattr(durable_contract, "source_contract", lambda *args: changed)
        with fixture.context.session_factory() as db:
            with pytest.raises(agent_runtime.AgentRuntimeError):
                agent_runtime._create_or_load_run(
                    db, db.get(Job, fixture.job_id), clock=lambda: datetime.now(timezone.utc)
                )
            assert db.get(AgentRun, run_id).config_metadata == original
        assert fixture.model_calls == 0
    finally:
        fixture.engine.dispose()


def test_endpoint_and_dependency_drift_are_rejected_without_storing_credentials(monkeypatch):
    from app.settings import Settings

    settings = Settings(
        _env_file=None, ollama_base_url="https://fixture-user:fixture-secret@example.invalid"
    )
    original = durable_contract.source_contract(settings)
    assert "fixture-secret" not in str(original) and original["dependencies"]["pydantic"]
    assert len(original["extraction_schema_sha256"]) == 64
    changed = settings.model_copy(update={"ollama_base_url": "https://other.invalid"})
    assert not durable_contract.compatible_contract({"source_contract": original}, changed)
    monkeypatch.setattr(durable_contract, "version", lambda name: "changed-dependency")
    assert not durable_contract.compatible_contract({"source_contract": original}, settings)


def test_legacy_conversation_stops_before_reserving_or_constructing_model(durable):  # noqa: F811
    sessions, ids = durable
    _, token = runtime.claim(sessions)
    with sessions.begin() as db:
        task = db.get(ConversationTask, ids.task)
        config = dict(task.config)
        config.pop("source_contract")
        task.config = config

    def forbidden(role):
        raise AssertionError("No adapter for unpinned legacy work")

    with pytest.raises(runtime.TaskStopped):
        journal(sessions, ids.task, token, forbidden).model("extraction")(user="legacy")
    with sessions() as db:
        task = db.get(ConversationTask, ids.task)
        assert task.model_calls == 0 and "source_contract" not in task.config
