from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from financial_agent.contracts.canonical import build_request_key, canonical_sha256
from financial_agent.contracts.request import (
    NamedEntityMention,
    RequestContext,
    Segment,
)
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.clova import ModelInvocationResult
from financial_agent.intent.errors import (
    MODEL_RATE_LIMITED,
    MODEL_SCHEMA_INVALID,
    ModelInvocationError,
    ResolverContractError,
)
from financial_agent.intent.service import (
    IntentResolverService,
    build_repair_envelope,
)
from financial_agent.intent.types import ResolutionStatus
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ActiveDatasetPin,
    ResolverInvariantError,
    build_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 31, 1, 2, 3, tzinfo=UTC)
USAGE = {"promptTokens": 11, "completionTokens": 7, "totalTokens": 18}
MODEL_UNKNOWN_ID = "MODEL_UNKNOWN_ID"


def _context(
    question: str = "AUM 알려줘",
    *,
    dataset_version: str = "dataset-v1",
    deadline_seconds: float = 8.0,
    entity_mention_count: int = 0,
) -> RequestContext:
    mention_texts = tuple(f"상품{index}" for index in range(entity_mention_count))
    if mention_texts:
        question = " ".join(mention_texts)
    return RequestContext(
        request_key=build_request_key("q-service", question, dataset_version, "1.0"),
        run_id="run-service",
        dataset_version=dataset_version,
        producer="request-normalizer",
        created_at=NOW,
        question_id="q-service",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        named_entities=tuple(
            NamedEntityMention(
                mention_id=f"entity-mention-{index}",
                segment_id="s1",
                text=text,
                expected_entity_types=("FinancialProduct",),
            )
            for index, text in enumerate(mention_texts)
        ),
        deadline_at=NOW + timedelta(seconds=deadline_seconds),
    )


