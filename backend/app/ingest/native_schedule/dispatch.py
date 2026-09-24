"""Safe native-schedule format detection and reader dispatch."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from app.ingest.native_schedule.microsoft import read_schedule as read_microsoft
from app.ingest.native_schedule.primavera import read_schedule as read_primavera
from app.ingest.native_schedule.runner import ParserRuntimeError
from app.schemas.native_schedule import SchedulePreview


def preview_schedule(path: Path, source_project_id: str | None = None) -> SchedulePreview:
    suffix = path.suffix.lower()
    if suffix == ".xer":
        return read_primavera(path, source_project_id)
    if suffix == ".mpp":
        return read_microsoft(path, source_project_id)
    if suffix != ".xml":
        raise ParserRuntimeError(
            "SCHEDULE_FORMAT_UNSUPPORTED",
            "Supported native formats are XER, P6 XML, MSPDI XML and MPP.",
        )
    raw = path.read_bytes()
    if b"<!doctype" in raw.lower():
        raise ParserRuntimeError(
            "SCHEDULE_FORMAT_MISMATCH", "XML DTD and external entities are not accepted."
        )
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ParserRuntimeError("SCHEDULE_PARSE_FAILED", "XML is not well formed.") from exc
    if root.tag == "{http://schemas.microsoft.com/project}Project":
        return read_microsoft(path, source_project_id)
    if (
        root.tag.endswith("Project")
        or root.tag.endswith("Projects")
        or root.tag.endswith("APIBusinessObjects")
    ):
        return read_primavera(path, source_project_id)
    raise ParserRuntimeError(
        "SCHEDULE_FORMAT_MISMATCH", "XML root does not identify P6 PMXML or Microsoft MSPDI."
    )
