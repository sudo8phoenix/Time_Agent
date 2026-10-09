from types import SimpleNamespace
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.api.dependencies import project_access, current_user
from app.db.session import get_session
from app.db.models import ScheduleVersion


def test_saved_staged_import_returns_activation_metadata():
    project = SimpleNamespace(id=uuid4())
    record = SimpleNamespace(id=uuid4(), project_id=project.id, revision=2, state="staged", source_format="p6_xer", parser_version="test", selected_source_project_id="source", preview={}, reviewed_mapping={}, staged_schedule_version_id=uuid4(), error_code=None)
    class Database:
        def scalar(self, statement):
            return record
        def get(self, model, key):
            assert model is ScheduleVersion and key == record.staged_schedule_version_id
            return SimpleNamespace(id=key, version_number=3)
    def database_session():
        yield Database()
    app.dependency_overrides[get_session] = database_session
    app.dependency_overrides[project_access] = lambda: project
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=uuid4())
    try:
        response = TestClient(app).get(f"/api/v1/projects/{project.id}/schedule-imports/{record.id}")
        assert response.status_code == 200
        assert response.json()["version"] == 3
        assert response.json()["schedule_version_id"] == str(record.staged_schedule_version_id)
    finally:
        for dependency in (get_session, project_access, current_user):
            app.dependency_overrides.pop(dependency, None)
