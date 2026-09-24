"""Create a demo reviewer/project without resetting existing data."""
import argparse
import getpass
import os
from pathlib import Path

from sqlalchemy import select

from app.db.models import Project, ProjectMembership, User
from app.db.passwords import hash_password
from app.db.session import session_factory
from app.ingest.schedules import stage_schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="demo-reviewer")
    args = parser.parse_args()
    with session_factory.begin() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            password = os.environ.get("DEMO_PASSWORD") or getpass.getpass("New demo password: ")
            if len(password) < 12:
                raise SystemExit("Use at least 12 characters for the demo password.")
            user = User(username=args.username, password_hash=hash_password(password), role="reviewer")
            db.add(user)
            db.flush()
        elif user.role != "reviewer" or not user.is_active:
            raise SystemExit("Existing account is not an active reviewer; no changes made.")
        project = db.scalar(select(Project).join(ProjectMembership).where(
            Project.name == "DEMO-UTILITY-01", ProjectMembership.user_id == user.id))
        if project is None:
            project = Project(name="DEMO-UTILITY-01", timezone="Asia/Kolkata")
            db.add(project)
            db.flush()
            db.add(ProjectMembership(project_id=project.id, user_id=user.id))
            raw = (Path(__file__).resolve().parents[1] / "data/synthetic/schedules/demo-utility-01.csv").read_bytes()
            version, _, errors, _ = stage_schedule(db, project, raw)
            if errors:
                raise RuntimeError(errors)
            version.state = "active"
            project.active_schedule_version_id = version.id
        print(f"Demo ready: {args.username}, project {project.id}. Existing passwords/progress preserved.")


if __name__ == "__main__":
    main()
