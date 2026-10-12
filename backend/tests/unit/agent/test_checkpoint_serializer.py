from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import ClassVar

from app.agent.checkpoint import make_checkpoint_serializer
from app.agent.state import ModelMetadata, create_initial_state
from app.schemas.common import Discipline
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


@dataclass
class ImportableConstructorProbe:
    value: str
    constructions: ClassVar[int] = 0

    def __post_init__(self):
        type(self).constructions += 1


IDS = {
    "run_id": "11111111-1111-4111-8111-111111111111",
    "job_id": "22222222-2222-4222-8222-222222222222",
    "project_id": "33333333-3333-4333-8333-333333333333",
    "report_id": "44444444-4444-4444-8444-444444444444",
    "schedule_version_id": "55555555-5555-4555-8555-555555555555",
}


def test_builtin_values_and_exact_legacy_agent_types_round_trip(caplog):
    serializer = make_checkpoint_serializer()
    state = create_initial_state(**IDS, model_metadata={"model_tag": "pinned"})

    state_type, encoded = serializer.dumps_typed(state)
    restored = serializer.loads_typed((state_type, encoded))
    assert restored == state
    assert isinstance(restored.model_metadata, ModelMetadata)
    assert serializer.loads_typed(serializer.dumps_typed(Discipline.civil)) is Discipline.civil
    assert not [record for record in caplog.records if record.levelname == "WARNING"]


def test_legacy_json_modelmetadata_constructor_is_allowed():
    serializer = make_checkpoint_serializer()
    legacy = {
        "lc": 2,
        "type": "constructor",
        "id": ["app", "agent", "state", "ModelMetadata"],
        "kwargs": {"model_tag": "recovery-seed"},
    }
    restored = serializer.loads_typed(("json", json.dumps(legacy).encode()))
    assert restored == ModelMetadata(model_tag="recovery-seed")


def test_unknown_importable_msgpack_and_json_types_stay_inert():
    permissive = JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=True,
        allowed_json_modules=True,
    )
    serializer = make_checkpoint_serializer()
    ImportableConstructorProbe.constructions = 0

    typed = permissive.dumps_typed(ImportableConstructorProbe("payload"))
    assert isinstance(permissive.loads_typed(typed), ImportableConstructorProbe)
    assert ImportableConstructorProbe.constructions == 2

    ImportableConstructorProbe.constructions = 0
    payload = {
        "lc": 2,
        "type": "constructor",
        "id": [ImportableConstructorProbe.__module__, "ImportableConstructorProbe"],
        "kwargs": {"value": "payload"},
    }
    encoded_json = ("json", json.dumps(payload).encode())
    assert isinstance(permissive.loads_typed(encoded_json), ImportableConstructorProbe)
    assert ImportableConstructorProbe.constructions == 1

    ImportableConstructorProbe.constructions = 0
    restored_json = serializer.loads_typed(encoded_json)
    restored_msgpack = serializer.loads_typed(typed)
    assert isinstance(restored_json, dict)
    assert not isinstance(restored_msgpack, ImportableConstructorProbe)
    assert ImportableConstructorProbe.constructions == 0


def test_postgres_scope_installs_explicit_serializer_without_env_policy(monkeypatch):
    import app.agent.runtime as runtime

    class FakeSaver:
        serde = None

    saver = FakeSaver()

    @contextmanager
    def fake_context():
        yield saver

    monkeypatch.setattr(
        runtime.PostgresSaver,
        "from_conn_string",
        classmethod(lambda cls, url: fake_context()),
    )
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "false")

    with runtime._checkpoint_scope("postgresql://localhost/test", None) as opened:
        assert opened is saver
        assert isinstance(opened.serde, JsonPlusSerializer)
        assert opened.serde.pickle_fallback is False
        ImportableConstructorProbe.constructions = 0
        payload = {
            "lc": 2,
            "type": "constructor",
            "id": [ImportableConstructorProbe.__module__, "ImportableConstructorProbe"],
            "kwargs": {"value": "payload"},
        }
        result = opened.serde.loads_typed(("json", json.dumps(payload).encode()))
        assert isinstance(result, dict)
        assert ImportableConstructorProbe.constructions == 0
