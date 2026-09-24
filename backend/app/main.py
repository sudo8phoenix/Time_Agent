"""FastAPI application entrypoint."""
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .settings import get_settings
from .api.endpoints.auth import router as auth_router
from .api.endpoints.projects import router as projects_router
from .api.endpoints.schedules import router as schedules_router
from .api.endpoints.reports import router as reports_router
from .api.endpoints.jobs import router as jobs_router
from .api.endpoints.review import router as review_router
from .api.endpoints.progress import router as progress_router
from .api.endpoints.schedule_imports import router as schedule_imports_router

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(schedules_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")
app.include_router(progress_router, prefix="/api/v1")
app.include_router(schedule_imports_router, prefix="/api/v1")


@app.get("/api/v1/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


def _serve_frontend() -> None:
    dist = Path(settings.frontend_dist)
    if not dist.is_absolute():
        # main.py lives at <project>/backend/app/main.py.
        dist = Path(__file__).resolve().parents[2] / dist
    dist = dist.resolve()
    if not dist.is_dir():
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API route not found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_serve_frontend()
