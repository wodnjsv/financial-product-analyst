from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.clova import ModelInvocationResult
from financial_agent.intent.query_contract_registry import load_query_contract_registry
from financial_agent.intent.query_contract_solver import (
    QueryContractCandidate,
    QueryContractCandidateSet,
    solve_query_contracts,
)
from financial_agent.intent.query_contracts import (
    ContractReadiness,
    ContractReadinessRecordV2,
    ProjectionSpecV2,
)
import financial_agent.intent.service as service_module
from financial_agent.intent.service import (
    IntentResolverService,
    QueryContractResolutionTelemetry,
    reconcile_exact_axis_locks,
)
from tests.planning.fixtures import resolution
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ActiveDatasetPin,
    build_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 2, tzinfo=UTC)
USAGE = {"promptTokens": 11, "completionTokens": 7, "totalTokens": 18}


class _Adapter:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[object] = []

    async def invoke(self, envelope: object, timeout_seconds: float) -> ModelInvocationResult:
        self.calls.append(envelope)
        return ModelInvocationResult(
            content=self.responses.pop(0), usage=MappingProxyType(USAGE)
        )


class _EmptyEntities:
    async def search_batch(self, dataset_version: str, mentions: object):
        return MappingProxyType({})


def _context(question: str = "AUM 알려줘") -> RequestContext:
    return RequestContext(
        request_key=build_request_key("query-contract", question, "dataset-v1", "1.0"),
        run_id="run-query-contract",
        dataset_version="dataset-v1",
        producer="test",
        created_at=NOW,
        question_id="query-contract",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=NOW + timedelta(seconds=55),
    )


