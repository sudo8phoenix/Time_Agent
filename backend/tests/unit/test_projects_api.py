from app.api.endpoints.projects import CreateProjectRequest


def test_project_request_rejects_unknown_fields():
    try:
        CreateProjectRequest.model_validate({"name": "Demo", "unexpected": True})
    except Exception:
        return
    raise AssertionError("project request must reject unknown fields")
