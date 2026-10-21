"""Nonsecret source contract for new durable work; drift requires explicit migration.

Hash complete request-building modules so schema, prompt and adapter defaults cannot
silently change on resume. This is deliberately conservative: even a comment edit
requires review. Legacy records remain identifiable and are not backfilled.
"""

from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import platform


APP = Path(__file__).resolve().parents[1]


def source_contract(settings=None):
    paths = set(APP.rglob("*.py"))
    from .extract import extraction_schema

    schema = extraction_schema()
    if settings is None:
        from ..settings import get_settings

        settings = get_settings()
    return {
        "version": 2,
        "python": platform.python_version(),
        # Keep endpoint identity without persisting a possibly credential-bearing URL.
        "ollama_endpoint_sha256": sha256(settings.ollama_base_url.encode()).hexdigest(),
        "dependencies": {
            name: version(name)
            for name in (
                "pydantic",
                "pydantic-settings",
                "langgraph",
                "langgraph-checkpoint",
                "langgraph-checkpoint-postgres",
                "SQLAlchemy",
                "psycopg",
            )
        },
        "extraction_schema_sha256": sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
        "files": {
            path.relative_to(APP).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)
        },
    }


def compatible_contract(record, settings=None):
    # Unknown legacy configuration needs reviewed migration, never silent adoption.
    if "source_contract" not in record:
        return False
    current = source_contract(settings) if settings is not None else source_contract()
    return record["source_contract"] == current