def _proposal(*, action: str = "lookup", family: str = "domestic_etf") -> str:
    # Evidence IDs are stable for this frozen question/catalog projection.
    return json.dumps(
        {
            "proposal_schema_version": "2.0",
            "frames": [
                {
                    "segment_ids": ["s1"],
                    "action_choice": {
                        "state": "selected",
                        "selected_ids": [action],
                        "evidence_ids": [
                            "evidence-a4208ee0fa533668a8a940c689a1679fe884c1eb625111b2f460a419083120b6"
                        ],
                        "reason_code": "explicit",
                    },
                    "product_family_choice": {
                        "state": "selected",
                        "selected_ids": [family],
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
                    "slot_assignments": [],
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


def _service(adapter: _Adapter) -> IntentResolverService:
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
    return IntentResolverService(
        adapter=adapter,
        entity_repository=_EmptyEntities(),
        catalog=catalog,
        manifest=manifest,
        active_dataset_pin=ActiveDatasetPin(
            dataset_version="dataset-v1", manifest_hash="a" * 64
        ),
        query_contract_registry=load_query_contract_registry(PROJECT_ROOT),
        utcnow=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_prepare_computes_exact_locks_once_without_exposing_lock_metadata() -> None:
    service = _service(_Adapter([_proposal()]))

    prepared = await service.prepare(_context())
    payload = json.loads(prepared.prompt.user_message)

    assert {(item.role, item.canonical_id) for item in prepared.view.exact_semantic_locks} >= {
        ("field", "aum")
    }
    assert "exact_semantic_locks" not in payload["view"]


@pytest.mark.asyncio
async def test_unique_complete_contract_uses_one_axis_call_and_no_v1_slot_binder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service_module,
        "bind_task_slots",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("V1 slot binder must not run")
        ),
    )
    adapter = _Adapter([_proposal()])
    attempt = await _service(adapter).resolve_query_contract_candidates(_context())

    assert attempt.telemetry.model_call_count == 1
    assert attempt.telemetry.repair_used is False
    assert attempt.telemetry.candidate_judge_used is False
    assert attempt.telemetry.complete_candidate_count == 1
    assert len(attempt.candidates.frames[0].complete_candidates) == 1
    assert adapter.calls and len(adapter.calls) == 1
    with pytest.raises(FrozenInstanceError):
        attempt.resolution = attempt.resolution  # type: ignore[misc]


@pytest.mark.asyncio
async def test_exact_public_fund_family_replaces_an_hcx_family_omission() -> None:
    service = _service(_Adapter([_proposal()]))
    prepared = await service.prepare(_context("공모펀드 순자산 알려줘"))

    reconciled = reconcile_exact_axis_locks(
        resolution(),
        prepared.view.exact_semantic_locks,
        prepared.semantic_candidates,
        prepared.literals,
        prepared.view,
    )

    assert tuple(
        item.value
        for item in reconciled.canonical_frames[0].product_family_choice.selected_ids
    ) == ("public_fund",)
    assert (
        reconciled.canonical_frames[0].product_family_choice.reason_code
        == "exact_lock"
    )
    assert set(
        reconciled.canonical_frames[0].product_family_choice.evidence_span_ids
    ) <= {item.evidence_id for item in prepared.view.evidence_candidates}


@pytest.mark.asyncio
async def test_schema_repair_consumes_second_call_and_never_uses_judge() -> None:
    adapter = _Adapter(["{}", _proposal()])
    attempt = await _service(adapter).resolve_query_contract_candidates(_context())

    assert attempt.telemetry.model_call_count == 2
    assert attempt.telemetry.repair_used is True
    assert attempt.telemetry.candidate_judge_used is False
    assert attempt.resolution.repair_used is True
    assert len(adapter.calls) == 2


@pytest.mark.asyncio
async def test_equal_quality_candidates_use_one_offered_id_judge_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    registry = load_query_contract_registry(PROJECT_ROOT)
    adapter = _Adapter([])
    service = _service(adapter)
    prepared = await service.prepare(context)
    axis_resolution = service.validate_axis_response(prepared, _proposal())
    solved = solve_query_contracts(
        resolution=axis_resolution,
        view=prepared.view,
        exact_locks=prepared.view.exact_semantic_locks,
        registry=registry,
    )
    first = solved.frames[0].complete_candidates[0]
    alternate = QueryContractCandidate(
        candidate_id="query-contract-alternate",
        contract=first.contract.model_copy(
            update={
                "projections": ProjectionSpecV2(
                    default_profile_id="default-product-projection.v1"
                )
            }
        ),
    )
    ambiguous_frame = solved.frames[0].model_copy(
        update={
            "complete_candidates": (first, alternate),
            "contract_readiness": ContractReadinessRecordV2(
                readiness=ContractReadiness.AMBIGUOUS,
                reason_codes=(),
            ),
        }
    )
    ambiguous = QueryContractCandidateSet(frames=(ambiguous_frame,))
    monkeypatch.setattr(
        service_module, "solve_query_contracts", lambda **_kwargs: ambiguous
    )
    adapter.responses.extend(
        [_proposal(), json.dumps({"candidate_id": alternate.candidate_id})]
    )

    attempt = await service.resolve_query_contract_candidates(context)

    assert attempt.telemetry.model_call_count == 2
    assert attempt.telemetry.repair_used is False
    assert attempt.telemetry.candidate_judge_used is True
    assert tuple(
        item.candidate_id for item in attempt.candidates.frames[0].complete_candidates
    ) == (alternate.candidate_id,)
    assert len(adapter.calls) == 2


@pytest.mark.asyncio
async def test_candidate_bound_never_uses_tie_break_or_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    registry = load_query_contract_registry(PROJECT_ROOT)
    adapter = _Adapter([])
    service = _service(adapter)
    prepared = await service.prepare(context)
    axis_resolution = service.validate_axis_response(prepared, _proposal())
    solved = solve_query_contracts(
        resolution=axis_resolution,
        view=prepared.view,
        exact_locks=prepared.view.exact_semantic_locks,
        registry=registry,
    )
    first = solved.frames[0].complete_candidates[0]
    alternate = QueryContractCandidate(
        candidate_id="query-contract-bound-alternate",
        contract=first.contract.model_copy(
            update={
                "projections": ProjectionSpecV2(
                    default_profile_id="default-product-projection.v1"
                )
            }
        ),
    )
    bounded = QueryContractCandidateSet(
        frames=(
            solved.frames[0].model_copy(
                update={
                    "complete_candidates": (first, alternate),
                    "contract_readiness": ContractReadinessRecordV2(
                        readiness=ContractReadiness.AMBIGUOUS,
                        reason_codes=("CANDIDATE_BOUND_REACHED",),
                    ),
                }
            ),
        )
    )
    monkeypatch.setattr(
        service_module, "solve_query_contracts", lambda **_kwargs: bounded
    )
    adapter.responses.append(_proposal())

    attempt = await service.resolve_query_contract_candidates(context)

    assert attempt.telemetry.model_call_count == 1
    assert attempt.telemetry.candidate_judge_used is False
    assert len(attempt.candidates.frames[0].complete_candidates) == 2
    assert attempt.candidates.frames[0].contract_readiness.reason_codes == (
        "CANDIDATE_BOUND_REACHED",
    )


def test_query_contract_telemetry_rejects_repair_and_judge_in_same_request() -> None:
    with pytest.raises(ValidationError, match="MODEL_CALL_ALLOWANCE_CONFLICT"):
        QueryContractResolutionTelemetry(
            normalization_ms=0,
            candidate_ms=0,
            axis_model_ms=0,
            validation_ms=0,
            exact_lock_reconciliation_ms=0,
            candidate_solve_ms=0,
            tie_break_ms=0,
            candidate_judge_ms=0,
            model_call_count=2,
            repair_used=True,
            candidate_judge_used=True,
            offered_candidate_count=2,
            complete_candidate_count=1,
            rejection_count=0,
            frame_count=1,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            stable_code="QUERY_CONTRACT_RESOLUTION_VALIDATED",
        )
