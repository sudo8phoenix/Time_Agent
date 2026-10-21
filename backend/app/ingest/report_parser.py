"""Fixed-operation report parser child with private, supervised transport.

Linux applies an address-space limit. Darwin supervises resident memory because
its kernel rejects RLIMIT_AS; sampling has a documented finite overshoot window.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_REQUEST_BYTES = 15 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_MEMORY_BYTES = 768 * 1024 * 1024
WALL_SECONDS = 30
POLL_SECONDS = 0.05
OPERATIONS = frozenset({'parse', 'preview', 'mapping'})


_SAFE_ERRORS = frozenset({
    'report exceeds 10 MB limit', 'document contains too many archive members',
    'document expands beyond 50 MB limit', 'unsafe or ambiguous document archive member',
    'invalid document archive', 'extracted report text exceeds limit',
    'text file must be UTF-8', 'report is empty', 'DOCX support is unavailable',
    'invalid DOCX document', 'DOCX contains no readable text',
    'PDF support is unavailable', 'encrypted PDF requires an unlocked source',
    'invalid or encrypted PDF document', 'PDF exceeds 20 page limit',
    'PDF contains no extractable text', 'XLSX support is unavailable',
    'invalid XLSX document', 'XLSX exceeds 30 sheet limit',
    'XLSX exceeds 200 column limit', 'XLSX exceeds 5,000 row limit',
    'XLSX contains no report rows', 'unsupported report format',
    'too many sheets to preview', 'mapped sheet is missing',
    'report exceeds 200 columns', 'mapped column is missing',
    'invalid report parser request', 'report parser request exceeds limit',
    'report parser output exceeds limit',
})


def _safe_error(value):
    # Dependency exceptions may contain source text, filenames or XML. Only
    # known validation messages cross the child boundary into API errors.
    if value in _SAFE_ERRORS:
        return value
    if value.startswith('sheet ') and value.endswith(' missing required columns'):
        return 'XLSX sheet missing required columns'
    if value.startswith('sheet ') and value.endswith(' is empty'):
        return 'XLSX sheet is empty'
    return 'report parser failed safely'


def _json_loads(raw):
    def reject_constant(_value):
        raise ValueError('invalid JSON constant')
    return json.loads(raw, parse_constant=reject_constant)


def _validate_result(operation, result):
    if not isinstance(result, dict):
        raise ValueError('invalid parser result')
    keys = {'parts', 'warnings', 'kind'} if operation == 'parse' else (
        {'sheets'} if operation == 'preview' else {'parts', 'errors', 'metadata'})
    if set(result) != keys:
        raise ValueError('invalid parser result')
    if 'parts' in result:
        parts = result['parts']
        if not isinstance(parts, list) or any(
            not isinstance(part, (list, tuple)) or len(part) != 2
            or any(not isinstance(value, str) for value in part)
            or len(part[0]) > 512 for part in parts
        ) or sum(len(part[1]) for part in parts) > 2_000_000:
            raise ValueError('invalid parser parts')
    if operation == 'parse':
        if (result['kind'] not in {'text', 'docx', 'pdf', 'xlsx'}
                or not isinstance(result['warnings'], list)
                or any(not isinstance(item, str) for item in result['warnings'])):
            raise ValueError('invalid parser result')
    elif operation == 'preview':
        sheets = result['sheets']
        if not isinstance(sheets, list) or len(sheets) > 30:
            raise ValueError('invalid parser preview')
        for sheet in sheets:
            if (not isinstance(sheet, dict) or set(sheet) != {'name', 'rows'}
                    or not isinstance(sheet['name'], str) or not isinstance(sheet['rows'], list)
                    or len(sheet['rows']) > 20):
                raise ValueError('invalid parser preview')
            for row in sheet['rows']:
                if not isinstance(row, list) or len(row) > 200 or any(
                    not isinstance(cell, dict) or set(cell) != {'cell', 'value'}
                    or any(not isinstance(value, str) for value in cell.values()) for cell in row
                ):
                    raise ValueError('invalid parser preview')
    elif not isinstance(result['errors'], list) or not isinstance(result['metadata'], dict):
        raise ValueError('invalid parser mapping')
    return result


def _resident_memory(pid):
    if sys.platform.startswith('linux'):
        try:
            status = Path(f'/proc/{pid}/status').read_text()
            for line in status.splitlines():
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) * 1024
        except FileNotFoundError:
            return None
        raise ValueError('memory monitoring unavailable')
    if sys.platform == 'darwin':
        result = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(pid)],
                                capture_output=True, text=True, timeout=1, check=False)
        if result.returncode == 1 and not result.stdout.strip():
            return None  # Child exited between poll and sample.
        if result.returncode != 0 or not result.stdout.strip().isdigit():
            raise ValueError('memory monitoring unavailable')
        return int(result.stdout.strip()) * 1024
    raise ValueError('memory monitoring unavailable')


def _stop_group(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        child.wait()


def run_parser(operation, raw, *, filename='', mime='', mapping=None):
    """Only named parser operations execute; no caller-supplied child command."""
    if operation not in OPERATIONS:
        raise ValueError('unsupported report parser operation')
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('report exceeds 10 MB limit')
    request = {'operation': operation, 'raw': base64.b64encode(raw).decode('ascii'),
               'filename': filename, 'mime': mime, 'mapping': mapping}
    payload = json.dumps(request, allow_nan=False).encode('utf-8')
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError('report parser request exceeds limit')
    environment = {'PYTHONPATH': str(Path(__file__).resolve().parents[2]),
                   'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1',
                   'LANG': 'C.UTF-8'}
    # TemporaryFile is private/unlinked. No source filename becomes a disk path,
    # and source bytes/errors are never included in the command or environment.
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        source.write(payload)
        source.seek(0)
        child = None
        try:
            child = subprocess.Popen(
                [sys.executable, '-m', 'app.ingest.report_parser'],
                stdin=source, stdout=output, stderr=errors, shell=False,
                start_new_session=True, close_fds=True, cwd=tempfile.gettempdir(), env=environment,
            )
            deadline = time.monotonic() + WALL_SECONDS
            while True:
                if output.tell() > MAX_OUTPUT_BYTES or errors.tell() > MAX_OUTPUT_BYTES:
                    raise ValueError('report parser output exceeds limit')
                if time.monotonic() >= deadline:
                    raise ValueError('report parsing exceeded time limit')
                running = child.poll() is None
                if running:
                    resident = _resident_memory(child.pid)
                    if resident is None and child.poll() is None:
                        raise ValueError('report parser memory monitoring unavailable')
                    if resident is not None and resident > MAX_MEMORY_BYTES:
                        raise ValueError('report parser memory exceeds limit')
                if not running:
                    break
                try:
                    child.wait(timeout=POLL_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
            if child.returncode:
                raise ValueError('report parser failed safely')
            output.seek(0)
            body = _json_loads(output.read(MAX_OUTPUT_BYTES + 1))
            if not isinstance(body, dict) or set(body) != {'ok', 'result', 'error'}:
                raise ValueError('report parser returned invalid output')
            if body['ok'] is False and body['result'] is None and isinstance(body['error'], str):
                raise ValueError(_safe_error(body['error']))
            if body['ok'] is not True or body['error'] is not None:
                raise ValueError('report parser returned invalid output')
            return _validate_result(operation, body['result'])
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('report parser unavailable or failed safely') from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError('report parser returned invalid output') from exc
        finally:
            if child is not None:
                # Kill the isolated process group even after the leader exited;
                # an unexpected descendant must not survive an intake operation.
                _stop_group(child)


def _apply_limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (WALL_SECONDS, WALL_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
    elif sys.platform != 'darwin':
        raise ValueError('report parser isolation is unavailable')


def _execute(request):
    if (not isinstance(request, dict)
            or set(request) != {'operation', 'raw', 'filename', 'mime', 'mapping'}
            or request['operation'] not in OPERATIONS
            or not all(isinstance(request[key], str) for key in ('raw', 'filename', 'mime'))):
        raise ValueError('invalid report parser request')
    raw = base64.b64decode(request['raw'], validate=True)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError('report exceeds 10 MB limit')
    operation = request['operation']
    if operation == 'parse':
        from .reports import _parse_bytes_local
        parts, warnings, kind = _parse_bytes_local(raw, request['filename'], request['mime'])
        return {'parts': parts, 'warnings': warnings, 'kind': kind}
    from .report_mapping import MappingSpec, _mapped_rows_local, _preview_local
    if operation == 'preview':
        return {'sheets': _preview_local(raw)}
    parts, errors, metadata = _mapped_rows_local(raw, MappingSpec.model_validate(request['mapping']))
    return {'parts': parts, 'errors': errors, 'metadata': metadata}


def _main():
    try:
        _apply_limits()
        payload = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(payload) > MAX_REQUEST_BYTES:
            raise ValueError('report parser request exceeds limit')
        request = _json_loads(payload)
        result = _validate_result(request['operation'], _execute(request))
        response = {'ok': True, 'result': result, 'error': None}
    except ValueError as exc:
        response = {'ok': False, 'result': None, 'error': _safe_error(str(exc))}
    except Exception:
        response = {'ok': False, 'result': None, 'error': 'report parser failed safely'}
    encoded = json.dumps(response, allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_OUTPUT_BYTES:
        encoded = b'{"ok":false,"result":null,"error":"report parser output exceeds limit"}'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    _main()
