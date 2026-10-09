from uuid import uuid4
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.base import Base
from app.db.models import User, Project, ProjectMembership, Report, Job, Observation, Proposal
from app.db.session import get_session
from app.api.dependencies import current_user


def test_history_pagination_pending_filter_and_project_isolation():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        user = User(username="reviewer", password_hash="unused", role="reviewer")
        project, foreign = Project(name="Owned"), Project(name="Foreign")
        db.add_all([user, project, foreign]); db.flush()
        db.add(ProjectMembership(user_id=user.id, project_id=project.id))
        jobs = []
        for index in range(3):
            owner = foreign if index == 2 else project
            report = Report(project_id=owner.id, content_hash=str(index), source_label=f"Report {index}")
            db.add(report); db.flush()
            job = Job(project_id=owner.id, report_id=report.id, schedule_version_id=uuid4(), state="ready_for_review", created_at=datetime.now(timezone.utc) + timedelta(seconds=index))
            db.add(job); db.flush(); jobs.append(job)
        observation = Observation(job_id=jobs[0].id, ordinal=1)
        db.add(observation); db.flush()
        db.add(Proposal(project_id=project.id, observation_id=observation.id, review_state="pending"))
        db.commit()
    def database_session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_session] = database_session
    app.dependency_overrides[current_user] = lambda: user
    try:
        client = TestClient(app)
        first = client.get(f"/api/v1/jobs?project_id={project.id}&limit=1").json()
        assert first["next_offset"] == 1
        assert first["items"][0]["report_name"] == "Report 1"
        second = client.get(f"/api/v1/jobs?project_id={project.id}&limit=1&offset=1").json()
        assert second["next_offset"] is None
        assert second["items"][0]["report_name"] == "Report 0"
        pending = client.get(f"/api/v1/jobs?project_id={project.id}&pending_only=true").json()
        assert len(pending["items"]) == 1 and pending["items"][0]["pending_count"] == 1
        assert client.get(f"/api/v1/jobs?project_id={foreign.id}").status_code == 403
        assert client.get(f"/api/v1/jobs?project_id={project.id}&limit=0").status_code == 422
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(current_user, None)
        engine.dispose()
