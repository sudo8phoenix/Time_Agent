"""Safe native-schedule format detection and reader dispatch."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from app.ingest.native_schedule.microsoft import _child_read as _read_microsoft
from app.ingest.native_schedule.primavera import _child_read as _read_primavera
from app.ingest.schedule_datasets.gt10_preview import read_schedule as read_gt10
from app.ingest.schedule_datasets.cambridge_preview import read_schedule as read_cambridge
from app.ingest.native_schedule.runner import ParserRuntimeError, run_reader_module
from app.schemas.native_schedule import SchedulePreview


def preview_schedule(path: Path, source_project_id: str | None = None) -> SchedulePreview:
    # Detection itself parses XML/XLSX/JSON, so it belongs inside the container too.
    return SchedulePreview.model_validate(run_reader_module(
        'app.ingest.native_schedule.dispatch', path, source_project_id))


def _preview_schedule_local(path: Path, source_project_id: str | None = None) -> SchedulePreview:
    suffix = path.suffix.lower()
    if suffix == ".xer":
        return SchedulePreview.model_validate(_read_primavera(path, source_project_id))
    if suffix == ".mpp":
        return SchedulePreview.model_validate(_read_microsoft(path, source_project_id))
    if suffix == ".xlsx":
        return read_gt10(path, source_project_id)
    if suffix == ".json":
        return read_cambridge(path, source_project_id)
    if suffix != ".xml":
        raise ParserRuntimeError(
            "SCHEDULE_FORMAT_UNSUPPORTED",
            "Supported native formats are XER, P6 XML, MSPDI XML, MPP, GT10 XLSX and derived Cambridge JSON snapshots.",
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
        return SchedulePreview.model_validate(_read_microsoft(path, source_project_id))
    if (
        root.tag.endswith("Project")
        or root.tag.endswith("Projects")
        or root.tag.endswith("APIBusinessObjects")
    ):
        return SchedulePreview.model_validate(_read_primavera(path, source_project_id))
    raise ParserRuntimeError(
        "SCHEDULE_FORMAT_MISMATCH", "XML root does not identify P6 PMXML or Microsoft MSPDI."
    )


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', action='store_true', required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--source-project-id')
    args = parser.parse_args()
    try:
        print(_preview_schedule_local(args.input, args.source_project_id).model_dump_json())
        return 0
    except ParserRuntimeError as exc:
        print(json.dumps({'code': exc.code}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
