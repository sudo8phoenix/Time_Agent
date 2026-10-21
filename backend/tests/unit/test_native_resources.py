import sys

import pytest

from app.ingest.native_schedule import runner


def test_real_child_has_private_environment_and_kernel_limits(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'private-database-secret')
    monkeypatch.setenv('JAVA_TOOL_OPTIONS', '-Xmx1g')
    monkeypatch.setenv('PYTHONSTARTUP', '/private/injection.py')
    result = runner._run_json_child([sys.executable, '-c', '''
import os, json, resource
print(json.dumps({'secret': os.getenv('DATABASE_URL'),
                  'java': os.getenv('JAVA_TOOL_OPTIONS'),
                  'startup': os.getenv('PYTHONSTARTUP'),
                  'home': os.environ['HOME'], 'cwd': os.getcwd(),
                  'cpu': resource.getrlimit(resource.RLIMIT_CPU)[0],
                  'core': resource.getrlimit(resource.RLIMIT_CORE)[0]}))
'''], 3)
    assert result['secret'] is result['java'] is result['startup'] is None
    assert result['home'] == result['cwd']
    assert result['cpu'] == runner.DEFAULT_TIMEOUT_SECONDS
    assert result['core'] == 0
    from pathlib import Path
    assert not Path(result['home']).exists()


def test_memory_limit_terminates_real_child(monkeypatch):
    monkeypatch.setattr(runner, 'MAX_MEMORY_BYTES', 1)
    with pytest.raises(runner.ParserRuntimeError, match='memory limit') as error:
        runner._run_json_child([sys.executable, '-c', 'import time; time.sleep(5)'], 2)
    assert error.value.code == 'SCHEDULE_TOO_LARGE'


def test_unavailable_memory_supervision_fails_closed(monkeypatch):
    def fail(_pid):
        raise ValueError('private monitor details')
    monkeypatch.setattr(runner, '_resident_memory', fail)
    with pytest.raises(runner.ParserRuntimeError, match='supervision failed'):
        runner._run_json_child([sys.executable, '-c', 'import time; time.sleep(5)'], 2)


def test_real_child_cpu_budget_stops_busy_loop():
    completed = runner._capture_child([sys.executable, '-c',
        'import resource; resource.setrlimit(resource.RLIMIT_CPU, (1, 1)); exec("while True: pass")'], 4)
    assert completed.returncode < 0


def test_missing_memory_sample_for_live_child_fails_closed(monkeypatch):
    monkeypatch.setattr(runner, '_resident_memory', lambda _pid: None)
    with pytest.raises(runner.ParserRuntimeError, match='supervision failed'):
        runner._run_json_child([sys.executable, '-c', 'import time; time.sleep(5)'], 2)
