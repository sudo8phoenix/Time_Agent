import csv
import json
from types import SimpleNamespace

import pytest

from app.llm import ollama
from evaluation.report_planner_eval import (
    EvaluationReplayMismatch,
    Recorder,
    SEED_CASE_IDS,
    load_cases,
)


def test_seed_dataset_uses_source_text_and_full_demo_schedule():
    cases = load_cases(dataset="seed")
    assert tuple(case["case_id"] for case in cases) == SEED_CASE_IDS
    assert all(case["dataset"] == "seed" for case in cases)
    assert all(case["text"].strip() and "expected_activity_ids" not in case["text"] for case in cases)
    assert all(case["schedule_path"].endswith("demo-utility-01.csv") for case in cases)
    with open(cases[0]["schedule_path"], newline="") as source:
        schedule_rows = list(csv.DictReader(source))
    assert len(schedule_rows) == 12
    schedule_ids = {row["activity_id"] for row in schedule_rows}
    assert {"PIP-A-ERECT-024", "PIP-B-ERECT-024"} <= schedule_ids
    assert all(set(case["label"]["expected_activity_ids"]) <= schedule_ids for case in cases)


class FakeAdapter:
    model = "groq-model"

    def __init__(self, transport):
        self._transport = transport

    def chat(self, **kwargs):
        payload = kwargs["payload"]
        status, body = self._transport("POST", "https://example.invalid", payload, 1, {})
        value = json.loads(body["choices"][0]["message"]["content"])
        return SimpleNamespace(value=value, prompt_hash="prompt", settings_hash="settings")


def make_replay_adapter(recorder, payload, live_calls):
    def factory(settings, **options):
        return FakeAdapter(lambda *args: live_calls.append(args) or (200, {"live": True}))

    recorder.factory = factory
    wrapped = recorder.create(None, role="selection")
    return wrapped


def test_specialist_replay_returns_recorded_output_without_live_transport():
    payload = {"model": "groq-model", "messages": [{"role": "user", "content": "same"}],
               "temperature": 0, "max_completion_tokens": 50, "stream": False}
    recorder = Recorder(replay_specialists=True)
    recorder.arm = "v2_super_vl"
    recorder.replay_queue = [{"stage": "selection", "model": "groq-model", "ok": True,
                              "payload_fingerprint": ollama._hash(payload), "output": {"chosen": "A"},
                              "http_status": 200}]
    live_calls = []
    adapter = make_replay_adapter(recorder, payload, live_calls)
    result = adapter.chat(payload=payload, schema={"properties": {"candidate_ids": {}}})
    assert result.value == {"chosen": "A"}
    assert not live_calls
    assert recorder.replay_queue == []


def test_specialist_replay_mismatch_fails_closed_without_live_transport():
    baseline_payload = {"model": "groq-model", "messages": [{"role": "user", "content": "baseline"}]}
    candidate_payload = {"model": "groq-model", "messages": [{"role": "user", "content": "changed"}]}
    recorder = Recorder(replay_specialists=True)
    recorder.arm = "v2_super_vl"
    recorder.replay_queue = [{"stage": "selection", "ok": True,
                              "payload_fingerprint": ollama._hash(baseline_payload), "output": {"chosen": "A"}}]
    live_calls = []
    adapter = make_replay_adapter(recorder, candidate_payload, live_calls)
    with pytest.raises(EvaluationReplayMismatch, match="fingerprint"):
        adapter.chat(payload=candidate_payload, schema={"properties": {"candidate_ids": {}}})
    assert not live_calls
    assert recorder.calls[0]["replay_mismatch"]
    assert recorder.calls[0]["payload_fingerprint"] == ollama._hash(candidate_payload)


def test_failed_transport_replay_preserves_error_semantics_instead_of_inventing_http_599():
    from app.llm.groq import GroqChatAdapter
    payload_seen = []
    # Obtain the exact payload from the same production adapter.
    def capture(*args):
        payload_seen.append(args[2])
        raise TimeoutError()
    schema = {"type": "object"}
    baseline = GroqChatAdapter("groq-model", bearer_token="key", transport=capture)
    with pytest.raises(ollama.OllamaTransportError):
        baseline.chat(system="s", user="u", schema=schema)
    recorder = Recorder(replay_specialists=True)
    recorder.arm = "v2_super_vl"
    recorder.factory = lambda *args, **kwargs: GroqChatAdapter("groq-model", bearer_token="key")
    recorder.replay_queue = [{"ok": False, "payload_fingerprint": ollama._hash(payload_seen[0]),
                              "error_type": "OllamaTransportError"}]
    with pytest.raises(ollama.OllamaTransportError):
        recorder.create(None, role="selection").chat(system="s", user="u", schema=schema)
    assert recorder.calls[0]["http_status"] is None
    assert recorder.calls[0]["error_type"] == "OllamaTransportError"
