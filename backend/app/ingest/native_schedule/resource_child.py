"""Trusted Python entrypoint: apply kernel limits before importing native readers.

RSS is sampled by the parent rather than limiting JVM virtual address reservations.
The parent runs inside the network-disabled, read-only Docker parser service.
"""
from __future__ import annotations

import resource
import runpy
import sys


def apply_limits() -> None:
    from .runner import DEFAULT_TIMEOUT_SECONDS, MAX_OUTPUT_BYTES
    resource.setrlimit(resource.RLIMIT_CPU, (DEFAULT_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main() -> None:
    apply_limits()
    arguments = sys.argv[1:]
    if len(arguments) >= 2 and arguments[0] == '-m':
        sys.argv = arguments[1:]
        runpy.run_module(arguments[1], run_name='__main__', alter_sys=True)
    elif len(arguments) == 2 and arguments[0] == '-c':
        sys.argv = ['-c']
        exec(compile(arguments[1], '<native-child>', 'exec'), {'__name__': '__main__'})
    else:
        raise SystemExit('Unsupported native parser invocation')


if __name__ == '__main__':
    main()
