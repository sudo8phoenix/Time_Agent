"""Isolated MPXJ probe runner used before format-specific readers are added."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT_BYTES = 50 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ParserRuntimeError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _run_json_child(command: list[str], timeout_seconds: int) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSER_UNAVAILABLE", "Python parser subprocess is unavailable."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_TIMEOUT", "Native schedule parsing exceeded the 30-second limit."
        ) from exc
    if (
        len(completed.stdout.encode()) > MAX_OUTPUT_BYTES
        or len(completed.stderr.encode()) > MAX_OUTPUT_BYTES
    ):
        raise ParserRuntimeError(
            "SCHEDULE_PARSE_FAILED", "Native parser output exceeded the 50 MiB limit."
        )
    if completed.returncode:
        message = (
            completed.stderr.strip()
            or completed.stdout.strip()
            or "Native parser failed without output."
        )
        try:
            payload = json.loads(_json_result_line(completed.stdout))
            message = str(payload.get("message", message))
            code = str(payload.get("code", "SCHEDULE_PARSE_FAILED"))
        except json.JSONDecodeError:
            code = "SCHEDULE_PARSE_FAILED"
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

        mpxj.startJVM(convertStrings=True)
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
