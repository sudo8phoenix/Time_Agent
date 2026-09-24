"""Read-only runtime readiness checks; missing prerequisites fail visibly."""
import importlib.metadata
import json
import platform
import shutil
import subprocess

from sqlalchemy import text

from app.db.session import engine
from app.llm.ollama import OllamaChatAdapter
from app.settings import get_settings


def main():
    settings = get_settings()
    checks = {"python": {"ok": platform.python_version_tuple()[:2] == ("3", "12"), "version": platform.python_version()}}
    try:
        with engine.connect() as db:
            revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        checks["database"] = {"ok": True, "migration": revision}
    except Exception as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}
    try:
        selected = OllamaChatAdapter(
            settings.ollama_base_url,
            settings.ollama_model,
            timeout=5,
            max_retries=0,
            bearer_token=(settings.ollama_api_key.get_secret_value() if settings.ollama_api_key else None),
        ).health()
        checks["model_endpoint"] = selected
    except Exception as exc:
        checks["model_endpoint"] = {"ok": False, "error": type(exc).__name__}
    try:
        java = subprocess.run(["java", "--version"], capture_output=True, text=True, timeout=10, check=True)
        checks["native_parser"] = {"ok": True, "java": java.stdout.splitlines()[0], "mpxj": importlib.metadata.version("mpxj"), "jpype": importlib.metadata.version("JPype1")}
    except Exception as exc:
        checks["native_parser"] = {"ok": False, "error": type(exc).__name__}
    checks["node"] = {"ok": shutil.which("node") is not None}
    print(json.dumps(checks, indent=2))
    return 0 if all(item["ok"] for item in checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
