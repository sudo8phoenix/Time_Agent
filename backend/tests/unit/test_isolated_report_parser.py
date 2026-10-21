"""Real fixed-child transport, failure fences and process-group cleanup."""
import json
import os
import subprocess
import sys
import time

import pytest

from app.ingest import report_parser
from app.ingest.reports import parse_bytes


def inject_child(monkeypatch, code):
    real_popen = subprocess.Popen
    observed = []
    def spawn(command, **kwargs):
        if command[1:3] == ['-m', 'app.ingest.report_parser']:
            observed.append((command, kwargs))
            return real_popen([sys.executable, '-c', code], **kwargs)
        return real_popen(command, **kwargs)
    monkeypatch.setattr(report_parser.subprocess, 'Popen', spawn)
    return observed


def test_real_text_worker_round_trip_and_private_transport(monkeypatch):
    real_popen = subprocess.Popen
    seen = []
    def spawn(command, **kwargs):
        if command[1:3] == ['-m', 'app.ingest.report_parser']:
            seen.append((command, kwargs))
        return real_popen(command, **kwargs)
    monkeypatch.setattr(report_parser.subprocess, 'Popen', spawn)
    monkeypatch.setenv('GROQ_API_KEY', 'must-not-reach-parser')
    assert parse_bytes(b'Private first\n\nSecond', '../../private.txt', 'text/plain') == (
        [('paragraph:1', 'Private first'), ('paragraph:2', 'Second')], [], 'text')
    command, options = seen[0]
    assert command == [sys.executable, '-m', 'app.ingest.report_parser']
    assert options['shell'] is False and options['start_new_session'] is True
    assert options['close_fds'] is True
    assert 'GROQ_API_KEY' not in options['env']
    assert set(options['env']) == {'PYTHONPATH', 'PYTHONIOENCODING', 'PYTHONDONTWRITEBYTECODE', 'LANG'}
    for stream in ('stdin', 'stdout', 'stderr'):
        assert options[stream].closed


@pytest.mark.parametrize('output', [
    'PRIVATE RAW SOURCE ERROR',
    '[]',
    '{"ok":true,"result":{},"error":null}',
    '{"ok":true,"result":{"parts":[["page:1",2]],"warnings":[],"kind":"pdf"},"error":null}',
    '{"ok":true,"result":{"parts":[],"warnings":[],"kind":"text"},"error":null,"extra":"bad"}',
    '{"ok":true,"result":{"parts":[],"warnings":[NaN],"kind":"pdf"},"error":null}',
])
def test_malformed_or_wrong_shape_child_never_yields_success(output, monkeypatch):
    inject_child(monkeypatch, 'import sys; sys.stdout.write(' + repr(output) + ')')
    with pytest.raises(ValueError) as error:
        parse_bytes(b'private', 'report.txt', 'text/plain')
    assert 'PRIVATE RAW SOURCE ERROR' not in str(error.value)


def test_hanging_child_times_out_and_is_reaped(monkeypatch):
    seen = inject_child(monkeypatch, 'import time; time.sleep(5)')
    monkeypatch.setattr(report_parser, 'WALL_SECONDS', 0.15)
    started = time.monotonic()
    with pytest.raises(ValueError, match='time limit'):
        parse_bytes(b'x', 'report.txt', 'text/plain')
    assert time.monotonic() - started < 2
    assert seen[0][1]['stdout'].closed


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_output_flood_is_bounded_and_rejected(stream, monkeypatch):
    inject_child(monkeypatch, f'import sys; sys.{stream}.write("x" * 2048); sys.{stream}.flush()')
    monkeypatch.setattr(report_parser, 'MAX_OUTPUT_BYTES', 1024)
    with pytest.raises(ValueError, match='output exceeds limit'):
        parse_bytes(b'x', 'report.txt', 'text/plain')


@pytest.mark.parametrize('monitor', ['over_limit', 'unavailable', 'missing_sample'])
def test_memory_limit_or_missing_monitor_fails_closed(monitor, monkeypatch):
    inject_child(monkeypatch, 'import time; time.sleep(5)')
    def memory(_pid):
        if monitor == 'unavailable':
            raise ValueError('memory monitoring unavailable')
        if monitor == 'missing_sample':
            return None
        return report_parser.MAX_MEMORY_BYTES + 1
    monkeypatch.setattr(report_parser, '_resident_memory', memory)
    with pytest.raises(ValueError, match='memory'):
        parse_bytes(b'x', 'report.txt', 'text/plain')


