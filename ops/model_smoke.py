"""Explicit real Ollama smoke call; never downloads models or benchmarks them."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.llm.ollama import OllamaChatAdapter  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Make one explicit local Ollama smoke request")
    parser.add_argument("--run", action="store_true", help="required: perform the real request")
    parser.add_argument("--output", type=Path, help="optional JSON result path")
    args = parser.parse_args()
    if not args.run:
        print("Refusing to call Ollama without --run (no model download or benchmark is performed).")
        return 2
    settings = get_settings()
    adapter = OllamaChatAdapter(
        settings.ollama_base_url,
        settings.ollama_model,
        bearer_token=(
            settings.ollama_api_key.get_secret_value()
            if settings.ollama_api_key
            else None
        ),
    )
    started = time.monotonic()
    metadata = adapter.metadata()
    result = adapter.chat(system="Return the requested JSON object.", user="Reply with {\"ok\": true}.", schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False})
    record = {"runtime": result.runtime, "model": result.model, "model_digest": result.model_digest or metadata.get("digest"), "elapsed_ms": result.elapsed_ms, "wall_ms": int((time.monotonic() - started) * 1000), "settings_hash": result.settings_hash, "prompt_hash": result.prompt_hash, "result": result.value}
    rendered = json.dumps(record, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
