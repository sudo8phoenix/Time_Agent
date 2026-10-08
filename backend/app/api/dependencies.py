from datetime import datetime, timezone
import hashlib
from fastapi import Cookie, Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from ..db.models import Project, ProjectMembership, Session, User
from ..db.session import get_session

def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def current_user(session_token: str | None = Cookie(None, alias="progress_session"), db: DBSession = Depends(get_session)) -> User:
    if not session_token:
        raise HTTPException(401, "Authentication required")
    record = db.get(Session, _digest(session_token))
    if not record or record.revoked_at or record.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(401, "Invalid or expired session")
    return record.user

def require_csrf(session_token: str | None = Cookie(None, alias="progress_session"), csrf_token: str | None = Header(None, alias="X-CSRF-Token"), db: DBSession = Depends(get_session)) -> User:
    user = current_user(session_token, db)
    record = db.get(Session, _digest(session_token))
    if not csrf_token or not record or _digest(csrf_token) != record.csrf_hash:
        raise HTTPException(403, "CSRF validation failed")
    return user

def require_reviewer(user: User = Depends(require_csrf)) -> User:
    if user.role != "reviewer":
        raise HTTPException(403, "Reviewer role required")
    return user

def current_reviewer(user: User = Depends(current_user)) -> User:
    """Authorize safe reviewer reads without requiring a CSRF header."""
    if user.role != "reviewer":
        raise HTTPException(403, "Reviewer role required")
    return user

def project_access(project_id: str, user: User = Depends(current_user), db: DBSession = Depends(get_session)) -> Project:
    project = db.scalar(
        select(Project)
        .join(ProjectMembership)
        .where(Project.id == project_id, ProjectMembership.user_id == user.id)
    )
    if not project:
        raise HTTPException(403, "Project access denied")
    return project
