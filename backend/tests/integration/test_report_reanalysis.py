from uuid import UUID, uuid4

from backend.tests.integration.test_postgres_workflow import SCHEDULE, _login, client as isolated_client
from app.db.models import ProjectMembership, User
from app.db.passwords import hash_password


def test_reanalysis_creates_audited_linked_run_and_retries_idempotently(isolated_client):
    browser, factory = isolated_client
    headers, _ = _login(browser, factory)
    project_response = browser.post("/api/v1/projects", json={"name": f"Reanalysis {uuid4().hex}"}, headers=headers)
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    schedule = browser.post(f"/api/v1/projects/{project_id}/schedules", files={
        "upload": ("demo-utility-01.csv", SCHEDULE.read_bytes(), "text/csv")
    }, headers=headers)
    assert schedule.status_code == 200
    activation = browser.post(f"/api/v1/projects/{project_id}/schedules/1/activate",
                              json={"expected_active_version": None}, headers=headers)
    assert activation.status_code == 200
    intake = browser.post(f"/api/v1/projects/{project_id}/reports",
                          json={"text": "Installed pipe in Area A", "report_date": "2026-10-01"}, headers=headers)
    assert intake.status_code == 202

    body = {"reason": "Review extraction with updated prompt configuration", "idempotency_key": f"rerun-{uuid4()}"}
    first = browser.post(f"/api/v1/projects/{project_id}/reports/{intake.json()['report_id']}/reanalysis",
                         json=body, headers=headers)
    retry = browser.post(f"/api/v1/projects/{project_id}/reports/{intake.json()['report_id']}/reanalysis",
                         json=body, headers=headers)
    assert first.status_code == retry.status_code == 202
    assert first.json()["job_id"] != intake.json()["job_id"]
    assert first.json()["parent_job_id"] == intake.json()["job_id"]
    assert retry.json()["job_id"] == first.json()["job_id"]
    assert retry.json()["existing"] is True
    assert first.json()["reanalysis"]["actor_id"]
    assert first.json()["reanalysis"]["reason"] == body["reason"]
    assert first.json()["reanalysis"]["config"]["execution_mode"] in {"legacy", "graph"}
    status = browser.get(f"/api/v1/jobs/{first.json()['job_id']}")
    assert status.status_code == 200
    assert status.json()["parent_job_id"] == intake.json()["job_id"]
    runs = browser.get(f"/api/v1/projects/{project_id}/reports/{intake.json()['report_id']}/runs")
    assert runs.status_code == 200
    run_rows = runs.json()["items"]
    assert {row["job_id"] for row in run_rows} == {intake.json()["job_id"], first.json()["job_id"]}
    assert next(row for row in run_rows if row["job_id"] == first.json()["job_id"])["parent_job_id"] == intake.json()["job_id"]

    normal_retry = browser.post(f"/api/v1/projects/{project_id}/reports",
                                json={"text": "Installed pipe in Area A", "report_date": "2026-10-01"}, headers=headers)
    assert normal_retry.status_code == 202
    assert normal_retry.json()["job_id"] == intake.json()["job_id"]
    conflicting_reason = browser.post(
        f"/api/v1/projects/{project_id}/reports/{intake.json()['report_id']}/reanalysis",
        json={**body, "reason": "Different reason"}, headers=headers)
    assert conflicting_reason.status_code == 409
    missing_csrf = browser.post(f"/api/v1/projects/{project_id}/reports/{intake.json()['report_id']}/reanalysis",
                                json={"reason": "No CSRF", "idempotency_key": str(uuid4())})
    assert missing_csrf.status_code == 403
    blank_reason = browser.post(
        f"/api/v1/projects/{project_id}/reports/{intake.json()['report_id']}/reanalysis",
        json={"reason": "   ", "idempotency_key": str(uuid4())}, headers=headers)
    assert blank_reason.status_code == 422
    username = f"supervisor-{uuid4().hex}"
    with factory() as db:
        supervisor = User(username=username, password_hash=hash_password("test-password"), role="supervisor")
        db.add(supervisor)
        db.flush()
        db.add(ProjectMembership(project_id=UUID(project_id), user_id=supervisor.id))
        db.commit()
    supervisor_login = browser.post("/api/v1/auth/login", json={"username": username, "password": "test-password"})
    assert supervisor_login.status_code == 200
    supervisor_headers = {"X-CSRF-Token": supervisor_login.json()["csrf_token"]}
    supervisor_attempt = browser.post(
        f"/api/v1/projects/{project_id}/reports/{intake.json()['report_id']}/reanalysis",
        json={"reason": "Supervisor role should be blocked", "idempotency_key": str(uuid4())},
        headers=supervisor_headers)
    assert supervisor_attempt.status_code == 403
