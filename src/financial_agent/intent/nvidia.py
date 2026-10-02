"""One-call NVIDIA JSON-mode adapter; semantic validation remains server-owned."""

from __future__ import annotations

import asyncio
import json
import math

import httpx

from .errors import (
    MODEL_CONFIGURATION_INVALID,
    MODEL_PROVIDER_UNAVAILABLE,
    MODEL_RATE_LIMITED,
    MODEL_SCHEMA_INVALID,
    MODEL_TIMEOUT,
    ModelInvocationError,
)
from .model import ModelInvocationResult, StructuredOutputEnvelope
from .nvidia_config import NvidiaResolverConfig


_V3_OUTPUT_GUIDANCE = (
    "V3 field-shape checks, including repair: keep the full root object and all "
    "required frame keys. Array fields must be JSON arrays, never null or a scalar; "
    "use [] when there is no item. semantic_links[].mention_id is one string; "
    "entity_hints[].mention_id is an array. Each entity hint's relation_id, "
    "expected_entity_type_ids, candidate_entity_ids and selected_candidate_ids "
    "are arrays. Field-value examples inside a frame: frame_subject relation_id=[]; "
    'relation_object relation_id=["managedBy"] (or another offered relation). '
    "frame.entity_type_ids contains only queried product subject types; put "
    "Security and AssetManager object types only in relation_object hints' expected_entity_type_ids, "
    "never in frame.entity_type_ids. Example: frame.entity_type_ids=[\"ETF\"]; "
    "the managedBy relation_object expected_entity_type_ids=[\"AssetManager\"] "
    "(holdsSecurity uses [\"Security\"]). "
    "For frame_subject, expected_entity_type_ids must match frame.entity_type_ids "
    "without extra broad ancestor types, e.g. frame.entity_type_ids=[\"ETF\"] "
    "and expected_entity_type_ids=[\"ETF\"]. "
    "Keep action IDs only in action_choice.selected_ids and product-family IDs "
    "only in product_family_choice.selected_ids. semantic_links[].semantic_ids "
    "contains only compact_semantic_catalog.concepts[].semantic_id values; "
    "never action, family, entity-type, literal or operator IDs. Example for a "
    'domestic annual-return question: action_choice.selected_ids=["rank"]; '
    'product_family_choice.selected_ids=["domestic_etf"]; '
    'semantic_links[].semantic_ids=["trailing_1y_historical_cumulative_return"]. '
    "The domestic_etf family mention needs no semantic link. These examples are "
    "field values, not complete outputs; use only IDs offered in the current view.\n"
)


class NvidiaStructuredOutputAdapter:
    def __init__(
        self,
        config: NvidiaResolverConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    async def invoke(
        self,
        envelope: StructuredOutputEnvelope,
        timeout_seconds: float,
    ) -> ModelInvocationResult:
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        body = self._request_body(envelope)
        try:
            # HTTP phase timeouts alone do not bound the entire invocation.
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        f"{self._config.base_url.rstrip('/')}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self._config.api_key.get_secret_value()}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                if response.status_code == 429:
                    raise ModelInvocationError(MODEL_RATE_LIMITED)
                if 400 <= response.status_code < 500:
                    raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
                if not 200 <= response.status_code < 300:
                    raise ModelInvocationError(MODEL_PROVIDER_UNAVAILABLE)
                return _parse_success(response)
        except (TimeoutError, httpx.TimeoutException):
            raise ModelInvocationError(MODEL_TIMEOUT) from None
        except httpx.HTTPError:
            raise ModelInvocationError(MODEL_PROVIDER_UNAVAILABLE) from None

    def _request_body(self, envelope: StructuredOutputEnvelope) -> dict[str, object]:
        if (
            not isinstance(envelope.system_message, str)
            or not isinstance(envelope.user_message, str)
            or not isinstance(envelope.response_schema, dict)
            or envelope.response_schema.get("type") != "object"
        ):
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        try:
            schema = json.dumps(
                _model_response_schema(envelope.response_schema),
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID) from None
        # Hosted GLM's JSON-schema enforcement is not documented. JSON mode and
        # this explicit schema do not replace the resolver's strict validation.
        body: dict[str, object] = {
            "model": self._config.model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{envelope.system_message}\n\n"
                        "Return exactly one JSON object matching this JSON Schema. "
                        "Do not return Markdown, explanations, or additional fields.\n"
                        f"{_V3_OUTPUT_GUIDANCE if _is_v3_response_schema(envelope.response_schema) else ''}"
                        f"JSON Schema:\n{schema}"
                    ),
                },
                {"role": "user", "content": envelope.user_message},
            ],
            "max_tokens": self._config.max_completion_tokens,
            "temperature": self._config.temperature,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        if self._config.model_id == "z-ai/glm-5.3-flash":
            body["reasoning_effort"] = "low"
            body["chat_template_kwargs"] = {"clear_thinking": True}
        return body


def _model_response_schema(schema: dict[str, object]) -> object:
    """Omit repeated V3 ID lists only in the model's schema presentation."""
    if not _is_v3_response_schema(schema):
        return schema
    identifier_fields = {
        "mention_id", "unmapped_mention_ids", "evidence_ids", "semantic_ids",
        "candidate_entity_ids", "selected_candidate_ids", "reference_id",
        "selector_literal_candidate_id",
    }

    def copy(value: object, identifier_field: bool = False) -> object:
        if isinstance(value, dict):
            return {
                key: copy(item, identifier_field or key in identifier_fields)
                for key, item in value.items()
                if not (identifier_field and key == "enum")
            }
        if isinstance(value, list):
            return [copy(item, identifier_field) for item in value]
        return value

    return copy(schema)


def _is_v3_response_schema(schema: dict[str, object]) -> bool:
    properties = schema.get("properties", {})
    version = properties.get("proposal_schema_version", {}) if isinstance(properties, dict) else {}
    return isinstance(version, dict) and (
        version.get("enum") == ["3.0"] or version.get("const") == "3.0"
    )


def _parse_success(response: httpx.Response) -> ModelInvocationResult:
    try:
        payload = json.loads(response.content, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(payload, dict):
            raise TypeError
        choices = payload["choices"]
        usage = payload["usage"]
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(usage, dict):
            raise TypeError
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
            raise TypeError
        if type(choice.get("index")) is not int or choice["index"] != 0:
            raise TypeError
        message = choice["message"]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise TypeError
        if (
            message.get("refusal") not in (None, "")
            or message.get("tool_calls") not in (None, [])
            or message.get("function_call") is not None
        ):
            raise TypeError
        content = message["content"]
        if not isinstance(content, str) or not content.strip():
            raise TypeError
        parsed_usage = {
            "promptTokens": usage["prompt_tokens"],
            "completionTokens": usage["completion_tokens"],
            "totalTokens": usage["total_tokens"],
        }
        if any(type(value) is not int or value < 0 for value in parsed_usage.values()):
            raise TypeError
        if parsed_usage["totalTokens"] != parsed_usage["promptTokens"] + parsed_usage["completionTokens"]:
            raise TypeError
    except (KeyError, TypeError, ValueError, UnicodeDecodeError):
        raise ModelInvocationError(MODEL_SCHEMA_INVALID) from None
    # Never return or log reasoning_content, provider bodies, or error details.
    return ModelInvocationResult(content=content, usage=parsed_usage)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result
