from types import SimpleNamespace

import app.llm.ollama as ollama_module
import app.agent.runtime as runtime_module


def test_graph_model_factory_honors_job_pinned_model(monkeypatch):
    seen = {}

    class Adapter:
        def __init__(self, base_url, model, *, bearer_token):
            seen.update(base_url=base_url, model=model, bearer_token=bearer_token)

        def chat(self, **kwargs):
            return kwargs

    monkeypatch.setattr(runtime_module, "get_settings", lambda: SimpleNamespace(
        ollama_base_url="http://ollama", ollama_model="current-model", ollama_api_key=None))
    monkeypatch.setattr(ollama_module, "OllamaChatAdapter", Adapter)

    model_call = runtime_module._model_callable("pinned-model")

    assert seen == {"base_url": "http://ollama", "model": "pinned-model", "bearer_token": None}
    assert model_call(messages=[]) == {"messages": []}
