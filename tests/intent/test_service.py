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
from financial_agent.intent.candidates import EntityCandidate
from financial_agent.intent.clova import ModelInvocationResult
from financial_agent.intent.errors import (
    MODEL_INVALID_FRAME_REFERENCE,
    MODEL_INVALID_SEMANTIC_COVERAGE,
    MODEL_PROPOSAL_SCHEMA_INVALID,
    MODEL_RATE_LIMITED,
    MODEL_UNKNOWN_EVIDENCE_ID,
    ModelInvocationError,
    ResolverContractError,
)
from financial_agent.intent.assembler import assemble_proposal
from financial_agent.intent.proposal import IntentResolutionProposalV2
from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.service import (
    IntentResolverService,
    build_repair_envelope,
)
from financial_agent.intent.task_binding import TaskReadiness
from financial_agent.intent.task_contracts import load_task_contract_registry
from financial_agent.intent.types import EntitySemanticRole, ResolutionStatus
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


def _valid_proposal_json() -> str:
    return json.dumps(
        {
            "proposal_schema_version": "2.0",
            "frames": [
                {
                    "segment_ids": ["s1"],
                    "action_choice": {
                        "state": "selected",
                        "selected_ids": ["lookup"],
                        "evidence_ids": [
                            "evidence-a4208ee0fa533668a8a940c689a1679fe884c1eb625111b2f460a419083120b6"
                        ],
                        "reason_code": "explicit",
                    },
                    "product_family_choice": {
                        "state": "selected",
                        "selected_ids": ["domestic_etf"],
                        "evidence_ids": [
                            "evidence-b06c0195af8f0cabcfc40852f3f891cb3fca54b4498f59473de4db364e1fc75c"
                        ],
                        "reason_code": "explicit",
                    },
                    "entity_type_ids": ["FinancialProduct"],
                    "semantic_coverage": {
                        "state": "covered",
                        "reason": "none",
                        "evidence_ids": [],
                    },
                    "slot_assignments": [
                        {
                            "slot_kind": "metric",
                            "value_ids": ["aum"],
                            "evidence_ids": [
                                "evidence-b06c0195af8f0cabcfc40852f3f891cb3fca54b4498f59473de4db364e1fc75c"
                            ],
                            "reason_code": "explicit",
                        }
                    ],
                    "entity_hints": [],
                    "produced_result_hints": ["candidates"],
                }
            ],
            "references": [],
            "context_links": [],
            "slot_mutations": [],
            "semantic_flag_hints": [],
            "frame_limit_exceeded": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _managed_by_proposal_json(evidence_id: str) -> str:
    return json.dumps(
        {
            "proposal_schema_version": "2.0",
            "frames": [
                {
                    "segment_ids": ["s1"],
                    "action_choice": {
                        "state": "selected",
                        "selected_ids": ["lookup"],
                        "evidence_ids": [evidence_id],
                        "reason_code": "explicit",
                    },
                    "product_family_choice": {
                        "state": "selected",
                        "selected_ids": ["domestic_etf"],
                        "evidence_ids": [evidence_id],
                        "reason_code": "explicit",
                    },
                    "entity_type_ids": ["ETF"],
                    "semantic_coverage": {
                        "state": "covered",
                        "reason": "none",
                        "evidence_ids": [],
                    },
                    "slot_assignments": [
                        {
                            "slot_kind": "relation",
                            "value_ids": ["managedBy"],
                            "evidence_ids": [evidence_id],
                            "reason_code": "explicit",
                        }
                    ],
                    "entity_hints": [
                        {
                            "semantic_role": "relation_object",
                            "relation_id": ["managedBy"],
                            "expected_entity_type_ids": ["AssetManager"],
                            "mention_id": ["mention-manager"],
                            "candidate_entity_ids": ["manager-samsung"],
                            "selected_candidate_ids": ["manager-samsung"],
                        }
                    ],
                    "produced_result_hints": ["relation_target"],
                }
            ],
            "references": [],
            "context_links": [],
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
        self.content = content or _valid_proposal_json()
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
        self.responses = MappingProxyType({})

    async def search_batch(self, dataset_version: str, mentions: object):
        self.call_count += 1
        return self.responses


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
        task_contract_registry=load_task_contract_registry(PROJECT_ROOT),
    )
    return ServiceFixture(service, adapter, entity_repository, context)


@pytest.mark.asyncio
async def test_resolve_once_parses_proposal_then_assembles_once(
    service_fixture: ServiceFixture,
) -> None:
    result = await service_fixture.service.resolve_once(service_fixture.context)

    assert service_fixture.adapter.call_count == 1
    assert isinstance(result.resolution, ValidatedIntentResolutionV2)
    assert result.resolution.canonical_frames[0].frame_id == "frame-0000"
    assert result.resolution.resolution_status is ResolutionStatus.RESOLVED


@pytest.mark.asyncio
async def test_resolve_task_bound_separates_axes_from_server_slot_binding(
    service_fixture: ServiceFixture,
) -> None:
    payload = json.loads(_valid_proposal_json())
    payload["frames"][0]["slot_assignments"] = []
    service_fixture.adapter.content = json.dumps(payload, ensure_ascii=False)

    result = await service_fixture.service.resolve_task_bound(service_fixture.context)

    assert service_fixture.adapter.call_count == 1
    assert result.resolution.task_contracts[0].contract_id == "lookup.v1"
    assert result.resolution.task_contracts[0].readiness is TaskReadiness.COMPLETE
    assert result.resolution.conditional_slot_call_used is False


@pytest.mark.asyncio
async def test_resolve_task_bound_rejects_model_authored_task_slots(
    service_fixture: ServiceFixture,
) -> None:
    with pytest.raises(ResolverContractError, match=MODEL_PROPOSAL_SCHEMA_INVALID):
        await service_fixture.service.resolve_task_bound(service_fixture.context)

    assert service_fixture.adapter.call_count == 1


@pytest.mark.asyncio
async def test_service_preserves_managed_by_object_role(
    service_fixture: ServiceFixture,
) -> None:
    question = "KODEX 200 운용사 삼성자산운용"
    context = _context(question).model_copy(
        update={
            "named_entities": (
                NamedEntityMention(
                    mention_id="mention-etf",
                    segment_id="s1",
                    text="KODEX 200",
                    expected_entity_types=("ETF",),
                ),
                NamedEntityMention(
                    mention_id="mention-manager",
                    segment_id="s1",
                    text="삼성자산운용",
                    expected_entity_types=("AssetManager",),
                ),
            )
        }
    )
    service_fixture.entity_repository.responses = MappingProxyType(
        {
            "mention-etf": (
                EntityCandidate(
                    entity_id="etf-kodex200",
                    canonical_name="KODEX 200",
                    ontology_type_ids=("DomesticETF", "ETF", "FinancialProduct"),
                    product_family="domestic_etf",
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="source-etf-kodex200",
                ),
            ),
            "mention-manager": (
                EntityCandidate(
                    entity_id="manager-samsung",
                    canonical_name="삼성자산운용",
                    ontology_type_ids=("AssetManager", "Organization"),
                    product_family=None,
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="source-manager-samsung",
                ),
            ),
        }
    )
    prepared = await service_fixture.service.prepare(context)
    relation_evidence_id = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if "managedBy" in item.offered_semantic_ids
    )
    service_fixture.adapter.content = _managed_by_proposal_json(relation_evidence_id)

    attempt = await service_fixture.service.resolve_once(context)
    hint = attempt.resolution.entity_hints[0]

    assert service_fixture.adapter.call_count == 1
    assert hint.semantic_role is EntitySemanticRole.RELATION_OBJECT
    assert hint.relation_id == ("managedBy",)
    assert hint.expected_entity_type_ids == ("AssetManager",)


@pytest.mark.asyncio
async def test_task_bound_relation_is_server_projected_from_axis_entity_hint(
    service_fixture: ServiceFixture,
) -> None:
    question = "KODEX 200 운용사 삼성자산운용"
    context = _context(question).model_copy(
        update={
            "named_entities": (
                NamedEntityMention(
                    mention_id="mention-etf",
                    segment_id="s1",
                    text="KODEX 200",
                    expected_entity_types=("ETF",),
                ),
                NamedEntityMention(
                    mention_id="mention-manager",
                    segment_id="s1",
                    text="삼성자산운용",
                    expected_entity_types=("AssetManager",),
                ),
            )
        }
    )
    service_fixture.entity_repository.responses = MappingProxyType(
        {
            "mention-etf": (
                EntityCandidate(
                    entity_id="etf-kodex200",
                    canonical_name="KODEX 200",
                    ontology_type_ids=("DomesticETF", "ETF", "FinancialProduct"),
                    product_family="domestic_etf",
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="source-etf-kodex200",
                ),
            ),
            "mention-manager": (
                EntityCandidate(
                    entity_id="manager-samsung",
                    canonical_name="삼성자산운용",
                    ontology_type_ids=("AssetManager", "Organization"),
                    product_family=None,
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="source-manager-samsung",
                ),
            ),
        }
    )
    prepared = await service_fixture.service.prepare(context)
    evidence_id = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if "managedBy" in item.offered_semantic_ids
    )
    payload = json.loads(_managed_by_proposal_json(evidence_id))
    payload["frames"][0]["slot_assignments"] = []
    service_fixture.adapter.content = json.dumps(payload, ensure_ascii=False)

    attempt = await service_fixture.service.resolve_task_bound(context)
    contract = attempt.resolution.task_contracts[0]

    assert service_fixture.adapter.call_count == 1
    assert contract.readiness is TaskReadiness.COMPLETE
    assert {
        binding.slot_kind.value: binding.value_ids for binding in contract.bindings
    }["relation"] == ("managedBy",)


@pytest.mark.asyncio
async def test_schema_failure_does_not_retry_inside_service(
    service_fixture: ServiceFixture,
) -> None:
    service_fixture.adapter.content = "{}"

    with pytest.raises(ResolverContractError, match=MODEL_PROPOSAL_SCHEMA_INVALID):
        await service_fixture.service.resolve_once(service_fixture.context)

    assert service_fixture.adapter.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.update({"frames": []}),
        lambda payload: payload["frames"][0]["action_choice"].update(
            {"selected_ids": ["lookup", "compare"]}
        ),
    ),
)
async def test_empty_resolution_and_two_actions_are_rejected_end_to_end(
    service_fixture: ServiceFixture,
    mutation,
) -> None:
    payload = json.loads(_valid_proposal_json())
    mutation(payload)
    service_fixture.adapter.content = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(ResolverContractError, match=MODEL_PROPOSAL_SCHEMA_INVALID):
        await service_fixture.service.resolve_once(service_fixture.context)

    assert service_fixture.adapter.call_count == 1


