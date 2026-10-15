from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select

import app.llm.provider as provider_module
from app.agent.runtime import process_job_with_graph
from app.db.models import AgentRun, Job, Observation, ProgressEvent, Proposal
from app.db.session import session_factory
from app.jobs.worker import WorkerShutdown
from app.llm.ollama import LLMResult
from app.settings import get_settings
from test_agent_runtime import RuntimeFixture


SUPERVL = "nvidia/nemotron-3.5-super-vl:free"


class PlannerAdapter:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        action = self.reply(kwargs)
        return LLMResult(value={"action": action}, model=SUPERVL, model_digest=None,
                         runtime="mock-openrouter", elapsed_ms=1,
                         settings_hash="d" * 64, prompt_hash="e" * 64)


@pytest.fixture
def model_assisted_runtime(monkeypatch):
    original = get_settings()
    get_settings.cache_clear()
    current = {"settings": original.model_copy(update={
        "agent_hierarchy_enabled": True,
        "orchestrator_model_assisted": True,
        "orchestrator_provider": "openrouter",
        "orchestrator_model": SUPERVL,
        "extraction_provider": "ollama",
        "selection_provider": "ollama",
    })}
    monkeypatch.setattr("app.agent.runtime.get_settings", lambda: current["settings"])
    yield current
    get_settings.cache_clear()


def _install_planner(monkeypatch, reply):
    planner = PlannerAdapter(reply)
    created = []

    def create_adapter(settings, *, timeout, model_name=None, provider=None, role=None):
        assert role == "orchestrator"
        assert settings.orchestrator_provider == "openrouter"
        assert settings.orchestrator_model == SUPERVL
        created.append((settings.orchestrator_provider, settings.orchestrator_model, timeout))
        return planner

    monkeypatch.setattr(provider_module, "create_adapter", create_adapter)
    return planner, created


def _run(fixture, settings, *, checkpointer, stop=None, inject_model=True):
    with session_factory() as db:
        job = db.get(Job, fixture.job_id)
        return process_job_with_graph(db, job, token=fixture.token,
            session_factory=session_factory, database_url=settings["settings"].database_url,
            should_stop=stop, model_callable=fixture.model if inject_model else None,
            checkpointer=checkpointer)


def test_model_assisted_hierarchy_uses_pinned_supervl_and_resumes_after_worker_stop(
    model_assisted_runtime, monkeypatch
):
    settings = model_assisted_runtime
    planner, created = _install_planner(monkeypatch,
        lambda kwargs: kwargs["user"]["legal_actions"][0])
    fixture = RuntimeFixture()
    checkpointer = MemorySaver()
    try:
        with pytest.raises(WorkerShutdown):
            _run(fixture, settings, checkpointer=checkpointer,
                 stop=lambda: fixture.calls.count("extraction") >= 1)
        before = list(fixture.calls)
        settings["settings"] = settings["settings"].model_copy(update={
            "orchestrator_provider": "openrouter",
            "orchestrator_model": "nvidia/nemotron-3-ultra-550b-a55b",
        })
        result = _run(fixture, settings, checkpointer=checkpointer)
        if result["state"] != "ready_for_review":
            with session_factory() as db:
                run = db.scalar(select(AgentRun).where(AgentRun.job_id == fixture.job_id))
                details = [(step.node, step.state, step.error_code) for step in run.steps]
                tasks = [(task.agent_role, task.status, task.error_code) for task in run.tasks]
            pytest.fail(f"{result}; steps={details}; tasks={tasks}; planner_calls={len(planner.calls)}")
        assert [call["user"]["legal_actions"][0] for call in planner.calls] == [
            "intake", "analysis", "analysis", "review",
        ]
        assert before == ["extraction"]
        assert fixture.calls == ["extraction", "schedule", "selection"]
        assert len(created) == 2
        assert all(model == SUPERVL for _, model, _ in created)

        with session_factory.begin() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.job_id == fixture.job_id))
            assert run.config_metadata["model_assisted"] is True
            assert run.config_metadata["roles"]["orchestrator"] == {
                "provider": "openrouter", "model": SUPERVL, "key_slot": 0,
            }
    finally:
        fixture.cleanup()


def test_model_assisted_planner_rejects_illegal_action_without_domain_writes(
    model_assisted_runtime, monkeypatch
):
    settings = model_assisted_runtime
    planner, _ = _install_planner(monkeypatch, lambda _kwargs: "arbitrary-agent")
    fixture = RuntimeFixture()
    try:
        result = _run(fixture, settings, checkpointer=MemorySaver())
        assert result["state"] == "failed"
        assert result["error_code"] == "AGENT_PLANNER_INVALID"
        assert len(planner.calls) == 1
        with session_factory() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.job_id == fixture.job_id))
            assert run.config_metadata["roles"]["orchestrator"]["model"] == SUPERVL
            assert db.scalar(select(func.count()).select_from(Observation).where(
                Observation.job_id == fixture.job_id)) == 0
            assert db.scalar(select(func.count()).select_from(Proposal).join(
                Observation, Proposal.observation_id == Observation.id
            ).where(Observation.job_id == fixture.job_id)) == 0
            assert db.scalar(select(func.count()).select_from(ProgressEvent).join(
                Observation, ProgressEvent.observation_id == Observation.id
            ).where(Observation.job_id == fixture.job_id)) == 0
    finally:
        fixture.cleanup()


def test_model_assisted_runtime_builds_all_role_adapters_without_injected_model(
    model_assisted_runtime, monkeypatch
):
    settings = model_assisted_runtime
    fixture = RuntimeFixture()
    planner = PlannerAdapter(lambda kwargs: kwargs["user"]["legal_actions"][0])
    created_roles = []

    def create_adapter(adapter_settings, *, timeout, model_name=None, provider=None, role=None):
        created_roles.append(role)
        if role == "orchestrator":
            assert adapter_settings.orchestrator_model == SUPERVL
            return planner
        assert role in {"extraction", "selection"}
        return SimpleNamespace(chat=fixture.model)

    monkeypatch.setattr(provider_module, "create_adapter", create_adapter)
    try:
        result = _run(fixture, settings, checkpointer=MemorySaver(), inject_model=False)
        assert result["state"] == "ready_for_review", result
        assert created_roles == ["orchestrator", "extraction", "selection"]
        assert [call["user"]["legal_actions"][0] for call in planner.calls] == [
            "intake", "analysis", "review",
        ]
        assert fixture.calls == ["extraction", "schedule", "selection"]
    finally:
        fixture.cleanup()
