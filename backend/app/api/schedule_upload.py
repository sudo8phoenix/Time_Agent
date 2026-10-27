"""Authenticated schedule multipart intake, bounded before temporary-file writes."""
from fastapi import HTTPException, Request
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

MAX_SCHEDULE_BYTES = 10 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_SCHEDULE_BYTES + 64 * 1024

# Documentation only: a File parameter would parse the body before authorization.
SCHEDULE_UPLOAD_OPENAPI = {"requestBody": {"required": True, "content": {
    "multipart/form-data": {"schema": {"type": "object", "required": ["upload"],
        "properties": {"upload": {"type": "string", "format": "binary"}}}}
}}}


class _UploadTooLarge(MultiPartException):
    pass


class _ScheduleParser(MultiPartParser):
    def on_part_begin(self):
        self._file_bytes = 0
        super().on_part_begin()

    def on_part_data(self, data, start, end):
        if self._current_part.file is not None:
            self._file_bytes += end - start
            if self._file_bytes > MAX_SCHEDULE_BYTES:
                raise _UploadTooLarge("schedule exceeds 10 MiB")
        super().on_part_data(data, start, end)


async def read_schedule_upload(request: Request) -> tuple[bytes, str, str]:
    """Called inside the handler, after session/membership/reviewer/CSRF checks."""
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        raise HTTPException(422, detail={"code": "SCHEDULE_UPLOAD_INVALID"})
    length = request.headers.get("content-length", "")
    if length:
        try:
            declared_size = int(length)
        except ValueError as exc:
            raise HTTPException(400, detail={"code": "SCHEDULE_UPLOAD_INVALID"}) from exc
        if declared_size < 0:
            raise HTTPException(400, detail={"code": "SCHEDULE_UPLOAD_INVALID"})
        if declared_size > MAX_MULTIPART_BYTES:
            raise HTTPException(413, detail={"code": "SCHEDULE_TOO_LARGE"})

    async def bounded_stream():
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_MULTIPART_BYTES:
                raise _UploadTooLarge("schedule multipart body exceeds limit")
            yield chunk

    parser = _ScheduleParser(request.headers, bounded_stream(), max_files=1, max_fields=0)
    form = None
    try:
        try:
            form = await parser.parse()
        except _UploadTooLarge as exc:
            raise HTTPException(413, detail={"code": "SCHEDULE_TOO_LARGE"}) from exc
        except (MultiPartException, MultipartParseError) as exc:
            raise HTTPException(422, detail={"code": "SCHEDULE_UPLOAD_INVALID"}) from exc
        upload = form.get("upload")
        if not isinstance(upload, UploadFile):
            raise HTTPException(422, detail={"code": "SCHEDULE_UPLOAD_INVALID"})
        raw = await upload.read(MAX_SCHEDULE_BYTES + 1)
        if len(raw) > MAX_SCHEDULE_BYTES:
            raise HTTPException(413, detail={"code": "SCHEDULE_TOO_LARGE"})
        return raw, upload.filename or "schedule", upload.content_type or "application/octet-stream"
    finally:
        try:
            if form is not None:
                await form.close()
        finally:
            # Pinned Starlette's file inventory also includes unfinished parts
            # absent from FormData. Close them on truncation/disconnect/cancel.
            for file in parser._files_to_close_on_error:
                file.close()
