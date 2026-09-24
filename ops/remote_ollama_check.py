"""Check an authenticated, private Ollama endpoint without printing its URL or token."""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.llm.ollama import OllamaChatAdapter, OllamaError  # noqa: E402
from app.settings import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds (default: 10)",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    settings = get_settings()
    try:
        result = OllamaChatAdapter(
            settings.ollama_base_url,
            settings.ollama_model,
            timeout=args.timeout,
            max_retries=0,
            bearer_token=(
                settings.ollama_api_key.get_secret_value()
                if settings.ollama_api_key
                else None
            ),
        ).health()
    except OllamaError as exc:
        # Error descriptions are intentionally generic and never include secrets.
        result = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
