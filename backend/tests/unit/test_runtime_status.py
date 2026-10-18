import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ops import runtime_status


def test_numeric_state_allowlists_values_and_discards_unknown_fields():
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    result = runtime_status._numeric_state({
        "remaining_requests": 4,
        "remaining_tokens": 0,
        "cooldown": now.timestamp() + 15,
        "authorization": "Bearer secret",
        "headers": {"x-secret": "sentinel"},
        "owner": "lease-owner-secret",
    }, now)
    assert result == {"remaining_requests": 4, "remaining_tokens": 0,
                     "cooldown_remaining_seconds": 15}
    assert "secret" not in json.dumps(result)


def test_numeric_state_ignores_non_finite_float_values():
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    result = runtime_status._numeric_state({
        "cooldown": float("inf"),
        "token_reset": float("nan"),
        "request_reset": float("-inf"),
    }, now)
    assert result == {}


def test_state_label_sanitizer_aggregates_unrecognized_values(monkeypatch):
    class Result:
        def mappings(self):
            return [
                {"state": "queued", "count": 2},
                {"state": "running", "count": 3},
                {"state": "ready_for_review", "count": 4},
                {"state": "needs_transcription", "count": 1},
                {"state": "private user text", "count": 5},
                {"state": "other_compromised", "count": 7},
            ]

    class FakeDB:
        def execute(self, _statement):
            return Result()

    states = runtime_status._count_by(FakeDB(), "jobs", "state")
    assert states == {"queued": 2, "running": 3, "ready_for_review": 4,
                      "needs_transcription": 1, "other": 12}
    assert "private user text" not in json.dumps(states)


def test_error_code_sanitizer_rejects_arbitrary_text():
    assert runtime_status._safe_code("MODEL_TIMEOUT") == "MODEL_TIMEOUT"
    assert runtime_status._safe_code("source text username@example.com") == "OTHER"


def test_output_refuses_existing_path(tmp_path, monkeypatch):
    target = tmp_path / "report.json"
    target.write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(runtime_status, "get_settings", lambda: SimpleNamespace())
    with pytest.raises(SystemExit):
        runtime_status.main(["--output", str(target)])
    assert target.read_text(encoding="utf-8") == "keep me"
