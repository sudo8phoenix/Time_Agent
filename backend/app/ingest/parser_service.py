"""Fixed-operation Unix-socket service; deploy only in the isolated parser container."""
import base64
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

from .parser_transport import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, read_frame, write_frame, DEFAULT_SOCKET
from .report_parser import OPERATIONS, _safe_error, run_parser_local
from .native_schedule.runner import NATIVE_MODULES, ParserRuntimeError, _run_json_child

MAX_CONCURRENT = 2


def dispatch(request):
    if not isinstance(request, dict):
        raise ValueError('invalid parser request')
    kind = request.get('kind')
    if kind == 'health' and set(request) == {'kind'}:
        return {'status': 'ok'}
    if kind == 'report':
        if set(request) != {'kind', 'operation', 'raw', 'filename', 'mime', 'mapping'}:
            raise ValueError('invalid parser request')
        if request['operation'] not in OPERATIONS or not all(
            isinstance(request[key], str) for key in ('raw', 'filename', 'mime')
        ):
            raise ValueError('invalid parser request')
        raw = base64.b64decode(request['raw'], validate=True)
        return run_parser_local(request['operation'], raw, filename=request['filename'],
                                mime=request['mime'], mapping=request['mapping'])
    if kind != 'native' or set(request) != {'kind', 'module', 'raw', 'suffix', 'source_project_id'}:
        raise ValueError('invalid parser request')
    module = request['module']
    if not isinstance(module, str) or module not in NATIVE_MODULES | {'probe'}:
        raise ValueError('invalid parser request')
    if request['suffix'] not in {'.xer', '.xml', '.mpp', '.xlsx', '.json'}:
        raise ValueError('invalid parser request')
    project = request['source_project_id']
    if project is not None and (not isinstance(project, str) or len(project) > 200):
        raise ValueError('invalid parser request')
    raw = base64.b64decode(request['raw'], validate=True)
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError('report exceeds 10 MB limit')
    with tempfile.TemporaryDirectory(prefix='schedule-input-') as directory:
        path = Path(directory) / ('input' + request['suffix'])
        path.write_bytes(raw)
        if module == 'probe':
            command = [sys.executable, '-m', 'app.ingest.native_schedule.runner', '--probe', str(path)]
        else:
            command = [sys.executable, '-m', module, '--child', '--input', str(path)]
            if project is not None:
                command.extend(['--source-project-id', project])
        return _run_json_child(command, 30)


def serve_connection(connection):
    deadline = time.monotonic() + 40
    try:
        request = read_frame(connection, MAX_REQUEST_BYTES, deadline)
        result = dispatch(request)
        response = {'ok': True, 'result': result, 'error': None}
    except ParserRuntimeError as exc:
        response = {'ok': False, 'result': None, 'error': exc.code}
    except (ValueError, TypeError, KeyError) as exc:
        response = {'ok': False, 'result': None, 'error': _safe_error(str(exc))}
    except Exception:
        response = {'ok': False, 'result': None, 'error': 'report parser failed safely'}
    try:
        write_frame(connection, response, MAX_RESPONSE_BYTES, deadline)
    except (OSError, ValueError):
        pass


def main():
    # Refuse accidental invocation outside the explicitly configured container.
    if os.environ.get('PARSER_SERVICE_ISOLATED') != '1':
        raise SystemExit('Start this service through the isolated Docker Compose parser service.')
    path = Path(os.environ.get('PARSER_SOCKET_PATH', DEFAULT_SOCKET))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    slots = threading.BoundedSemaphore(MAX_CONCURRENT)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        path.chmod(0o660)
        listener.listen(8)
        while True:
            connection, _ = listener.accept()
            if not slots.acquire(blocking=False):
                connection.close()
                continue
            def handle(connection=connection):
                try:
                    with connection:
                        serve_connection(connection)
                finally:
                    slots.release()
            threading.Thread(target=handle, daemon=True).start()


if __name__ == '__main__':
    main()
