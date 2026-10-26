"""Gonka Broker chat adapter using the shared hosted JSON contract."""
from __future__ import annotations

import re

from .openrouter import OpenRouterChatAdapter


class GonkaChatAdapter(OpenRouterChatAdapter):
    endpoint = "https://proxy.gonkabroker.com/v1/chat/completions"
    provider_name = "gonka"
    provider_label = "Gonka"
    max_output_tokens = 4096

    @staticmethod
    def _normalize_content(content: str) -> str:
        if not isinstance(content, str):
            return content
        match = re.fullmatch(r"\s*```(?:json)?\s*\n(.*?)\n```\s*", content, re.I | re.S)
        return match.group(1) if match else content

    @staticmethod
    def _http_transport(method, url, payload, timeout, headers):
        from .hosted import request

        return request("gonka", method, url, payload, timeout, headers)
