import subprocess

import pytest

from app.ingest.native_schedule.runner import ParserRuntimeError, probe_schedule


def test_probe_uses_argument_list_and_returns_child_json(tmp_path, monkeypatch):
    path = tmp_path / "fixture.xer"
    path.write_text("fixture")
    seen = {}

    def run(command, timeout):
        seen.update(command=command, timeout=timeout)
        return subprocess.CompletedProcess(command, 0, '{"task_count": 4}', "")

    monkeypatch.setattr("app.ingest.native_schedule.runner._capture_child", run)
    assert probe_schedule(path) == {"task_count": 4}
    assert seen["command"][:3] == [seen["command"][0], "-m", "app.ingest.native_schedule.runner"]
    assert seen["timeout"] == 30


def test_probe_reports_timeout_and_bad_child_output(tmp_path, monkeypatch):
    path = tmp_path / "fixture.xer"
    path.write_text("fixture")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("probe", 30)

    monkeypatch.setattr("app.ingest.native_schedule.runner._capture_child", timeout)
    with pytest.raises(ParserRuntimeError, match="time limit") as timeout_error:
        probe_schedule(path)
    assert timeout_error.value.code == "SCHEDULE_PARSE_TIMEOUT"
    monkeypatch.setattr(
        "app.ingest.native_schedule.runner._capture_child",
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


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_real_child_output_flood_stops_during_capture(stream, monkeypatch):
    import sys
    from app.ingest.native_schedule import runner

    monkeypatch.setattr(runner, 'MAX_OUTPUT_BYTES', 1024)
    command = [sys.executable, '-c',
               f'import sys; sys.{stream}.write("x" * 1000000); sys.{stream}.flush()']
    with pytest.raises(ParserRuntimeError, match='output exceeded'):
        runner._run_json_child(command, 2)


def test_real_child_drains_both_streams_and_accepts_jvm_chatter(monkeypatch):
    import sys
    from app.ingest.native_schedule import runner

    monkeypatch.setattr(runner, 'MAX_OUTPUT_BYTES', 200000)
    command = [sys.executable, '-c',
               'import sys; sys.stderr.write("x" * 100000); '
               'print("JVM warning"); print(\'{"task_count":4}\')']
    assert runner._run_json_child(command, 2) == {'task_count': 4}


def test_real_child_timeout_kills_descendants(tmp_path):
    import sys
    import time
    from app.ingest.native_schedule import runner

    marker = tmp_path / 'survivor'
    descendant = f'import time; from pathlib import Path; time.sleep(0.5); Path({str(marker)!r}).touch()'
    command = [sys.executable, '-c',
               f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{descendant!r}]); time.sleep(5)']
    with pytest.raises(ParserRuntimeError) as error:
        runner._run_json_child(command, 0.15)
    assert error.value.code == 'SCHEDULE_PARSE_TIMEOUT'
    time.sleep(0.6)
    assert not marker.exists()


def test_exited_child_with_inherited_open_pipes_is_still_bounded():
    import sys
    from app.ingest.native_schedule import runner

    command = [sys.executable, '-c',
               'import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time; time.sleep(5)"])']
    with pytest.raises(ParserRuntimeError) as error:
        runner._run_json_child(command, 0.2)
    assert error.value.code == 'SCHEDULE_PARSE_TIMEOUT'


@pytest.mark.parametrize('source', ['import sys; sys.stdout.buffer.write(b"\\xff")',
                                     'import sys; print("[]"); sys.exit(2)'])
def test_invalid_encoding_and_error_shape_fail_safely(source):
    import sys
    from app.ingest.native_schedule import runner

    with pytest.raises(ParserRuntimeError) as error:
        runner._run_json_child([sys.executable, '-c', source], 2)
    assert error.value.code == 'SCHEDULE_PARSE_FAILED'


@pytest.mark.parametrize('output', [
    'PRIVATE SOURCE',
    '{"code":"SCHEDULE_PARSER_UNAVAILABLE","message":"PRIVATE SOURCE"}',
    '{"code":"PRIVATE SOURCE","message":"PRIVATE SOURCE"}',
    '{"code":[],"message":"PRIVATE SOURCE"}',
])
def test_child_errors_do_not_export_source_or_untrusted_codes(output):
    import sys
    from app.ingest.native_schedule import runner

    command = [sys.executable, '-c', f'import sys; print({output!r}); sys.stderr.write("PRIVATE SOURCE"); sys.exit(2)']
    with pytest.raises(ParserRuntimeError) as error:
        runner._run_json_child(command, 2)
    assert 'PRIVATE' not in str(error.value)
    assert 'PRIVATE' not in error.value.code


def test_exact_output_cap_is_accepted(monkeypatch):
    import sys
    from app.ingest.native_schedule import runner

    output = '{"task_count":4}'
    monkeypatch.setattr(runner, 'MAX_OUTPUT_BYTES', len(output.encode()))
    assert runner._run_json_child(
        [sys.executable, '-c', f'import sys; sys.stdout.write({output!r})'], 2,
    ) == {'task_count': 4}