@pytest.mark.parametrize('state', ['Z (zombie)', 'X (dead)', 'R (running)'])
def test_linux_status_without_rss_defers_to_child_liveness(monkeypatch, state):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(report_parser.Path, 'read_text',
                        lambda path: f'Name:\tparser\nState:\t{state}\n')
    assert report_parser._resident_memory(12345) is None


def test_linux_status_with_rss_returns_bytes(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(report_parser.Path, 'read_text',
                        lambda path: 'State:\tR (running)\nVmRSS:\t1234 kB\n')
    assert report_parser._resident_memory(12345) == 1234 * 1024


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux /proc exit race')
def test_linux_unreaped_child_without_rss_is_recognized_as_exited():
    with subprocess.Popen([sys.executable, '-c', 'pass']) as child:
        # Wait for exit without reaping: /proc still exists but VmRSS is absent.
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
        assert report_parser._resident_memory(child.pid) is None
        assert child.poll() == 0


def test_process_group_cleanup_kills_descendants_after_leader_exit(monkeypatch, tmp_path):
    marker = tmp_path / 'orphan-survived'
    grandchild = f'import time; from pathlib import Path; time.sleep(0.5); Path({str(marker)!r}).write_text("bad")'
    output = json.dumps({'ok': True, 'result': {'parts': [], 'warnings': [], 'kind': 'text'}, 'error': None})
    code = ('import subprocess,sys; subprocess.Popen([sys.executable,"-c",' + repr(grandchild) + ']); '
            'sys.stdout.write(' + repr(output) + '); sys.stdout.flush()')
    inject_child(monkeypatch, code)
    assert parse_bytes(b'x', 'report.txt', 'text/plain') == ([], [], 'text')
    time.sleep(0.7)
    assert not marker.exists()


def test_unknown_operation_rejected_before_process_launch(monkeypatch):
    monkeypatch.setattr(report_parser.subprocess, 'Popen', lambda *a, **k: pytest.fail('launched'))
    with pytest.raises(ValueError, match='unsupported'):
        report_parser.run_parser('shell', b'')


def test_child_limit_configuration_linux_and_darwin(monkeypatch):
    import resource
    calls = []
    monkeypatch.setattr(resource, 'setrlimit', lambda kind, limits: calls.append((kind, limits)))
    monkeypatch.setattr(sys, 'platform', 'linux')
    report_parser._apply_limits()
    assert (resource.RLIMIT_AS, (report_parser.MAX_MEMORY_BYTES,) * 2) in calls
    assert (resource.RLIMIT_FSIZE, (report_parser.MAX_OUTPUT_BYTES,) * 2) in calls
    assert (resource.RLIMIT_CPU, (report_parser.WALL_SECONDS,) * 2) in calls
    calls.clear()
    monkeypatch.setattr(sys, 'platform', 'darwin')
    report_parser._apply_limits()
    assert all(kind != resource.RLIMIT_AS for kind, limits in calls)


def test_real_worker_preserves_parser_validation_errors():
    with pytest.raises(ValueError, match='invalid document archive'):
        parse_bytes(b'broken', 'broken.docx', 'application/octet-stream')


def test_child_failure_message_cannot_export_private_dependency_error(monkeypatch):
    body = json.dumps({'ok': False, 'result': None, 'error': 'PRIVATE SOURCE AND API KEY'})
    inject_child(monkeypatch, 'import sys; sys.stdout.write(' + repr(body) + ')')
    with pytest.raises(ValueError, match='report parser failed safely') as error:
        parse_bytes(b'private', 'report.txt', 'text/plain')
    assert 'PRIVATE' not in str(error.value)


def test_sheet_validation_message_does_not_echo_source_sheet_title():
    assert report_parser._safe_error('sheet PRIVATE is empty') == 'XLSX sheet is empty'
    assert report_parser._safe_error('sheet PRIVATE missing required columns') == 'XLSX sheet missing required columns'