def _valid_draft_json() -> str:
    return json.dumps(
        {
            "evidence_spans": [
                {
                    "span_id": "span-aum",
                    "segment_id": "s1",
                    "start_char": 0,
                    "end_char": 3,
                    "text": "AUM",
                }
            ],
            "intent_frames": [
                {
                    "frame_id": "frame-1",
                    "ordinal": 0,
                    "segment_ids": ["s1"],
                    "evidence_span_ids": ["span-aum"],
                    "normalized_intent_argument": "AUM lookup",
                    "action_choice": {
                        "state": "selected",
                        "selected_ids": ["lookup"],
                        "evidence_span_ids": ["span-aum"],
                        "reason_code": "explicit",
                    },
                    "product_family_choice": {
                        "state": "selected",
                        "selected_ids": ["domestic_etf"],
                        "evidence_span_ids": ["span-aum"],
                        "reason_code": "explicit",
                    },
                    "entity_type_ids": ["FinancialProduct"],
                    "entity_hint_ids": [],
                    "slot_assignments": [
                        {
                            "slot_assignment_id": "slot-aum",
                            "slot_kind": "metric",
                            "value_ids": ["aum"],
                            "evidence_span_ids": ["span-aum"],
                            "reason_code": "explicit",
                        }
                    ],
                    "produced_result_hints": ["candidates"],
                }
            ],
            "entity_hints": [],
            "reference_hints": [],
            "context_link_hints": [],
            "slot_mutations": [],
            "semantic_flag_hints": [],
            "frame_limit_exceeded": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class FakeAdapter:
    def __init__(self, content: str = "") -> None:
        self.content = content or _valid_draft_json()
        self.call_count = 0
        self.timeouts: list[float] = []
        self.failure: ModelInvocationError | None = None

    async def invoke(self, envelope: object, timeout_seconds: float) -> ModelInvocationResult:
        self.call_count += 1
        self.timeouts.append(timeout_seconds)
        if self.failure is not None:
            raise self.failure
        return ModelInvocationResult(content=self.content, usage=MappingProxyType(USAGE))


class EmptyEntityRepository:
    def __init__(self) -> None:
        self.call_count = 0

    async def search_batch(self, dataset_version: str, mentions: object):
        self.call_count += 1
        return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ServiceFixture:
    service: IntentResolverService
    adapter: FakeAdapter
    entity_repository: EmptyEntityRepository
    context: RequestContext


@pytest.fixture
def service_fixture() -> ServiceFixture:
    catalog = load_catalog(PROJECT_ROOT)
    manifest = build_manifest(
        catalog,
        {
            "normalizer_version": NORMALIZER_VERSION,
            "candidate_policy_version": CANDIDATE_POLICY_VERSION,
            "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
            "adapter_version": ADAPTER_VERSION,
        },
    )
    adapter = FakeAdapter()
    entity_repository = EmptyEntityRepository()
    context = _context()
    service = IntentResolverService(
        adapter=adapter,
        entity_repository=entity_repository,
        catalog=catalog,
        manifest=manifest,
        active_dataset_pin=ActiveDatasetPin(
            dataset_version=context.dataset_version,
            manifest_hash="a" * 64,
        ),
        utcnow=lambda: NOW,
    )
    return ServiceFixture(service, adapter, entity_repository, context)


@pytest.mark.asyncio
async def test_resolve_once_calls_model_exactly_once(
    service_fixture: ServiceFixture,
) -> None:
    result = await service_fixture.service.resolve_once(service_fixture.context)

    assert service_fixture.adapter.call_count == 1
    assert result.resolution.resolution_status is ResolutionStatus.RESOLVED


@pytest.mark.asyncio
async def test_schema_failure_does_not_retry_inside_service(
    service_fixture: ServiceFixture,
) -> None:
    service_fixture.adapter.content = "{}"

    with pytest.raises(ResolverContractError, match=MODEL_SCHEMA_INVALID):
        await service_fixture.service.resolve_once(service_fixture.context)

    assert service_fixture.adapter.call_count == 1


@pytest.mark.asyncio
async def test_duplicate_model_keys_are_rejected_without_retry(
    service_fixture: ServiceFixture,
) -> None:
    service_fixture.adapter.content = '{"evidence_spans":[],"evidence_spans":[]}'

    with pytest.raises(ResolverContractError, match=MODEL_SCHEMA_INVALID):
        await service_fixture.service.resolve_once(service_fixture.context)

    assert service_fixture.adapter.call_count == 1


@pytest.mark.asyncio
async def test_provider_failure_is_preserved_without_semantic_conversion(
    service_fixture: ServiceFixture,
) -> None:
    service_fixture.adapter.failure = ModelInvocationError(MODEL_RATE_LIMITED)

    with pytest.raises(ModelInvocationError) as error:
        await service_fixture.service.resolve_once(service_fixture.context)

    assert error.value.code == MODEL_RATE_LIMITED
    assert service_fixture.adapter.call_count == 1


@pytest.mark.asyncio
async def test_prepare_rejects_input_and_pin_mismatch_before_model(
    service_fixture: ServiceFixture,
) -> None:
    oversized = _context("가" * 4097)
    mismatched = _context(dataset_version="different-dataset")

    with pytest.raises(ValueError, match="REQUEST_CONTRACT_INVALID"):
        await service_fixture.service.resolve_once(oversized)
    with pytest.raises(ResolverInvariantError, match="CATALOG_VERSION_MISMATCH"):
        await service_fixture.service.resolve_once(mismatched)

    assert service_fixture.adapter.call_count == 0
    assert service_fixture.entity_repository.call_count == 0


@pytest.mark.asyncio
async def test_prepare_accepts_sixteen_entity_mentions(
    service_fixture: ServiceFixture,
) -> None:
    await service_fixture.service.prepare(_context(entity_mention_count=16))

    assert service_fixture.entity_repository.call_count == 1
    assert service_fixture.adapter.call_count == 0


@pytest.mark.asyncio
async def test_prepare_rejects_seventeen_entity_mentions_before_repository(
    service_fixture: ServiceFixture,
) -> None:
    with pytest.raises(ValueError, match="REQUEST_CONTRACT_INVALID"):
        await service_fixture.service.prepare(_context(entity_mention_count=17))

    assert service_fixture.entity_repository.call_count == 0
    assert service_fixture.adapter.call_count == 0


@pytest.mark.asyncio
async def test_model_timeout_is_derived_from_request_deadline(
    service_fixture: ServiceFixture,
) -> None:
    await service_fixture.service.resolve_once(service_fixture.context)

    assert service_fixture.adapter.timeouts == [pytest.approx(8.0)]


@pytest.mark.asyncio
async def test_resolution_metadata_and_ids_are_deterministic(
    service_fixture: ServiceFixture,
) -> None:
    prepared = await service_fixture.service.prepare(service_fixture.context)

    first = service_fixture.service.validate_response(prepared, _valid_draft_json())
    second = service_fixture.service.validate_response(prepared, _valid_draft_json())

    assert first == second
    assert first.request_key == service_fixture.context.request_key
    assert first.run_id == service_fixture.context.run_id
    assert first.dataset_version == service_fixture.context.dataset_version
    assert first.created_at == service_fixture.context.created_at
    assert first.draft_hash == canonical_sha256(
        json.loads(_valid_draft_json())
    )
    assert first.resolution_id.startswith("resolution-")
    assert first.build_manifest == prepared.view.build_manifest
    assert first.active_dataset_manifest_hash == "a" * 64


@pytest.mark.asyncio
async def test_unique_evidence_text_repairs_only_model_offsets(
    service_fixture: ServiceFixture,
) -> None:
    prepared = await service_fixture.service.prepare(service_fixture.context)
    payload = json.loads(_valid_draft_json())
    payload['evidence_spans'][0]['start_char'] = 1
    payload['evidence_spans'][0]['end_char'] = 4

    resolution = service_fixture.service.validate_response(
        prepared, json.dumps(payload, ensure_ascii=False)
    )

    payload['evidence_spans'][0]['start_char'] = 0
    payload['evidence_spans'][0]['end_char'] = 3
    assert resolution.draft_hash == canonical_sha256(payload)


@pytest.mark.asyncio
async def test_ambiguous_evidence_text_does_not_repair_model_offsets(
    service_fixture: ServiceFixture,
) -> None:
    context = _context('AUM AUM 알려줘')
    prepared = await service_fixture.service.prepare(context)
    payload = json.loads(_valid_draft_json())
    payload['evidence_spans'][0]['start_char'] = 1
    payload['evidence_spans'][0]['end_char'] = 4

    with pytest.raises(ResolverContractError, match='LITERAL_SPAN_MISMATCH'):
        service_fixture.service.validate_response(
            prepared, json.dumps(payload, ensure_ascii=False)
        )


@pytest.mark.asyncio
async def test_telemetry_contains_only_safe_stage_metrics(
    service_fixture: ServiceFixture,
) -> None:
    raw_content = _valid_draft_json()
    service_fixture.adapter.content = raw_content

    result = await service_fixture.service.resolve_once(service_fixture.context)
    telemetry = result.telemetry.model_dump(mode="json")

    assert set(telemetry) == {
        "normalization_ms",
        "candidate_ms",
        "model_ms",
        "validation_ms",
        "semantic_candidate_count",
        "entity_candidate_count",
        "frame_count",
        "context_link_count",
        "usage",
        "stable_code",
    }
    assert telemetry["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    assert telemetry["semantic_candidate_count"] >= 1
    assert telemetry["entity_candidate_count"] == 0
    assert telemetry["frame_count"] == 1
    assert telemetry["context_link_count"] == 0
    assert telemetry["stable_code"] == "RESOLUTION_VALIDATED"
    serialized = json.dumps(telemetry, ensure_ascii=False, sort_keys=True)
    assert service_fixture.context.question not in serialized
    assert raw_content not in serialized
    assert service_fixture.context.question not in repr(result.telemetry)
    assert raw_content not in repr(result.telemetry)


@pytest.mark.asyncio
async def test_repair_builder_reuses_view_and_schema_without_calling_model(
    service_fixture: ServiceFixture,
) -> None:
    prepared = await service_fixture.service.prepare(service_fixture.context)
    invalid_raw_content = "PRIVATE INVALID MODEL CONTENT"

    repair = build_repair_envelope(
        prepared,
        ResolverContractError(MODEL_UNKNOWN_ID),
    )
    payload = json.loads(repair.user_message)

    assert repair.response_schema == prepared.prompt.response_schema
    assert set(payload) == {
        "context",
        "view",
        "original_prompt_hash",
        "failure_code",
        "correction_instruction",
    }
    assert payload["context"] == prepared.context.model_dump(mode="json")
    assert payload["view"] == prepared.view.model_dump(mode="json")
    assert payload["failure_code"] == MODEL_UNKNOWN_ID
    assert len(payload["original_prompt_hash"]) == 64
    assert payload["correction_instruction"]
    assert invalid_raw_content not in repair.system_message
    assert invalid_raw_content not in repair.user_message
    assert service_fixture.adapter.call_count == 0
