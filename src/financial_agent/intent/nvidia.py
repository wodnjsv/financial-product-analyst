"""One-call NVIDIA JSON-mode adapter; semantic validation remains server-owned."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from time import perf_counter

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

_LOGGER = logging.getLogger(__name__)


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
    "A generic product family such as domestic ETF is not a named product. "
    "Do not add a frame_subject entity hint for that family. Entity-hint "
    "mention_id may contain only a view.entity_candidates[].mention_id; "
    "general view.mention_spans IDs are not interchangeable with entity mentions. "
    "For manager/holding family screens, keep the offered relation_object hint "
    "and select the subject family/type in the frame without inventing a subject name. "
    "Also include a selected semantic_link for that same relation ID (managedBy "
    "or holdsSecurity), using an offered source mention. A relation_id inside "
    "an entity hint alone does not establish the frame's relation meaning. "
    "Keep action IDs only in action_choice.selected_ids and product-family IDs "
    "only in product_family_choice.selected_ids. semantic_links[].semantic_ids "
    "contains only compact_semantic_catalog.concepts[].semantic_id values; "
    "never action, family, entity-type, literal or operator IDs. Example for a "
    'domestic annual-return question: action_choice.selected_ids=["rank"]; '
    'product_family_choice.selected_ids=["domestic_etf"]; '
    'semantic_links[].semantic_ids=["trailing_1y_historical_cumulative_return"]. '
    "The domestic_etf family mention needs no semantic link. These examples are "
    "field values, not complete outputs; use only IDs offered in the current view. "
    "Represent every view.reference_candidates ID in references. If there is no "
    "antecedent in this request, use status=unresolved and producer_frame_ordinals=[]; "
    "never ignore a demonstrative or invent a prior result. "
    "references[].grammatical_number, expected_target_kind and expected_cardinality "
    "are optional single-item arrays, not strings. Examples: grammatical_number=[\"singular\"], "
    "expected_target_kind=[\"entity\"], expected_cardinality=[\"one\"]; or "
    "grammatical_number=[\"plural\"], expected_target_kind=[\"result_set\"], "
    "expected_cardinality=[\"many\"]. Use [] when the optional value is unknown. "
    "Ambiguous axis choices have selected_ids=[]; do not choose an unsupported "
    "family to hide ambiguity. Each source mention belongs either to a semantic "
    "link or to unmapped_mention_ids, never both or multiple links. With no "
    "unmapped source meaning, semantic_coverage is covered with reason=none; "
    "ambiguous semantic links still retain their distinct concept alternatives. "
    "Every semantic_id in a selected or ambiguous link must apply to all selected "
    "frame product families and subject types. Do not include an inapplicable "
    "alternative in ambiguity. Keep unresolved source meaning unmapped instead "
    "of replacing unsupported meaning with a nearby registered concept. "
    "Partial/unmapped coverage requires a genuinely unmapped source mention "
    "and a non-none reason. Context links connect an earlier producer frame to "
    "a later consumer, never the same frame. A singleton relation_target has "
    "selector=[] and selector_literal_candidate_id=[]. To reuse the same singleton "
    "entity, selected_product uses inherit_scope; relation_target uses derive_entity. "
    "consume_single_result selects from candidates or top_k_products with an explicit "
    "single-result selector; consume_result_set consumes those result-set roles. "
    "metric_value uses derive_metric_value, excluded_products uses refer_exclusion_set "
    "and evidence_records uses refer_evidence. The producer must declare the actual "
    "source role and the reference must match the link's target kind/cardinality. "
    "Do not change a product reference into a related entity or invent a role to make "
    "a link executable. These constraints also "
    "apply during repair.\n"
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
        started = perf_counter()
        status = None
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
                status = response.status_code
                if status == 429:
                    raise ModelInvocationError(MODEL_RATE_LIMITED)
                if 400 <= response.status_code < 500:
                    raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
                if not 200 <= response.status_code < 300:
                    raise ModelInvocationError(MODEL_PROVIDER_UNAVAILABLE)
                return _parse_success(response)
        except (TimeoutError, httpx.TimeoutException) as error:
            kind = next((name for cls, name in (
                (httpx.ReadTimeout, "read_timeout"), (httpx.ConnectTimeout, "connect_timeout"),
                (httpx.WriteTimeout, "write_timeout"), (httpx.PoolTimeout, "pool_timeout"),
            ) if isinstance(error, cls)), "wall_timeout")
            _log_failure(MODEL_TIMEOUT, kind, status, started)
            raise ModelInvocationError(MODEL_TIMEOUT) from None
        except httpx.HTTPError as error:
            kind = next((name for cls, name in (
                (httpx.ConnectError, "connect_error"), (httpx.ReadError, "read_error"),
                (httpx.RemoteProtocolError, "remote_protocol_error"),
            ) if isinstance(error, cls)), "http_error")
            _log_failure(MODEL_PROVIDER_UNAVAILABLE, kind, status, started)
            raise ModelInvocationError(MODEL_PROVIDER_UNAVAILABLE) from None
        except ModelInvocationError as error:
            _log_failure(error.code, "http_status" if status != 200 else "response_schema", status, started)
            raise

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
    """Keep role-specific IDs while omitting repeated general evidence enums."""
    if not _is_v3_response_schema(schema):
        return schema
    identifier_fields = {
        "mention_id", "unmapped_mention_ids", "evidence_ids",
        "candidate_entity_ids", "selected_candidate_ids", "reference_id",
        "selector_literal_candidate_id",
    }

    def copy(value: object, identifier_field: bool = False, path: tuple[str, ...] = ()) -> object:
        if isinstance(value, dict):
            return {
                key: copy(item, identifier_field or key in identifier_fields, path + (key,))
                for key, item in value.items()
                if not (identifier_field and key == "enum"
                        and not ("entity_hints" in path and "mention_id" in path))
            }
        if isinstance(value, list):
            return [copy(item, identifier_field, path) for item in value]
        return value

    return copy(schema)


def _log_failure(code: str, kind: str, status: int | None, started: float) -> None:
    # Never log URLs, headers, exception text or provider response bodies.
    _LOGGER.warning("NVIDIA invocation failed code=%s kind=%s http_status=%s elapsed_ms=%s",
                    code, kind, status, round((perf_counter() - started) * 1000))


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
