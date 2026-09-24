from datetime import datetime, timedelta, timezone
import hashlib, secrets
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from ...db.models import Project, ProjectMembership, Session, User
from ...db.passwords import verify_password
from ...db.session import get_session
from ...settings import get_settings
from ..dependencies import current_user, require_csrf

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "progress_session"
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)

def digest(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()

@router.post("/login")
def login(body: LoginRequest, response: Response, db: DBSession = Depends(get_session)):
    user = db.scalar(select(User).where(User.username == body.username, User.is_active.is_(True)))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(Session(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf), expires_at=datetime.now(timezone.utc) + timedelta(hours=12)))
    response.set_cookie(
        COOKIE, token, httponly=True,
        secure=get_settings().environment == "production",
        samesite="lax", max_age=43200,
    )
    return {"csrf_token": csrf, "user": {"id": str(user.id), "username": user.username, "role": user.role}}

@router.post("/logout", status_code=204)
def logout(response: Response, user: User = Depends(require_csrf), session_token: str | None = Cookie(None, alias=COOKIE), db: DBSession = Depends(get_session)):
    if session_token:
        record = db.get(Session, digest(session_token))
        if record: record.revoked_at = datetime.now(timezone.utc)
        db.commit()
    response.delete_cookie(COOKIE)

@router.get("/me")
def me(user: User = Depends(current_user), db: DBSession = Depends(get_session)):
    projects = db.scalars(
        select(Project)
        .join(ProjectMembership)
        .where(ProjectMembership.user_id == user.id)
        .order_by(Project.name)
    ).all()
    return {
        "id": str(user.id),
        "username": user.username,
        "role": user.role,
        "projects": [{"id": str(project.id), "name": project.name, "timezone": project.timezone} for project in projects],
    }
