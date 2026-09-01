"""One-call async adapter for CLOVA Chat Completions v3 Structured Outputs."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import quote

import httpx

from .config import ClovaResolverConfig
from .errors import (
    MODEL_CONFIGURATION_INVALID,
    MODEL_PROVIDER_UNAVAILABLE,
    MODEL_RATE_LIMITED,
    MODEL_SCHEMA_INVALID,
    MODEL_TIMEOUT,
    ModelInvocationError,
)
from .prompt import ResolverPromptEnvelope


@dataclass(frozen=True, slots=True)
class ModelInvocationResult:
    content: str
    usage: Mapping[str, int]


class ClovaStructuredOutputAdapter:
    def __init__(
        self,
        config: ClovaResolverConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    async def invoke(
        self,
        envelope: ResolverPromptEnvelope,
        timeout_seconds: float,
    ) -> ModelInvocationResult:
        if timeout_seconds <= 0:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout_seconds,
            ) as client:
                response = await client.post(
                    self._url(),
                    headers={
                        "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
                        "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
                        "Content-Type": "application/json",
                    },
                    json={
                        "messages": [
                            {"role": "system", "content": envelope.system_message},
                            {"role": "user", "content": envelope.user_message},
                        ],
                        "topP": self._config.top_p,
                        "topK": self._config.top_k,
                        "maxCompletionTokens": self._config.max_completion_tokens,
                        "temperature": self._config.temperature,
                        "repetitionPenalty": self._config.repetition_penalty,
                        "thinking": {"effort": "none"},
                        "seed": 42,
                        "responseFormat": {
                            "type": "json",
                            "schema": envelope.response_schema,
                        },
                    },
                )
        except httpx.TimeoutException:
            raise ModelInvocationError(MODEL_TIMEOUT) from None
        except httpx.HTTPError:
            raise ModelInvocationError(MODEL_PROVIDER_UNAVAILABLE) from None

        if response.status_code == 429:
            raise ModelInvocationError(MODEL_RATE_LIMITED)
        if response.status_code in (401, 403) or 400 <= response.status_code < 500:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        if response.status_code >= 500:
            raise ModelInvocationError(MODEL_PROVIDER_UNAVAILABLE)
        if response.status_code < 200 or response.status_code >= 300:
            raise ModelInvocationError(MODEL_PROVIDER_UNAVAILABLE)
        return _parse_success(response)

    def _url(self) -> str:
        return (
            f"{self._config.base_url.rstrip('/')}/v3/chat-completions/"
            f"{quote(self._config.model_id, safe='')}"
        )


def _parse_success(response: httpx.Response) -> ModelInvocationResult:
    try:
        payload = _strict_json_loads(response.content)
        result = payload["result"]
        message = result["message"]
        content = message["content"]
        usage = result["usage"]
        if not isinstance(payload, dict) or not isinstance(result, dict) or not isinstance(message, dict):
            raise TypeError
        if not isinstance(content, str) or not isinstance(usage, dict):
            raise TypeError
        parsed_usage = {
            name: usage[name]
            for name in ("promptTokens", "completionTokens", "totalTokens")
        }
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in parsed_usage.values()
        ):
            raise TypeError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ModelInvocationError(MODEL_SCHEMA_INVALID) from None
    return ModelInvocationResult(content=content, usage=parsed_usage)


def _strict_json_loads(payload: str | bytes) -> object:
    return json.loads(payload, object_pairs_hook=_reject_duplicate_keys)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result
