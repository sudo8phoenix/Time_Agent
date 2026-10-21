"""Bounded OpenRouter chat adapter implementing the worker chat interface."""
from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping
from typing import Any, Callable

from .ollama import (LLMResult, OllamaConfigurationError, OllamaResponseError,
                     OllamaTransportError, _hash)


Transport = Callable[[str, str, Mapping[str, Any], float, Mapping[str, str]], tuple[int, Mapping[str, Any]]]
_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_MAX_OUTPUT_TOKENS = 1536
_MAX_TIMEOUT_SECONDS = 900


class OpenRouterChatAdapter:
    def __init__(self, model: str | None, *, bearer_token: str | None,
                 timeout: float = 120, max_retries: int = 0,
                 transport: Transport | None = None):
        if not isinstance(model, str) or not model.strip():
            raise OllamaConfigurationError("An explicit OPENROUTER_MODEL is required")
        if not bearer_token or any(char in bearer_token for char in "\r\n"):
            raise OllamaConfigurationError("A valid OPENROUTER_API_KEY is required")
        if not math.isfinite(timeout) or not 0 < timeout <= _MAX_TIMEOUT_SECONDS or max_retries not in (0, 1):
            raise OllamaConfigurationError("OpenRouter timeout or retries exceed the allowed limit")
        self.model, self.timeout, self.max_retries = model.strip(), float(timeout), max_retries
        self._token = bearer_token
        self._transport = transport or self._http_transport

    @staticmethod
    def _http_transport(method, url, payload, timeout, headers):
        from .hosted import request
        return request("openrouter", method, url, payload, timeout, headers)

    def chat(self, *, system: str, user: str | Mapping[str, Any], schema: Mapping[str, Any],
             settings: Mapping[str, Any] | None = None, metadata: bool = True) -> LLMResult:
        if isinstance(user, Mapping):
            user = json.dumps(user, ensure_ascii=False, default=str)
        options = {"temperature": 0.0, "num_predict": _MAX_OUTPUT_TOKENS}
        options.update(settings or {})
        try:
            requested_output = int(options["num_predict"])
            temperature = float(options["temperature"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OllamaConfigurationError("OpenRouter generation settings are invalid") from exc
        if requested_output <= 0 or not 0 <= temperature <= 2:
            raise OllamaConfigurationError("OpenRouter generation settings are invalid")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system + "\nReturn only JSON matching this schema: " + json.dumps(schema)}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": min(requested_output, _MAX_OUTPUT_TOKENS),
            "stream": False,
        }
        prompt_hash = _hash({"system": system, "user": user})
        settings_hash = _hash({"temperature": temperature, "max_tokens": payload["max_tokens"]})
        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                status, body = self._transport("POST", _ENDPOINT, payload, self.timeout,
                    {"Authorization": f"Bearer {self._token}"})
            except (TimeoutError, OSError, ValueError) as exc:
                if attempt < self.max_retries:
                    continue
                raise OllamaTransportError("OpenRouter request timed out or failed") from exc
            if status >= 500 and attempt < self.max_retries:
                continue
            from .hosted import raise_for_status
            raise_for_status("openrouter", status)
            try:
                if (not isinstance(body, Mapping) or not isinstance(body.get("choices"), list)
                        or len(body["choices"]) != 1):
                    raise OllamaResponseError("OpenRouter returned an invalid JSON response")
                choice = body["choices"][0]
                if not isinstance(choice, Mapping) or not isinstance(choice.get("message"), Mapping):
                    raise OllamaResponseError("OpenRouter returned an invalid JSON response")
                if choice.get("message", {}).get("refusal"):
                    raise OllamaResponseError("OpenRouter refused the request")
                if choice.get("finish_reason") != "stop":
                    raise OllamaResponseError("OpenRouter response was incomplete")
                value = json.loads(choice["message"]["content"])
                if not isinstance(value, dict):
                    raise ValueError("Expected JSON object")
                _validate_schema(value, schema)
            except OllamaResponseError:
                raise
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise OllamaResponseError("OpenRouter returned an invalid JSON response") from exc
            return LLMResult(value, str(body.get("model", self.model)), None, "openrouter",
                int((time.monotonic() - started) * 1000), settings_hash, prompt_hash)
        raise OllamaTransportError("OpenRouter request failed")


def _validate_schema(value: dict[str, Any], schema: Mapping[str, Any]) -> None:
    """Enforce the caller's JSON schema locally even if the provider ignores it."""
    if not _matches_schema(value, schema):
        raise OllamaResponseError("OpenRouter response did not match the requested schema")


def _matches_schema(value: Any, schema: Mapping[str, Any], *,
                    root: Mapping[str, Any] | None = None,
                    refs: frozenset[tuple[int, str]] = frozenset()) -> bool:
    """Validate our schema subset, resolving local definitions without network IO."""
    root = schema if root is None else root
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/"):
            return False
        identity = (id(value), reference)
        if identity in refs:
            return False
        target = root
        for token in reference[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, Mapping) or token not in target:
                return False
            target = target[token]
        if not isinstance(target, Mapping):
            return False
        siblings = {key: item for key, item in schema.items() if key != "$ref"}
        return (_matches_schema(value, target, root=root, refs=refs | {identity}) and
                _matches_schema(value, siblings, root=root, refs=refs))
    if "enum" in schema and value not in schema["enum"]:
        return False
    if "anyOf" in schema:
        return any(_matches_schema(value, option, root=root, refs=refs) for option in schema["anyOf"])
    kind = schema.get("type")
    if isinstance(kind, list):
        return any(_matches_schema(value, {**schema, "type": item}, root=root, refs=refs) for item in kind)
    type_matches = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if kind in type_matches and not type_matches[kind](value):
        return False
    if isinstance(value, dict):
        if any(key not in value for key in schema.get("required", [])):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            return False
        return all(key not in properties or _matches_schema(item, properties[key], root=root, refs=refs)
                   for key, item in value.items())
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            return False
        if schema.get("uniqueItems") and len(value) != len({json.dumps(item, sort_keys=True) for item in value}):
            return False
        item_schema = schema.get("items")
        return item_schema is None or all(_matches_schema(item, item_schema, root=root, refs=refs) for item in value)
    return True
