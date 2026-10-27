"""Small in-process multipart regressions; no database, parser service or provider."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import ClientDisconnect, Request

from app.api import schedule_upload as intake
from app.api.dependencies import project_access, require_reviewer
from app.api.endpoints import schedule_imports, schedules
from app.db.session import get_session


PREFIX = (b'--fixture\r\nContent-Disposition: form-data; name="upload"; '
          b'filename="schedule.csv"\r\nContent-Type: text/csv\r\n\r\n')
SUFFIX = b'\r\n--fixture--\r\n'


def request(chunks, *, length=None, disconnect=False):
    pending = iter(chunks)
    reads = []

    async def receive():
        reads.append(True)
        part = next(pending, None)
        if part is None:
            return {"type": "http.disconnect"} if disconnect else {
                "type": "http.request", "body": b"", "more_body": False,
            }
        return {"type": "http.request", "body": part, "more_body": True}

    headers = [(b"content-type", b"multipart/form-data; boundary=fixture")]
    if length is not None:
        headers.append((b"content-length", str(length).encode()))
    return Request({"type": "http", "method": "POST", "headers": headers}, receive), reads


@pytest.fixture
def spools(monkeypatch):
    from starlette import formparsers
    original = formparsers.SpooledTemporaryFile
    files = []

    def tracked(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked)
    monkeypatch.setattr(intake, "MAX_SCHEDULE_BYTES", 16)
    monkeypatch.setattr(intake, "MAX_MULTIPART_BYTES", 2048)
    return files


@pytest.mark.parametrize("route", ["schedules", "schedule-imports"])
@pytest.mark.parametrize("gate,status", [("project", 401), ("project", 403), ("reviewer", 403)])
def test_rejected_authorization_never_parses_multipart(route, gate, status, monkeypatch):
    app = FastAPI()
    app.include_router(schedules.router)
    app.include_router(schedule_imports.router)

    def reject():
        raise HTTPException(status, "denied")

    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[project_access] = reject if gate == "project" else lambda: object()
    app.dependency_overrides[require_reviewer] = reject if gate == "reviewer" else lambda: object()

    async def forbidden(_self):
        pytest.fail("multipart parsing ran before authorization")

    monkeypatch.setattr(intake._ScheduleParser, "parse", forbidden)
    with TestClient(app) as client:
        response = client.post(f"/projects/{uuid4()}/{route}", files={
            "upload": ("schedule.csv", b"dummy", "text/csv"),
        })
    assert response.status_code == status


def test_file_at_limit_is_accepted_and_closed(spools):
    req, _ = request([PREFIX, b"x" * 16, SUFFIX])
    assert asyncio.run(intake.read_schedule_upload(req)) == (b"x" * 16, "schedule.csv", "text/csv")
    assert len(spools) == 1 and spools[0].closed


def test_chunked_file_over_limit_is_rejected_and_partial_spool_closed(spools):
    req, _ = request([PREFIX, b"x" * 8, b"x" * 9, SUFFIX])
    with pytest.raises(HTTPException) as error:
        asyncio.run(intake.read_schedule_upload(req))
    assert error.value.status_code == 413
    assert len(spools) == 1 and spools[0].closed


def test_aggregate_stream_limit_closes_partial_file(spools, monkeypatch):
    monkeypatch.setattr(intake, "MAX_MULTIPART_BYTES", len(PREFIX) + 4)
    req, _ = request([PREFIX, b"x" * 8, SUFFIX])
    with pytest.raises(HTTPException) as error:
        asyncio.run(intake.read_schedule_upload(req))
    assert error.value.status_code == 413
    assert len(spools) == 1 and spools[0].closed


def test_declared_oversize_is_rejected_without_read_or_spool(spools):
    req, reads = request([PREFIX], length=2049)
    with pytest.raises(HTTPException) as error:
        asyncio.run(intake.read_schedule_upload(req))
    assert error.value.status_code == 413
    assert reads == [] and spools == []


def test_disconnect_closes_partial_spool(spools):
    req, _ = request([PREFIX, b"dummy"], disconnect=True)
    with pytest.raises(ClientDisconnect):
        asyncio.run(intake.read_schedule_upload(req))
    assert len(spools) == 1 and spools[0].closed


def test_truncated_multipart_closes_unfinished_part(spools):
    req, _ = request([PREFIX, b"dummy"])
    with pytest.raises(HTTPException) as error:
        asyncio.run(intake.read_schedule_upload(req))
    assert error.value.status_code == 422
    assert len(spools) == 1 and spools[0].closed


def test_invalid_multipart_is_a_client_error(spools):
    req, _ = request([b"not a multipart boundary"])
    with pytest.raises(HTTPException) as error:
        asyncio.run(intake.read_schedule_upload(req))
    assert error.value.status_code == 422
    assert all(file.closed for file in spools)


@pytest.mark.parametrize("route", ["schedules", "schedule-imports"])
def test_authorized_route_passes_original_bytes_and_metadata(route, monkeypatch):
    app = FastAPI()
    app.include_router(schedules.router)
    app.include_router(schedule_imports.router)
    project = SimpleNamespace(id=uuid4())
    reviewer = SimpleNamespace(id=uuid4())
    db = SimpleNamespace(execute=lambda *_: None)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[project_access] = lambda: project
    app.dependency_overrides[require_reviewer] = lambda: reviewer
    seen = []

    def stage(_db, _project, raw):
        seen.append(raw)
        return SimpleNamespace(id=uuid4(), version_number=1, state="staged", activities=[]), "hash", [], False

    def create(_db, _project, raw, **kwargs):
        seen.append((raw, kwargs))
        return object()

    monkeypatch.setattr(schedules, "stage_schedule", stage)
    monkeypatch.setattr(schedule_imports, "create_import", create)
    monkeypatch.setattr(schedule_imports, "_payload", lambda *_: {"ok": True})
    with TestClient(app) as client:
        response = client.post(f"/projects/{project.id}/{route}", files={
            "upload": ("schedule.csv", b"dummy", "text/csv"),
        })
    assert response.status_code in {200, 201}
    assert seen == ([b"dummy"] if route == "schedules" else [(b"dummy", {
        "filename": "schedule.csv", "mime_type": "text/csv", "creator_id": reviewer.id,
    })])
