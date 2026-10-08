"""Small, injectable Ollama chat client used by worker stages.

The client deliberately accepts configuration only from the worker.  Uploaded
text and browser parameters must never be able to select an endpoint or model.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class OllamaError(RuntimeError):
    """Base class for expected local model failures."""


class OllamaConfigurationError(OllamaError):
    pass


class OllamaTransportError(OllamaError):
    pass


class OllamaResponseError(OllamaError):
    pass


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_local_base_url(value: str) -> str:
    """Allow loopback, RFC1918/link-local, and Tailscale's CGNAT address space."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise OllamaConfigurationError("ollama_base_url must be an http(s) private/loopback URL")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise OllamaConfigurationError("ollama_base_url must not contain a path or query")
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        raise OllamaConfigurationError("ollama_base_url must include a host")
    if host.lower() == "localhost":
        return value.rstrip("/")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, port)}
        except OSError as exc:
            raise OllamaConfigurationError("ollama_base_url host cannot be resolved") from exc
    def allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        tailscale_ipv4 = isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10")
        return address.is_loopback or address.is_private or address.is_link_local or tailscale_ipv4

    if not addresses or not all(allowed(address) for address in addresses):
        raise OllamaConfigurationError("ollama_base_url must resolve only to loopback/private addresses")
    return value.rstrip("/")


@dataclass(frozen=True)
class LLMResult:
    value: dict[str, Any]
    model: str
    model_digest: str | None
    runtime: str | None
    elapsed_ms: int
    settings_hash: str
    prompt_hash: str


Transport = Callable[[str, str, Mapping[str, Any], float, Mapping[str, str]], tuple[int, Mapping[str, Any]]]


class OllamaChatAdapter:
    def __init__(self, base_url: str, model: str, *, timeout: float = 120.0,
                 max_retries: int = 1, transport: Transport | None = None,
                 bearer_token: str | None = None, think: bool | None = False):
        self.base_url = validate_local_base_url(base_url)
        if not model.strip():
            raise OllamaConfigurationError("ollama model is required")
        if timeout <= 0 or max_retries < 0 or max_retries > 1:
            raise OllamaConfigurationError("timeout must be positive and retries must be 0 or 1")
        self.model, self.timeout, self.max_retries = model, timeout, max_retries
        token = bearer_token if bearer_token is not None else os.getenv("OLLAMA_API_KEY")
        if token and ("\r" in token or "\n" in token):
            raise OllamaConfigurationError("bearer token contains invalid header characters")
        self.bearer_token = token or None
        self.think = think
        self._transport = transport or self._http_transport

    @staticmethod
    def _http_transport(method: str, url: str, payload: Mapping[str, Any], timeout: float,
                        headers: Mapping[str, str]):
        body = json.dumps(payload).encode() if method != "GET" else None
        request = Request(url, data=body if method == "POST" else None, method=method,
                          headers={"Content-Type": "application/json", **headers})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL was validated above
            return response.status, json.loads(response.read())

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None):
        headers = {"Authorization": f"Bearer {self.bearer_token}"} if self.bearer_token else {}
        try:
            return self._transport(method, f"{self.base_url}{path}", payload or {}, self.timeout, headers)
        except (TimeoutError, OSError, ValueError) as exc:
            raise OllamaTransportError("Ollama request timed out or failed") from exc

    def health(self) -> dict[str, Any]:
        """Check runtime and configured model without printing endpoint credentials."""
        status, version_body = self._request("GET", "/api/version")
        if status >= 400 or not isinstance(version_body, Mapping) or not version_body.get("version"):
            raise OllamaResponseError("Ollama runtime health check failed")
        status, tags_body = self._request("GET", "/api/tags")
        if status >= 400 or not isinstance(tags_body, Mapping):
            raise OllamaResponseError("Ollama model inventory request failed")
        models = tags_body.get("models", [])
        if not isinstance(models, list):
            raise OllamaResponseError("Ollama model inventory response is invalid")
        selected = next((item for item in models if isinstance(item, Mapping)
                         and item.get("name") == self.model), None)
        result = {"ok": selected is not None, "runtime": str(version_body["version"]),
                  "model": self.model, "installed": selected is not None,
                  "model_digest": selected.get("digest") if selected else None}
        if selected:
            model_data = self.metadata()
            details = model_data.get("details", {})
            result["model_metadata"] = {
                key: details[key] for key in ("family", "parameter_size", "quantization_level")
                if isinstance(details, Mapping) and key in details
            }
        return result

    def metadata(self) -> dict[str, Any]:
        status, body = self._request("POST", "/api/show", {"name": self.model})
        if status == 404:
            raise OllamaResponseError(f"model is not installed: {self.model}")
        if status >= 400 or not isinstance(body, Mapping):
            raise OllamaResponseError("Ollama model metadata request failed")
        return dict(body)

    def chat(self, *, system: str, user: str | Mapping[str, Any], schema: Mapping[str, Any], settings: Mapping[str, Any] | None = None,
             metadata: bool = True) -> LLMResult:
        # Selection supplies structured context; Ollama message content is text.
        if isinstance(user, Mapping):
            user = json.dumps(user, ensure_ascii=False, default=str)
        options = {"temperature": 0.0, "num_ctx": 8192, "num_predict": 1536}
        if settings:
            options.update(settings)
        try:
            requested_context = int(options["num_ctx"])
            requested_output = int(options["num_predict"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OllamaConfigurationError("num_ctx and num_predict must be positive integers") from exc
        if requested_context <= 0 or requested_output <= 0:
            raise OllamaConfigurationError("num_ctx and num_predict must be positive integers")
        # Uploaded content and injected callers cannot expand the bounded worker
        # context or output beyond the reviewed runtime envelope.
        options["num_ctx"] = min(requested_context, 8192)
        options["num_predict"] = min(requested_output, 1536)
        payload = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                   "stream": False, "format": schema, "options": options}
        if self.think is not None:
            payload["think"] = self.think
        prompt_hash, settings_hash = _hash({"system": system, "user": user}), _hash(options)
        started = time.monotonic()
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                status, body = self._request("POST", "/api/chat", payload)
                if status == 404:
                    raise OllamaResponseError(f"model is not installed: {self.model}")
                if status >= 500 and attempt < self.max_retries:
                    continue
                if status >= 400:
                    raise OllamaResponseError(f"Ollama chat request failed ({status})")
                content = body.get("message", {}).get("content") if isinstance(body, Mapping) else None
                if not isinstance(content, str):
                    raise OllamaResponseError("Ollama response has no message.content")
                try:
                    value = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise OllamaResponseError("Ollama returned malformed JSON") from exc
                if not isinstance(value, dict):
                    raise OllamaResponseError("Ollama JSON result must be an object")
                elapsed_ms = int((time.monotonic() - started) * 1000)
                return LLMResult(value, str(body.get("model", self.model)), body.get("digest"), body.get("runtime"), elapsed_ms, settings_hash, prompt_hash)
            except OllamaResponseError:
                raise
            except OllamaTransportError as exc:
                last = exc
                if attempt >= self.max_retries:
                    break
            except (TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                last = exc
                if attempt >= self.max_retries:
                    break
        raise OllamaTransportError("Ollama request timed out or failed") from last
