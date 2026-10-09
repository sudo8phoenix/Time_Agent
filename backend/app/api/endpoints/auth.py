from datetime import datetime, timedelta, timezone
import hashlib, hmac, secrets, threading, time
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from ...db.models import Project, ProjectMembership, Session, User
from ...db.passwords import hash_password, verify_password
from ...db.session import get_session
from ...settings import get_settings
from ..dependencies import current_user, require_csrf

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "progress_session"
_login_lock = threading.Lock()
_login_failures: dict[tuple[str, str], tuple[int, float]] = {}
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 5
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)

def create_session(user: User, response: Response, db: DBSession):
    token = secrets.token_urlsafe(32)
    csrf = csrf_for_session(token)
    db.add(Session(token_hash=digest(token), user_id=user.id, csrf_hash=digest(csrf), expires_at=datetime.now(timezone.utc) + timedelta(hours=12)))
    response.set_cookie(COOKIE, token, httponly=True, secure=get_settings().environment == "production", samesite="lax", max_age=43200)
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": csrf, "user": {"id": str(user.id), "username": user.username, "role": user.role}}

@router.post("/register", status_code=201)
def register(body: RegisterRequest, response: Response, db: DBSession = Depends(get_session)):
    user = User(username=body.username, password_hash=hash_password(body.password), role="reviewer", is_active=True)
    try:
        db.add(user)
        db.flush()
        project = Project(name=f"{body.username}'s project", timezone="Asia/Kolkata")
        db.add(project)
        db.flush()
        db.add(ProjectMembership(project_id=project.id, user_id=user.id))
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Username already exists") from exc
    return create_session(user, response, db)

def digest(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()

def csrf_for_session(token: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), ("csrf:" + token).encode(), hashlib.sha256).hexdigest()

@router.post("/login")
def login(body: LoginRequest, response: Response, request: Request, db: DBSession = Depends(get_session)):
    key = (request.client.host if request.client else "unknown", body.username.casefold())
    now = time.monotonic()
    with _login_lock:
        if len(_login_failures) > 10_000:
            for expired_key, (_, deadline) in list(_login_failures.items()):
                if deadline <= now: _login_failures.pop(expired_key, None)
        count, expires = _login_failures.get(key, (0, 0))
        if expires <= now: count = 0
        if count >= LOGIN_MAX_FAILURES:
            raise HTTPException(429, "Too many sign-in attempts. Try again later.", headers={"Retry-After": str(max(1, int(expires - now)))})
    user = db.scalar(select(User).where(User.username == body.username, User.is_active.is_(True)))
    if not user or not verify_password(body.password, user.password_hash):
        with _login_lock:
            count, expires = _login_failures.get(key, (0, 0))
            _login_failures[key] = (count + 1 if expires > now else 1, expires if expires > now else now + LOGIN_WINDOW_SECONDS)
        raise HTTPException(401, "Invalid credentials")
    with _login_lock: _login_failures.pop(key, None)
    return create_session(user, response, db)

@router.post("/logout", status_code=204)
def logout(response: Response, user: User = Depends(require_csrf), session_token: str | None = Cookie(None, alias=COOKIE), db: DBSession = Depends(get_session)):
    if session_token:
        record = db.get(Session, digest(session_token))
        if record: record.revoked_at = datetime.now(timezone.utc)
        db.commit()
    response.delete_cookie(COOKIE)

@router.get("/me")
def me(response: Response, user: User = Depends(current_user), session_token: str = Cookie(..., alias=COOKIE), db: DBSession = Depends(get_session)):
    response.headers["Cache-Control"] = "no-store"
    csrf = csrf_for_session(session_token)
    record = db.get(Session, digest(session_token))
    record.csrf_hash = digest(csrf)
    projects = db.scalars(
        select(Project)
        .join(ProjectMembership)
        .where(ProjectMembership.user_id == user.id)
        .order_by(Project.name)
    ).all()
    return {
        "csrf_token": csrf,
        "id": str(user.id),
        "username": user.username,
        "role": user.role,
        "projects": [{"id": str(project.id), "name": project.name, "timezone": project.timezone} for project in projects],
    }
