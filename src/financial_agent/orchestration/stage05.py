"""Evidence-bound Stage 05 adapters for server-owned semantic tool tasks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping, Protocol

from financial_agent.contracts.canonical import canonical_json_bytes
from financial_agent.contracts.enums import Capability, Cardinality, ToolStatus
from financial_agent.contracts.execution import BindingValue, ResultField, ResultRow
from financial_agent.contracts.values import decode_contract_value, encode_contract_value
from financial_agent.documents import SectionType
from financial_agent.graph.client import GraphQueryResult
from financial_agent.graph.contract import APPROVED_PREDICATES
from financial_agent.graph.queries import build_relation_query
from financial_agent.planning.logical_query import LogicalQueryTaskV2
from financial_agent.planning.primitive_contracts import RELATION_CONCEPT_IDS
from financial_agent.retrieval import (
    DocumentCandidateRepository,
    DocumentEvidencePromoter,
    DocumentSearchRequest,
    reciprocal_rank_fusion,
)

from .executors import (
    CapabilityExecutor,
    ExecutorRequest,
    build_tool_result,
)
from .semantic_execution import SemanticToolTaskExecutionInput


class GraphSelectClient(Protocol):
    def select(
        self,
        *,
        query_id: str,
        sparql: str,
        dataset_version: str,
        coverage_status: str,
    ) -> GraphQueryResult: ...


@dataclass(frozen=True, slots=True)
class QueryEmbedding:
    model_id: str
    model_version: str
    values: tuple[float, ...]


QueryEmbeddingProvider = Callable[
    [str],
    QueryEmbedding
    | tuple[str, str, tuple[float, ...]]
    | Awaitable[QueryEmbedding | tuple[str, str, tuple[float, ...]]],
]


@dataclass(frozen=True, slots=True)
class _DocumentTopicPolicy:
    claim_type: str
    section_types: tuple[SectionType, ...]
    query_text: str


_DOCUMENT_TOPICS: Mapping[str, _DocumentTopicPolicy] = MappingProxyType(
    {
        "investment_strategy": _DocumentTopicPolicy(
            "investment_strategy",
            (SectionType.INVESTMENT_OBJECTIVE, SectionType.INVESTMENT_STRATEGY),
            "투자 목적 주요 투자대상 투자 전략",
        ),
        "risk_factor": _DocumentTopicPolicy(
            "risk_factor",
            (SectionType.RISK_FACTOR,),
            "주요 투자위험 위험 요인",
        ),
        "official_update": _DocumentTopicPolicy(
            "official_update",
            (SectionType.OFFICIAL_UPDATE, SectionType.CHANGE_HISTORY),
            "공식 변경 공시 변경 이력",
        ),
        "product_structure": _DocumentTopicPolicy(
            "structure",
            (SectionType.LEGAL_STRUCTURE,),
            "상품 구조 법적 구조",
        ),
        "supporting_document": _DocumentTopicPolicy(
            "publisher_provenance",
            (
                SectionType.INVESTMENT_OBJECTIVE,
                SectionType.INVESTMENT_STRATEGY,
                SectionType.RISK_FACTOR,
            ),
            "공식 문서 근거",
        ),
    }
)


class GraphCapabilityExecutor(CapabilityExecutor):
    """Execute one approved relation traversal and preserve its Evidence IDs."""

    def __init__(self, client: GraphSelectClient) -> None:
        self._client = client

    async def execute(self, request: ExecutorRequest):
        request = _require_tool_request(
            request,
            Capability.GRAPH_TRAVERSAL,
            "GRAPH_TRAVERSAL_REQUEST_REQUIRED",
        )
        logical_task = request.logical_task()
        predicate_id = _relation_predicate(logical_task)
        entity_scope = _entity_scope(request)
        if not entity_scope:
            raise ValueError("GRAPH_ENTITY_SCOPE_REQUIRED")
        query_id = f"relation:{predicate_id}:{request.dataset_version}"
        result = await asyncio.to_thread(
            self._client.select,
            query_id=query_id,
            sparql=build_relation_query(
                predicate_id,
                request.dataset_version,
                entity_ids=tuple(sorted(entity_scope)),
            ),
            dataset_version=request.dataset_version,
            coverage_status="bounded_unknown",
        )
        if result.dataset_version != request.dataset_version:
            raise ValueError("GRAPH_DATASET_VERSION_MISMATCH")

        rows: list[ResultRow] = []
        evidence_ids: set[str] = set()
        for binding in result.bindings:
            _validate_graph_binding(binding, predicate_id, request.dataset_version)
            if not ({binding["subject_id"], binding["object_id"]} & entity_scope):
                continue
            evidence_ids.add(binding["evidence_id"])
            fields = tuple(
                ResultField(field_id=field_id, value=encode_contract_value(value))
                for field_id, value in (
                    ("subject_id", binding["subject_id"]),
                    ("predicate_id", binding["predicate_id"]),
                    ("object_id", binding["object_id"]),
                    ("relation_assertion_id", binding["relation_assertion_id"]),
                    ("valid_from", binding.get("valid_from")),
                    ("valid_to", binding.get("valid_to")),
                    ("evidence_id", binding["evidence_id"]),
                )
            )
            rows.append(
                ResultRow(
                    row_id=binding["relation_assertion_id"],
                    entity_ids=(binding["subject_id"], binding["object_id"]),
                    fields=fields,
                )
            )
        ordered_rows = tuple(sorted(rows, key=lambda item: item.row_id))
        status = ToolStatus.SUCCESS if ordered_rows else ToolStatus.EMPTY
        return build_tool_result(
            request,
            status=status,
            result_rows=ordered_rows,
            binding_values=(
                _result_bindings(request, ordered_rows) if ordered_rows else ()
            ),
            evidence_refs=tuple(sorted(evidence_ids)),
            latency_ms=0,
        )


class DocumentSearchCapabilityExecutor(CapabilityExecutor):
    """Search bounded official documents and promote every returned candidate."""

    def __init__(
        self,
        candidates: DocumentCandidateRepository,
        promoter: DocumentEvidencePromoter,
        *,
        query_embedding_provider: QueryEmbeddingProvider | None = None,
        top_k: int = 5,
    ) -> None:
        if top_k < 1 or top_k > 50:
            raise ValueError("DOCUMENT_SEARCH_TOP_K_INVALID")
        self._candidates = candidates
        self._promoter = promoter
        self._query_embedding_provider = query_embedding_provider
        self._top_k = top_k

    async def execute(self, request: ExecutorRequest):
        request = _require_tool_request(
            request,
            Capability.KEYWORD_SEARCH,
            "DOCUMENT_SEARCH_REQUEST_REQUIRED",
        )
        logical_task = request.logical_task()
        if logical_task.operation.operation_type != "explain":
            raise ValueError("DOCUMENT_EXPLANATION_TASK_REQUIRED")
        topic_id = logical_task.operation.explanation.topic_concept_id
        if topic_id is None:
            raise ValueError("DOCUMENT_TOPIC_REQUIRED")
        policy = _DOCUMENT_TOPICS.get(topic_id)
        if policy is None:
            raise ValueError("DOCUMENT_TOPIC_NOT_REGISTERED")
        entity_scope = tuple(sorted(_entity_scope(request)))
        if not entity_scope:
            raise ValueError("DOCUMENT_ENTITY_SCOPE_REQUIRED")

        embedding: QueryEmbedding | None = None
        if self._query_embedding_provider is not None:
            provided = self._query_embedding_provider(policy.query_text)
            if inspect.isawaitable(provided):
                provided = await provided
            embedding = (
                provided
                if isinstance(provided, QueryEmbedding)
                else QueryEmbedding(*provided)
            )
        search_request = DocumentSearchRequest(
            dataset_version=request.dataset_version,
            entity_ids=entity_scope,
            claim_type=policy.claim_type,
            section_types=policy.section_types,
            cutoff_date=request.cutoff_date,
            top_k=self._top_k,
            query_embedding=None if embedding is None else embedding.values,
            model_id=None if embedding is None else embedding.model_id,
            model_version=None if embedding is None else embedding.model_version,
        )
        keyword_hits = await self._candidates.search_keyword(
            search_request, policy.query_text
        )
        vector_hits = (
            await self._candidates.search_vector(search_request)
            if embedding is not None
            else ()
        )
        fused = reciprocal_rank_fusion(
            keyword_hits,
            vector_hits,
            top_k=self._top_k,
        )
        if not fused:
            return build_tool_result(
                request,
                status=ToolStatus.EMPTY,
                latency_ms=0,
            )

        rows: list[ResultRow] = []
        evidence_ids: list[str] = []
        for hit in fused:
            promoted = await self._promoter.promote(
                hit,
                claim_type=policy.claim_type,
            )
            evidence_ids.append(promoted.evidence.evidence_id)
            rows.append(
                ResultRow(
                    row_id=hit.chunk_id,
                    entity_ids=(hit.entity_id,),
                    fields=tuple(
                        ResultField(
                            field_id=field_id,
                            value=encode_contract_value(value),
                        )
                        for field_id, value in (
                            ("document_id", hit.document_id),
                            ("chunk_id", hit.chunk_id),
                            ("section_type", hit.section_type.value),
                            ("chunk_text", hit.exact_text),
                            ("source_id", hit.source_id),
                            ("source_locator", hit.source_locator),
                            ("document_version", hit.document_version),
                            ("published_at", hit.published_at),
                            ("available_at", hit.available_at),
                            ("evidence_id", promoted.evidence.evidence_id),
                        )
                    ),
                )
            )
        ordered_rows = tuple(rows)
        return build_tool_result(
            request,
            status=ToolStatus.SUCCESS,
            result_rows=ordered_rows,
            binding_values=_result_bindings(request, ordered_rows),
            evidence_refs=tuple(evidence_ids),
            latency_ms=0,
        )


def _require_tool_request(
    request: ExecutorRequest,
    capability: Capability,
    error_code: str,
) -> SemanticToolTaskExecutionInput:
    if not isinstance(request, SemanticToolTaskExecutionInput):
        raise ValueError(error_code)
    request = SemanticToolTaskExecutionInput.model_validate_json(
        canonical_json_bytes(request)
    )
    if request.task.capability is not capability:
        raise ValueError(error_code)
    return request


def _relation_predicate(task: LogicalQueryTaskV2) -> str:
    operation = task.operation
    if operation.operation_type == "lookup":
        concept_ids = set(operation.projections.field_concept_ids)
    elif operation.operation_type == "screen":
        concept_ids = _predicate_ids(operation.predicate)
    elif operation.operation_type == "compare":
        concept_ids = set(operation.comparison.metric_concept_ids)
    elif operation.operation_type == "explain":
        concept_ids = {operation.explanation.topic_concept_id}
    else:
        concept_ids = set()
    relations = tuple(sorted(concept_ids & RELATION_CONCEPT_IDS))
    if len(relations) != 1 or relations[0] not in APPROVED_PREDICATES:
        raise ValueError("GRAPH_SINGLE_APPROVED_PREDICATE_REQUIRED")
    return relations[0]


def _predicate_ids(predicate) -> set[str]:
    if predicate.node_type == "atom":
        return {predicate.field_concept_id}
    if predicate.node_type == "not":
        return _predicate_ids(predicate.child)
    return {
        field_id
        for child in predicate.children
        for field_id in _predicate_ids(child)
    }


def _entity_scope(request: SemanticToolTaskExecutionInput) -> set[str]:
    entity_ids = set(request.logical_task().scope.entity_refs)
    for binding in request.binding_values:
        decoded = decode_contract_value(binding.value)
        values = decoded if isinstance(decoded, tuple) else (decoded,)
        if any(not isinstance(item, str) for item in values):
            raise ValueError("SEMANTIC_ENTITY_BINDING_REQUIRED")
        entity_ids.update(values)
    return entity_ids


def _validate_graph_binding(
    binding: Mapping[str, str],
    predicate_id: str,
    dataset_version: str,
) -> None:
    required = {
        "subject_id",
        "predicate_id",
        "object_id",
        "relation_assertion_id",
        "evidence_id",
        "dataset_version",
    }
    if not required <= set(binding) or any(not binding[key] for key in required):
        raise ValueError("GRAPH_EVIDENCE_BINDING_REQUIRED")
    if binding["predicate_id"] != predicate_id:
        raise ValueError("GRAPH_PREDICATE_MISMATCH")
    if binding["dataset_version"] != dataset_version:
        raise ValueError("GRAPH_DATASET_VERSION_MISMATCH")


def _result_bindings(
    request: SemanticToolTaskExecutionInput,
    rows: tuple[ResultRow, ...],
) -> tuple[BindingValue, ...]:
    if not request.task.produces_bindings:
        return ()
    entity_ids = tuple(
        sorted({entity_id for row in rows for entity_id in row.entity_ids})
    )
    values: list[BindingValue] = []
    for binding_name in request.task.produces_bindings:
        logical_binding = next(
            item
            for item in request.logical_task().produced_result_bindings
            if item.binding_id == binding_name
        )
        if logical_binding.cardinality is Cardinality.ONE:
            if len(entity_ids) != 1:
                raise ValueError("SEMANTIC_BINDING_CARDINALITY_MISMATCH")
            value = entity_ids[0]
        else:
            value = entity_ids
        values.append(
            BindingValue(
                binding_name=binding_name,
                value_type=request.binding_type(binding_name),
                value=encode_contract_value(value),
            )
        )
    return tuple(values)


__all__ = [
    "DocumentSearchCapabilityExecutor",
    "GraphCapabilityExecutor",
    "GraphSelectClient",
    "QueryEmbedding",
    "QueryEmbeddingProvider",
]