@pytest.mark.asyncio
async def test_duplicate_model_keys_are_rejected_without_retry(
    service_fixture: ServiceFixture,
) -> None:
    service_fixture.adapter.content = '{"frames":[],"frames":[]}'

    with pytest.raises(ResolverContractError, match=MODEL_PROPOSAL_SCHEMA_INVALID):
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
async def test_model_timeout_is_not_capped_at_twenty_seconds(
    service_fixture: ServiceFixture,
) -> None:
    await service_fixture.service.resolve_once(_context(deadline_seconds=55.0))

    assert service_fixture.adapter.timeouts == [pytest.approx(55.0)]


@pytest.mark.asyncio
async def test_resolution_metadata_and_ids_are_deterministic(
    service_fixture: ServiceFixture,
) -> None:
    prepared = await service_fixture.service.prepare(service_fixture.context)

    first = service_fixture.service.validate_response(prepared, _valid_proposal_json())
    second = service_fixture.service.validate_response(prepared, _valid_proposal_json())

    assert first == second
    assert first.request_key == service_fixture.context.request_key
    assert first.run_id == service_fixture.context.run_id
    assert first.dataset_version == service_fixture.context.dataset_version
    assert first.created_at == service_fixture.context.created_at
    assembled = assemble_proposal(
        IntentResolutionProposalV2.model_validate_json(_valid_proposal_json()),
        prepared.normalized,
        prepared.view,
        load_catalog(PROJECT_ROOT),
    )
    assert first.draft_hash == canonical_sha256(assembled)
    assert first.resolution_id.startswith("resolution-")
    assert first.build_manifest == prepared.view.build_manifest
    assert first.active_dataset_manifest_hash == "a" * 64


