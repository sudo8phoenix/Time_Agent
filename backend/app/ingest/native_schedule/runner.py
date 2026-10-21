"""Isolated MPXJ probe runner used before format-specific readers are added."""

from __future__ import annotations

import argparse
import json
import math
import os
import selectors
import signal
import time
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_BYTES = 50 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
JVM_OPTIONS = ("-Xmx512m", "-XX:MaxMetaspaceSize=256m", "-XX:MaxDirectMemorySize=128m",
               "-XX:-CreateCoredumpOnCrash")


def _child_environment(directory: str) -> dict[str, str]:
    """Do not forward service credentials or Python/Java injection options."""
    directory = str(Path(directory).resolve())
    env = {key: os.environ[key] for key in ("PATH", "JAVA_HOME", "LANG", "LC_ALL",
           "SYSTEMROOT") if key in os.environ}
    env.update(HOME=directory, TMPDIR=directory, TMP=directory, TEMP=directory,
               PYTHONPATH=str(Path(__file__).resolve().parents[3]))
    return env


def _resident_memory(pid: int) -> int | None:
    # Shared platform implementation; Linux /proc and Darwin ps fail closed.
    from app.ingest.report_parser import _resident_memory as sample
    return sample(pid)


@dataclass
class ParserRuntimeError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _capture_child(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess:
    """Drain both pipes concurrently, retaining at most the cap per stream.

    Pipe backpressure bounds unread output; no unbounded communicate() capture or
    temporary output files are used. All exits reap the isolated process group.
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Parser timeout must be finite and positive")
    deadline = time.monotonic() + timeout_seconds
    with tempfile.TemporaryDirectory(prefix="native-parser-") as directory, subprocess.Popen(
                          [sys.executable, "-m", "app.ingest.native_schedule.resource_child",
                           *command[1:]], shell=False, stdin=subprocess.DEVNULL,
                          env=_child_environment(directory), cwd=directory,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True, close_fds=True) as child:
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            with selectors.DefaultSelector() as selector:
                for name in buffers:
                    stream = getattr(child, name)
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, name)
                while selector.get_map() or child.poll() is None:
                    if child.poll() is None:
                        try:
                            resident = _resident_memory(child.pid)
                        except (OSError, ValueError, subprocess.SubprocessError) as exc:
                            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED",
                                                     "Native parser memory supervision failed.") from exc
                        if resident is None and child.poll() is None:
                            raise ParserRuntimeError("SCHEDULE_PARSE_FAILED",
                                                     "Native parser memory supervision failed.")
                        if resident is not None and resident > MAX_MEMORY_BYTES:
                            raise ParserRuntimeError("SCHEDULE_TOO_LARGE",
                                                     "Native parser exceeded its memory limit.")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout_seconds)
                    for key, _ in selector.select(min(remaining, 0.05)):
                        target = buffers[key.data]
                        chunk = os.read(key.fd, min(65536, MAX_OUTPUT_BYTES - len(target) + 1))
                        if not chunk:
                            selector.unregister(key.fileobj)
                        elif len(target) + len(chunk) > MAX_OUTPUT_BYTES:
                            raise ParserRuntimeError(
                                "SCHEDULE_PARSE_FAILED",
                                "Native parser output exceeded the 50 MiB limit.",
                            )
                        else:
                            target.extend(chunk)
                return subprocess.CompletedProcess(
                    command, child.returncode,
                    buffers["stdout"].decode("utf-8"), buffers["stderr"].decode("utf-8"),
                )
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def _run_json_child(command: list[str], timeout_seconds: int) -> dict[str, object]:
    try:
        completed = _capture_child(command, timeout_seconds)
    except OSError as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSER_UNAVAILABLE", "Python parser subprocess is unavailable."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_TIMEOUT", "Native schedule parsing exceeded its time limit."
        ) from exc
    except UnicodeDecodeError as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", "Native parser returned invalid UTF-8."
        ) from exc
    if completed.returncode:
        # Dependency diagnostics can echo source text, paths and environment.
        # Only stable public codes cross this boundary; raw streams stay private.
        messages = {
            "SCHEDULE_PARSER_UNAVAILABLE": "Native schedule parser is unavailable.",
            "SCHEDULE_FORMAT_UNSUPPORTED": "Native schedule format is unsupported.",
            "SCHEDULE_FORMAT_MISMATCH": "Native schedule format does not match the source.",
            "SCHEDULE_SOURCE_PROJECT_UNKNOWN": "Select a valid source project.",
            "SCHEDULE_TOO_LARGE": "Native schedule exceeds supported limits.",
            "SCHEDULE_PARSE_FAILED": "Native schedule parsing failed safely.",
        }
        code = "SCHEDULE_PARSE_FAILED"
        try:
            payload = json.loads(_json_result_line(completed.stdout))
            if isinstance(payload, dict) and payload.get("code") in messages:
                code = payload["code"]
        except (json.JSONDecodeError, TypeError):
            pass
        message = messages[code]
        raise ParserRuntimeError(code, message)
    try:
        payload = json.loads(_json_result_line(completed.stdout))
    except json.JSONDecodeError as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", "Native parser returned invalid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", "Native parser returned an invalid result."
        )
    return payload


def _json_result_line(output: str) -> str:
    """Ignore bounded JVM logger chatter while requiring a JSON result record."""
    for line in reversed(output.splitlines()):
        if line.lstrip().startswith("{"):
            return line
    raise json.JSONDecodeError("No JSON result line", output, 0)


def probe_schedule(
    path: Path, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> dict[str, object]:
    """Read a locally generated path in a child process and return only probe metadata."""
    if not path.is_file():
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"Schedule file does not exist: {path.name}"
        )
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ParserRuntimeError(
            "SCHEDULE_TOO_LARGE", "Native schedule input exceeds the 10 MiB limit."
        )
    return _run_json_child(
        [sys.executable, "-m", "app.ingest.native_schedule.runner", "--probe", str(path.resolve())],
        timeout_seconds,
    )


def run_reader_module(
    module: str,
    path: Path,
    source_project_id: str | None = None,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Run a format-specific reader in the same bounded subprocess policy as MPXJ probes."""
    if not path.is_file():
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"Schedule file does not exist: {path.name}"
        )
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ParserRuntimeError(
            "SCHEDULE_TOO_LARGE", "Native schedule input exceeds the 10 MiB limit."
        )
    command = [sys.executable, "-m", module, "--child", "--input", str(path.resolve())]
    if source_project_id is not None:
        command.extend(["--source-project-id", source_project_id])
    return _run_json_child(command, timeout_seconds)


def _child_probe(path: Path) -> dict[str, object]:
    try:
        import mpxj

        mpxj.startJVM(*JVM_OPTIONS, convertStrings=True)
        from org.mpxj.reader import UniversalProjectReader
    except Exception as exc:  # the child returns a structured availability error to its parent
        raise ParserRuntimeError(
            "SCHEDULE_PARSER_UNAVAILABLE", f"MPXJ/Java is unavailable: {exc}"
        ) from exc
    try:
        project = UniversalProjectReader().read(str(path))
    except Exception as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"MPXJ could not read {path.name}: {exc}"
        ) from exc
    if project is None:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", f"MPXJ returned no project for {path.name}."
        )
    properties = project.getProjectProperties()
    return {
        "parser_version": "mpxj-14.0.0",
        "project_name": str(properties.getName() or ""),
        "project_unique_id": str(properties.getUniqueID() or ""),
        "task_count": int(project.getTasks().size()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded MPXJ native-schedule probe")
    parser.add_argument("--probe", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(_child_probe(args.probe)))
        return 0
    except ParserRuntimeError as exc:
        print(json.dumps({"code": exc.code, "message": exc.message}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
