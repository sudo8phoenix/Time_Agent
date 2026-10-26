from app.api.endpoints.projects import CreateProjectRequest
from app.api.endpoints.projects import create_project
from fastapi import HTTPException
import pytest


def test_project_request_rejects_unknown_fields():
    try:
        CreateProjectRequest.model_validate({"name": "Demo", "unexpected": True})
    except Exception:
        return
    raise AssertionError("project request must reject unknown fields")


@pytest.mark.parametrize("timezone", ["/etc/passwd", "../UTC", "Unknown/Timezone"])
def test_invalid_timezone_returns_validation_error_before_writing(timezone):
    with pytest.raises(HTTPException) as exc:
        create_project(CreateProjectRequest(name="Demo", timezone=timezone), None, None)
    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "PROJECT_TIMEZONE_INVALID"}
