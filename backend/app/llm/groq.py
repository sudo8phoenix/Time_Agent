"""Groq structured chat using the existing injectable model interface."""
import json
import math
import time
from functools import partial
from collections.abc import Mapping
from .ollama import (LLMResult, OllamaConfigurationError,
                     OllamaResponseError, OllamaTransportError, _hash)



class GroqTruncatedResponseError(OllamaResponseError):
    """The provider stopped at its output token limit."""


class GroqInvalidJSONError(OllamaResponseError):
    """The response content was not a JSON object."""


class GroqSchemaMismatchError(OllamaResponseError):
    """Parsed JSON did not satisfy the requested schema."""


class GroqRefusalError(OllamaResponseError):
    """The provider refused the request."""


class GroqEnvelopeError(OllamaResponseError):
    """The provider response envelope was missing required fields."""


def _validate_schema(value, schema):
    """Enforce the requested JSON schema locally, independent of provider claims."""
    from .openrouter import _matches_schema
    if not _matches_schema(value, schema):
        raise GroqSchemaMismatchError("Groq response did not match the requested schema")



def _response_schema(schema, model):
    """Require every declared field for GPT-OSS constrained decoding.

    Open-ended maps cannot be closed without changing their meaning, so retain
    best-effort mode for those schemas and for unsupported models.
    """
    if model not in {"openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"}:
        return schema, False
    compatible = True

    def visit(node):
        nonlocal compatible
        if isinstance(node, list):
            return [visit(item) for item in node]
        if not isinstance(node, dict):
            return node
        reference = node.get("$ref", "")
        if reference.startswith("#/$defs/"):
            target = schema.get("$defs", {}).get(reference.removeprefix("#/$defs/"), {})
            if "enum" in target:
                return visit(target)
        result = {}
        for key, value in node.items():
            # Provider constrained decoding supports structure, while the original
            # schema and Pydantic retain all bounds and format validation locally.
            if key in {"default", "format", "minimum", "maximum", "exclusiveMinimum",
                       "exclusiveMaximum", "multipleOf", "minItems", "maxItems",
                       "minLength", "maxLength", "pattern", "uniqueItems"}:
                continue
            if key in {"properties", "$defs"}:
                result[key] = {name: visit(child) for name, child in value.items()}
            elif key in {"items", "anyOf", "oneOf", "allOf"}:
                result[key] = visit(value)
            else:
                result[key] = value
        branches = result.get("anyOf", [])
        if branches and all(branch.get("type") in {"string", "number", "integer", "boolean", "null"}
                            for branch in branches):
            enums = [branch for branch in branches if "enum" in branch]
            if not enums or (len(enums) == 1 and all(
                    branch is enums[0] or branch.get("type") == "null" for branch in branches)):
                result.pop("anyOf")
                result["type"] = [branch["type"] for branch in branches]
                if enums:
                    result["enum"] = [*enums[0]["enum"], None]
        if node.get("type") == "object" or "properties" in node:
            if node.get("additionalProperties") is not False:
                compatible = False
            result["required"] = list(node.get("properties", {}))
        return result

    prepared = visit(schema)
    return (prepared, True) if compatible else (schema, False)


class GroqChatAdapter:
    def __init__(self, model, *, bearer_token, timeout=120, max_retries=0, transport=None,
                 capacity_scope=None):
        if not bearer_token or any(c in bearer_token for c in "\r\n"):
            raise OllamaConfigurationError("A valid GROQ_API_KEY is required")
        if (not model.strip() or not math.isfinite(timeout) or not 0 < timeout <= 900
                or max_retries not in (0, 1)):
            raise OllamaConfigurationError("Invalid Groq model, timeout or retries")
        self.model, self.timeout, self.max_retries = model, timeout, max_retries
        self._token = bearer_token
        self.capacity_scope = capacity_scope
        self._transport = transport or (partial(self._http_transport, capacity_scope=capacity_scope)
                                       if capacity_scope else self._http_transport)

    @staticmethod
    def _http_transport(method, url, payload, timeout, headers, *, capacity_scope=None):
        from .hosted import request
        if capacity_scope:
            return request("groq", method, url, payload, timeout, headers,
                           capacity_scope=capacity_scope)
        return request("groq", method, url, payload, timeout, headers)

    def chat(self, *, system, user, schema, settings=None, metadata=True):
        if isinstance(user, Mapping):
            user = json.dumps(user, ensure_ascii=False, default=str)
        options = {"temperature": 0.0, "num_predict": 8112}
        options.update(settings or {})
        try:
            output = int(options["num_predict"])
        except (ValueError, TypeError) as exc:
            raise OllamaConfigurationError("num_predict must be positive") from exc
        if output <= 0:
            raise OllamaConfigurationError("num_predict must be positive")
        response_schema, strict = _response_schema(schema, self.model)
        payload = {"model": self.model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": options["temperature"], "max_completion_tokens": min(output, 8112),
            "stream": False, "response_format": {"type": "json_schema", "json_schema": {
                "name": "response", "strict": strict, "schema": response_schema}}}
        if self.model.startswith("openai/gpt-oss-"):
            payload["reasoning_effort"] = "low"
        started = time.monotonic()
        for attempt in range(self.max_retries + 1):
            try:
                status, body = self._transport("POST", "https://api.groq.com/openai/v1/chat/completions",
                    payload, self.timeout, {"Authorization": f"Bearer {self._token}"})
            except (TimeoutError, OSError, ValueError) as exc:
                if attempt < self.max_retries:
                    continue
                raise OllamaTransportError("Groq request timed out or failed") from exc
            if status >= 500 and attempt < self.max_retries:
                continue
            from .hosted import raise_for_status
            raise_for_status("groq", status, scope=self.capacity_scope)
            try:
                if (not isinstance(body, Mapping) or not isinstance(body.get("choices"), list)
                        or len(body["choices"]) != 1):
                    raise GroqEnvelopeError("Groq returned an invalid response envelope")
                choice = body["choices"][0]
                if not isinstance(choice, Mapping) or not isinstance(choice.get("message"), Mapping):
                    raise GroqEnvelopeError("Groq returned an invalid response envelope")
                from .metrics import record_provider_finish
                record_provider_finish("groq", choice.get("finish_reason"))
                if choice.get("message", {}).get("refusal"):
                    raise GroqRefusalError("Groq refused the request")
                if choice.get("finish_reason") == "length":
                    raise GroqTruncatedResponseError("Groq response reached its output limit")
                if choice.get("finish_reason") != "stop":
                    raise OllamaResponseError("Groq response was incomplete")
                value = json.loads(choice["message"]["content"])
                if not isinstance(value, dict):
                    raise ValueError("Expected object")
                _validate_schema(value, schema)
            except KeyError:
                raise GroqEnvelopeError("Groq response content is missing") from None
            except (IndexError, TypeError, ValueError):
                raise GroqInvalidJSONError("Groq response content is not a JSON object") from None
            return LLMResult(value, body.get("model", self.model), None, "groq",
                int((time.monotonic() - started) * 1000), _hash(payload),
                _hash({"system": system, "user": user}))
