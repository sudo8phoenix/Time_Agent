from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ingest import reports
from app.api.endpoints.reports import _multipart_input
from fastapi import HTTPException
from starlette.datastructures import UploadFile
from io import BytesIO
import asyncio


class FakeDB:
    def __init__(self, *, fail_flush=False):
        self.added = []
        self.fail_flush = fail_flush

    def scalar(self, _query):
        return None

    def add(self, value):
        self.added.append(value)

    def flush(self):
        if self.fail_flush:
            raise RuntimeError("flush failed")
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()


def test_storage_write_failure_removes_pending_and_final_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "get_settings", lambda: SimpleNamespace(upload_dir=str(tmp_path)))
    target = tmp_path / "pending.txt"

    def fail_replace(_self, _target):
        raise OSError("disk full")

    monkeypatch.setattr(type(target), "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        reports._store_original("pending.txt", b"hello")
    assert not target.exists()
    assert not (tmp_path / "pending.txt.pending").exists()


def test_flush_failure_compensates_only_new_original(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "get_settings", lambda: SimpleNamespace(upload_dir=str(tmp_path)))
    project = SimpleNamespace(id=uuid4())
    db = FakeDB(fail_flush=True)

    with pytest.raises(RuntimeError, match="flush failed"):
        reports.ingest_report(db, project, b"Daily progress", filename="daily.txt")

    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
    assert len(db.added) == 1


def test_duplicate_reuses_existing_without_touching_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "get_settings", lambda: SimpleNamespace(upload_dir=str(tmp_path)))
    existing = object()

    class DuplicateDB(FakeDB):
        def scalar(self, _query):
            return existing

    db = DuplicateDB()
    result, reused = reports.ingest_report(db, SimpleNamespace(id=uuid4()), b"same", filename="same.txt")
    assert result is existing
    assert reused is True
    assert db.added == []
    assert list(tmp_path.rglob("*")) == []


def test_successful_ingest_preserves_paragraph_locators_and_final_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "get_settings", lambda: SimpleNamespace(upload_dir=str(tmp_path)))
    db = FakeDB()
    report, reused = reports.ingest_report(
        db, SimpleNamespace(id=uuid4()), b"First paragraph\n\nSecond paragraph", filename="daily.txt"
    )
    assert reused is False
    fragments = [item for item in db.added if item.__class__.__name__ == "Fragment"]
    assert [item.locator for item in fragments] == ["paragraph:1", "paragraph:2"]
    assert list(path for path in tmp_path.rglob("*") if path.is_file())
    assert not list(tmp_path.rglob("*.pending"))


def test_duplicate_keeps_preexisting_original_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "get_settings", lambda: SimpleNamespace(upload_dir=str(tmp_path)))
    project_id = uuid4()
    key = f"{project_id}/old-same.txt"
    old = tmp_path / key
    old.parent.mkdir(parents=True)
    old.write_bytes(b"same")

    class DuplicateDB(FakeDB):
        def scalar(self, _query):
            return SimpleNamespace(id=uuid4(), file_id=uuid4())

    reports.ingest_report(DuplicateDB(), SimpleNamespace(id=project_id), b"same", filename="same.txt")
    assert old.read_bytes() == b"same"


def test_multipart_rejects_conflicting_file_and_text():
    upload = UploadFile(file=BytesIO(b"file"), filename="x.txt")
    with pytest.raises(HTTPException) as error:
        asyncio.run(_multipart_input({"file": upload, "text": "also text"}))
    assert error.value.detail["code"] == "REPORT_INPUT_AMBIGUOUS"


def test_multipart_rejects_missing_input_and_invalid_date():
    with pytest.raises(HTTPException) as missing:
        asyncio.run(_multipart_input({}))
    assert missing.value.detail["code"] == "REPORT_INPUT_REQUIRED"
    with pytest.raises(HTTPException) as invalid_date:
        asyncio.run(_multipart_input({"text": "report", "report_date": "2026-99-99"}))
    assert invalid_date.value.detail["code"] == "REPORT_INVALID"
