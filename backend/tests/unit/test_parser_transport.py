"""Protocol limits and fail-closed behavior require no Docker daemon."""
import socket
import struct
import time

import pytest

from app.ingest.parser_transport import read_frame, request_parser, ParserServiceUnavailable
from app.ingest.parser_service import dispatch


def test_missing_service_has_no_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv('PARSER_SOCKET_PATH', str(tmp_path / 'absent.sock'))
    with pytest.raises(ParserServiceUnavailable, match='unavailable'):
        request_parser({'kind': 'health'}, timeout=0.1)


@pytest.mark.parametrize('body', [struct.pack('!I', 1000),
    struct.pack('!I', 3) + b'NaN', struct.pack('!I', 4) + b'bad!'])
def test_invalid_or_oversized_frames_are_rejected_before_dispatch(body):
    incoming, outgoing = socket.socketpair()
    try:
        outgoing.sendall(body)
        outgoing.shutdown(socket.SHUT_WR)
        with pytest.raises(ValueError):
            read_frame(incoming, 100, time.monotonic() + 1)
    finally:
        incoming.close()
        outgoing.close()


def test_arbitrary_module_rejected_before_subprocess(monkeypatch):
    monkeypatch.setattr('app.ingest.parser_service._run_json_child',
                        lambda *args: pytest.fail('arbitrary execution'))
    with pytest.raises(ValueError):
        dispatch({'kind': 'native', 'module': 'subprocess', 'raw': '',
                  'suffix': '.xml', 'source_project_id': None})
