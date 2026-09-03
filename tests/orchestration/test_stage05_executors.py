from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest

from financial_agent.contracts import (
    CutoffStatus,
    EvidenceKind,
    EvidenceRecord,
    SourceLocator,
)
from financial_agent.contracts.enums import Capability, ToolStatus
from financial_agent.contracts.values import decode_contract_value
from financial_agent.graph.client import GraphQueryResult
from financial_agent.intent.query_contract_solver import QueryContractCandidate
from financial_agent.orchestration.semantic_execution import (
    SemanticToolTaskExecutionInput,
)
from financial_agent.orchestration.executors import ExecutorRegistry
from financial_agent.orchestration.graph import ExecutionGraphCompiler
from financial_agent.orchestration.semantic_graph import SemanticExecutionGraphCompiler
from financial_agent.orchestration.service import Orchestrator
from financial_agent.orchestration.stage05 import (
    DocumentSearchCapabilityExecutor,
    GraphCapabilityExecutor,
)
from financial_agent.planning.registry import load_planning_registry
from financial_agent.retrieval import DocumentCandidateHit
from financial_agent.documents import SectionType
from financial_agent.release import EvidenceBundleAssembler

from tests.orchestration.test_semantic_graph import PROJECT_ROOT
from tests.planning.test_semantic_compiler import ADAPTER, _assessment, _base, _compile


def _compilation(*, kind: str):
    if kind == "graph":
        payload = _base("lookup")
        payload["scope"] = {
            "product_family_ids": [],
            "entity_refs": ["product-1"],
            "prior_result_binding": None,
        }
        payload["projections"] = {
            "field_concept_ids": ["managedBy"],
            "default_profile_id": None,
        }
        primitives = ("lookup-products", "traverse-relations")
    else:
        payload = _base("explain")
        payload["scope"] = {
            "product_family_ids": [],
            "entity_refs": ["product-1"],
            "prior_result_binding": None,
        }
        payload["explanation"] = {
            "topic_concept_id": "risk_factor",
            "profile_id": None,
        }
        primitives = ("lookup-products", "search-documents")
    candidate = QueryContractCandidate(
        candidate_id=f"candidate-{kind}",
        contract=ADAPTER.validate_json(json.dumps(payload)),
    )
    return _compile(
        (candidate,),
        (_assessment(candidate),),
        primitive_ids=primitives,
    )


def _request(*, kind: str) -> SemanticToolTaskExecutionInput:
    compilation = _compilation(kind=kind)
    bundle = SemanticExecutionGraphCompiler(
        load_planning_registry(PROJECT_ROOT),
        compiled_request_provider=lambda *_: None,
    ).compile(compilation)
    return SemanticToolTaskExecutionInput(
        request_key=bundle.graph.request_key,
        run_id=bundle.graph.run_id,
        dataset_version=bundle.graph.dataset_version,
        cutoff_date=bundle.graph.cutoff_date,
        created_at=bundle.graph.created_at,
        task=bundle.graph.tasks[0],
        logical_query_plan=bundle.logical_query_plan,
        dependency_results=(),
        binding_values=(),
        binding_types=(),
    )