@pytest.mark.asyncio
async def test_unknown_evidence_does_not_retry(
    service_fixture: ServiceFixture,
) -> None:
    payload = json.loads(_valid_proposal_json())
    payload["frames"][0]["action_choice"]["evidence_ids"] = ["unknown-evidence"]
    service_fixture.adapter.content = json.dumps(payload, ensure_ascii=False)

    with pytest.raises(ResolverContractError, match=MODEL_UNKNOWN_EVIDENCE_ID):
        await service_fixture.service.resolve_once(service_fixture.context)

    assert service_fixture.adapter.call_count == 1


@pytest.mark.asyncio
async def test_telemetry_contains_only_safe_stage_metrics(
    service_fixture: ServiceFixture,
) -> None:
    raw_content = _valid_proposal_json()
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
@pytest.mark.parametrize(
    "failure_code",
    (
        MODEL_PROPOSAL_SCHEMA_INVALID,
        MODEL_UNKNOWN_EVIDENCE_ID,
        MODEL_INVALID_FRAME_REFERENCE,
        MODEL_INVALID_SEMANTIC_COVERAGE,
    ),
)
async def test_repair_builder_reuses_view_and_schema_without_calling_model(
    service_fixture: ServiceFixture,
    failure_code: str,
) -> None:
    prepared = await service_fixture.service.prepare(service_fixture.context)
    invalid_raw_content = "PRIVATE INVALID MODEL CONTENT"

    repair = build_repair_envelope(
        prepared,
        ResolverContractError(failure_code),
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
    assert payload["failure_code"] == failure_code
    assert len(payload["original_prompt_hash"]) == 64
    assert "offered" in payload["correction_instruction"]
    assert invalid_raw_content not in repair.system_message
    assert invalid_raw_content not in repair.user_message
    assert service_fixture.adapter.call_count == 0
