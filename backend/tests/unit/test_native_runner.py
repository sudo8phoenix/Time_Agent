import subprocess

import pytest

from app.ingest.native_schedule.runner import ParserRuntimeError, probe_schedule


def test_probe_uses_argument_list_and_returns_child_json(tmp_path, monkeypatch):
    path = tmp_path / "fixture.xer"
    path.write_text("fixture")
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 0, '{"task_count": 4}', "")

    monkeypatch.setattr("app.ingest.native_schedule.runner.subprocess.run", run)
    assert probe_schedule(path) == {"task_count": 4}
    assert seen["command"][:3] == [seen["command"][0], "-m", "app.ingest.native_schedule.runner"]
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["timeout"] == 30


def test_probe_reports_timeout_and_bad_child_output(tmp_path, monkeypatch):
    path = tmp_path / "fixture.xer"
    path.write_text("fixture")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("probe", 30)

    monkeypatch.setattr("app.ingest.native_schedule.runner.subprocess.run", timeout)
    with pytest.raises(ParserRuntimeError, match="30-second") as timeout_error:
        probe_schedule(path)
    assert timeout_error.value.code == "SCHEDULE_PARSE_TIMEOUT"
    monkeypatch.setattr(
        "app.ingest.native_schedule.runner.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "not json", ""),
    )
    with pytest.raises(ParserRuntimeError) as invalid:
        probe_schedule(path)
    assert invalid.value.code == "SCHEDULE_PARSE_FAILED"


def test_probe_rejects_missing_and_oversized_paths(tmp_path):
    with pytest.raises(ParserRuntimeError) as missing:
        probe_schedule(tmp_path / "missing.xer")
    assert missing.value.code == "SCHEDULE_PARSE_FAILED"
    large = tmp_path / "large.xer"
    large.write_bytes(b"0" * (10 * 1024 * 1024 + 1))
    with pytest.raises(ParserRuntimeError) as oversized:
        probe_schedule(large)
    assert oversized.value.code == "SCHEDULE_TOO_LARGE"