class _GraphClient:
    def __init__(self, result: GraphQueryResult) -> None:
        self.result = result
        self.calls = []

    def select(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.mark.asyncio
async def test_graph_executor_returns_only_scoped_evidence_bound_relations() -> None:
    request = _request(kind="graph")
    client = _GraphClient(
        GraphQueryResult(
            query_id="ignored",
            dataset_version="dataset-v1",
            coverage_status="bounded_unknown",
            bindings=(
                {
                    "subject_id": "product-2",
                    "predicate_id": "managedBy",
                    "object_id": "manager-2",
                    "relation_assertion_id": "relation-2",
                    "evidence_id": "evidence-2",
                    "dataset_version": "dataset-v1",
                },
                {
                    "subject_id": "product-1",
                    "predicate_id": "managedBy",
                    "object_id": "manager-1",
                    "relation_assertion_id": "relation-1",
                    "evidence_id": "evidence-1",
                    "dataset_version": "dataset-v1",
                    "valid_from": "2026-01-01",
                },
            ),
        )
    )

    result = await GraphCapabilityExecutor(client).execute(request)

    assert result.status is ToolStatus.SUCCESS
    assert result.evidence_refs == ("evidence-1",)
    assert result.result_rows[0].entity_ids == ("product-1", "manager-1")
    fields = {
        item.field_id: decode_contract_value(item.value)
        for item in result.result_rows[0].fields
    }
    assert fields["relation_assertion_id"] == "relation-1"
    assert fields["predicate_id"] == "managedBy"
    assert "<urn:ontology:financial-product:v1#managedBy>" in client.calls[0]["sparql"]
    assert 'VALUES ?scope_id { "product-1" }' in client.calls[0]["sparql"]


@pytest.mark.asyncio
async def test_graph_executor_runs_through_bounded_orchestrator_registry() -> None:
    compilation = _compilation(kind="graph")
    client = _GraphClient(
        GraphQueryResult(
            query_id="q",
            dataset_version="dataset-v1",
            coverage_status="bounded_unknown",
            bindings=(),
        )
    )
    planning = load_planning_registry(PROJECT_ROOT)
    service = Orchestrator(
        graph_compiler=ExecutionGraphCompiler(planning),
        semantic_graph_compiler=SemanticExecutionGraphCompiler(
            planning,
            compiled_request_provider=lambda *_: None,
        ),
        executors=ExecutorRegistry(
            ((Capability.GRAPH_TRAVERSAL, GraphCapabilityExecutor(client)),)
        ),
        hard_deadline_ms=5_000,
    )

    result = await service.execute_semantic(compilation)

    assert result.tool_results[0].status is ToolStatus.EMPTY
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_graph_executor_rejects_unbound_evidence_and_version_drift() -> None:
    request = _request(kind="graph")
    missing = _GraphClient(
        GraphQueryResult(
            query_id="q",
            dataset_version="dataset-v1",
            coverage_status="bounded_unknown",
            bindings=(
                {
                    "subject_id": "product-1",
                    "predicate_id": "managedBy",
                    "object_id": "manager-1",
                    "relation_assertion_id": "relation-1",
                    "dataset_version": "dataset-v1",
                },
            ),
        )
    )
    with pytest.raises(ValueError, match="GRAPH_EVIDENCE_BINDING_REQUIRED"):
        await GraphCapabilityExecutor(missing).execute(request)

    drift = _GraphClient(
        GraphQueryResult(
            query_id="q",
            dataset_version="dataset-v2",
            coverage_status="bounded_unknown",
            bindings=(),
        )
    )
    with pytest.raises(ValueError, match="GRAPH_DATASET_VERSION_MISMATCH"):
        await GraphCapabilityExecutor(drift).execute(request)


def _candidate(*, chunk_id: str, fused_score: float | None = None):
    return DocumentCandidateHit(
        dataset_version="dataset-v1",
        entity_id="product-1",
        document_id="document-1",
        chunk_id=chunk_id,
        section_type=SectionType.RISK_FACTOR,
        exact_text=f"{chunk_id} 위험 설명",
        source_id="source-1",
        source_locator=f"document-1:{chunk_id}",
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
        available_at=datetime(2026, 8, 20, tzinfo=UTC),
        effective_from=request_date(),
        effective_to=None,
        document_version="2026-08-20",
        cutoff_eligible=True,
        publisher_approved=True,
        keyword_rank=1,
        vector_rank=None,
        fused_score=fused_score,
    )


def request_date():
    from datetime import date

    return date(2026, 8, 20)


class _Candidates:
    def __init__(self, keyword=(), vector=()) -> None:
        self.keyword = keyword
        self.vector = vector
        self.requests = []

    async def search_keyword(self, request, query_text):
        self.requests.append((request, query_text))
        return self.keyword

    async def search_vector(self, request):
        self.requests.append((request, "vector"))
        return self.vector


class _Promoter:
    def __init__(self) -> None:
        self.calls = []
        self.evidence_records = []

    async def promote(self, candidate, *, claim_type):
        self.calls.append((candidate, claim_type))
        draft = EvidenceRecord(
            evidence_id=f"evidence-{candidate.chunk_id}",
            evidence_kind=EvidenceKind.DOCUMENT_SPAN,
            source_id=candidate.source_id,
            dataset_version=candidate.dataset_version,
            subject_id=candidate.entity_id,
            predicate_id=claim_type,
            value_or_object_id={"type": "string", "value": candidate.chunk_id},
            normalized_value={"type": "string", "value": candidate.chunk_id},
            source_locator=SourceLocator(
                locator_type="document_span",
                uri_or_object_key=candidate.source_locator,
            ),
            raw_value_repr=candidate.exact_text,
            parser_version="parser-v1",
            mapping_version="mapping-v1",
            cutoff_status=CutoffStatus.ELIGIBLE,
            record_hash="0" * 64,
        )
        from financial_agent.contracts.canonical import canonical_sha256

        evidence = draft.model_copy(
            update={
                "record_hash": canonical_sha256(
                    draft, exclude_fields=("record_hash",)
                )
            }
        )
        self.evidence_records.append(evidence)
        return SimpleNamespace(candidate=candidate, evidence=evidence)


@pytest.mark.asyncio
async def test_document_executor_promotes_fused_candidates_before_success() -> None:
    request = _request(kind="document")
    first = _candidate(chunk_id="chunk-1")
    second = _candidate(chunk_id="chunk-2")
    candidates = _Candidates(keyword=(first,), vector=(second,))
    promoter = _Promoter()

    result = await DocumentSearchCapabilityExecutor(
        candidates,
        promoter,
        query_embedding_provider=lambda _text: ("bge-m3", "1", (0.1, 0.2)),
    ).execute(request)

    assert result.status is ToolStatus.SUCCESS
    assert result.evidence_refs == ("evidence-chunk-1", "evidence-chunk-2")
    assert [call[1] for call in promoter.calls] == ["risk_factor", "risk_factor"]
    assert candidates.requests[0][1] == "주요 투자위험 위험 요인"
    assert candidates.requests[0][0].section_types == (SectionType.RISK_FACTOR,)
    assert candidates.requests[1][0].query_embedding == (0.1, 0.2)
    assert all(row.fields for row in result.result_rows)
    assembly = EvidenceBundleAssembler().assemble(
        (result,), evidence_records=tuple(promoter.evidence_records)
    )
    assert sorted(
        decode_contract_value(claim.value) for claim in assembly.claims
    ) == ["chunk-1 위험 설명", "chunk-2 위험 설명"]


@pytest.mark.asyncio
async def test_document_executor_keeps_empty_candidate_result_nonfactual() -> None:
    request = _request(kind="document")
    result = await DocumentSearchCapabilityExecutor(
        _Candidates(), _Promoter()
    ).execute(request)

    assert result.status is ToolStatus.EMPTY
    assert result.result_rows == ()
    assert result.evidence_refs == ()


@pytest.mark.asyncio
async def test_stage05_executors_reject_wrong_capability() -> None:
    graph_request = _request(kind="graph")
    document_request = _request(kind="document")
    with pytest.raises(ValueError, match="GRAPH_TRAVERSAL_REQUEST_REQUIRED"):
        await GraphCapabilityExecutor(_GraphClient(None)).execute(document_request)
    with pytest.raises(ValueError, match="DOCUMENT_SEARCH_REQUEST_REQUIRED"):
        await DocumentSearchCapabilityExecutor(_Candidates(), _Promoter()).execute(
            graph_request
        )
    assert graph_request.task.capability is Capability.GRAPH_TRAVERSAL
    assert document_request.task.capability is Capability.KEYWORD_SEARCH
