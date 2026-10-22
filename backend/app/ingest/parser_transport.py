"""Bounded Unix-socket transport to the credential-free Docker parser service."""
import json
import os
import socket
import struct
import time

MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
DEFAULT_SOCKET = '/run/site-parser/parser.sock'


class ParserServiceUnavailable(ValueError):
    pass


def _read_exact(connection, size, deadline):
    chunks = bytearray()
    while len(chunks) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('parser service deadline')
        connection.settimeout(remaining)
        part = connection.recv(min(65536, size - len(chunks)))
        if not part:
            raise ValueError('incomplete parser frame')
        chunks.extend(part)
    return bytes(chunks)


def read_frame(connection, limit, deadline):
    size = struct.unpack('!I', _read_exact(connection, 4, deadline))[0]
    if size > limit:
        raise ValueError('parser frame exceeds limit')
    return json.loads(_read_exact(connection, size, deadline),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('invalid JSON')))


def write_frame(connection, value, limit, deadline):
    raw = json.dumps(value, allow_nan=False).encode('utf-8')
    if len(raw) > limit:
        raise ValueError('parser frame exceeds limit')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('parser service deadline')
    connection.settimeout(remaining)
    connection.sendall(struct.pack('!I', len(raw)) + raw)


def request_parser(payload, *, timeout=45):
    deadline = time.monotonic() + timeout
    path = os.environ.get('PARSER_SOCKET_PATH', DEFAULT_SOCKET)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(path)
            write_frame(connection, payload, MAX_REQUEST_BYTES, deadline)
            result = read_frame(connection, MAX_RESPONSE_BYTES, deadline)
        if not isinstance(result, dict) or set(result) != {'ok', 'result', 'error'}:
            raise ValueError('invalid parser response')
        return result
    except (OSError, ValueError, UnicodeError) as exc:
        raise ParserServiceUnavailable('Isolated document parser service is unavailable.') from exc
