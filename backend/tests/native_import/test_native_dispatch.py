from pathlib import Path

import pytest

from app.ingest.native_schedule.dispatch import preview_schedule
from app.ingest.native_schedule.runner import ParserRuntimeError


ROOT = Path(__file__).resolve().parents[4]


def test_dispatches_verified_xer_and_mspdi_xml():
    assert preview_schedule(ROOT / "PROJECT.xer").source_format == "p6_xer"
    fixture = ROOT / "site-progress-agent/backend/tests/fixtures/native_schedule/tiny_mspdi.xml"
    assert preview_schedule(fixture).source_format == "msp_xml"


def test_dispatch_rejects_xml_doctype(tmp_path):
    source = tmp_path / "unsafe.xml"
    source.write_text("<!DOCTYPE Project><Project/>")
    with pytest.raises(ParserRuntimeError) as error:
        preview_schedule(source)
    assert error.value.code == "SCHEDULE_FORMAT_MISMATCH"
