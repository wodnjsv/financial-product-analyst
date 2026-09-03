from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.enums import ProductFamily
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.catalog import load_catalog, load_hybrid_catalog
from financial_agent.intent.clova import ModelInvocationResult
from financial_agent.intent.draft import ProductFamilyChoice
from financial_agent.intent.evidence import EvidenceCandidate, EvidenceSourceKind
from financial_agent.intent.errors import ResolverContractError
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
    ProvenanceSourceKind,
)
from financial_agent.intent.semantic_defaults import (
    DatasetSemanticDefaultsV1,
    SemanticAsOfDefaultV1,
    load_semantic_default_policy_registry,
)
import financial_agent.intent.service as service_module
from financial_agent.intent.resolution import ResolutionIssue
from financial_agent.intent.service import (
    IntentResolverService,
    PreparedHybridResolutionRequest,
    PreparedResolutionRequest,
    QueryContractResolutionAttemptV3,
    QueryContractResolutionTelemetry,
    reconcile_exact_axis_locks,
)
from financial_agent.intent.types import ChoiceState, ResolutionStatus
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ActiveDatasetPin,
    ResolverViewReferenceCandidate,
    build_manifest,
    build_hybrid_manifest,
)
from financial_agent.intent.resolution import ValidatedIntentResolutionV3
from tests.intent.view_fixtures import hybrid_manifest_versions
from tests.planning.fixtures import resolution


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 2, tzinfo=UTC)
USAGE = {"promptTokens": 11, "completionTokens": 7, "totalTokens": 18}


class _Adapter:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[object] = []

    async def invoke(
        self, envelope: object, timeout_seconds: float
    ) -> ModelInvocationResult:
        self.calls.append(envelope)
        return ModelInvocationResult(
            content=self.responses.pop(0), usage=MappingProxyType(USAGE)
        )


class _EmptyEntities:
    async def search_batch(self, dataset_version: str, mentions: object):
        return MappingProxyType({})


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _TimedAdapter(_Adapter):
    def __init__(self, responses: list[str], clock: _Clock) -> None:
        super().__init__(responses)
        self._clock = clock

    async def invoke(
        self, envelope: object, timeout_seconds: float
    ) -> ModelInvocationResult:
        self._clock.advance(0.025)
        return await super().invoke(envelope, timeout_seconds)


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


def _generic_lookup_proposal(prepared: PreparedResolutionRequest) -> str:
    payload = json.loads(_proposal())
    evidence_by_text = {
        item.text: item.evidence_id for item in prepared.view.evidence_candidates
    }
    frame = payload["frames"][0]
    frame["action_choice"]["evidence_ids"] = [evidence_by_text["알려줘"]]
    frame["product_family_choice"]["evidence_ids"] = [evidence_by_text["상품"]]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _service(
    adapter: _Adapter,
    *,
    timer=None,
    semantic_defaults: DatasetSemanticDefaultsV1 | None = None,
) -> IntentResolverService:
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
    semantic_default_inputs = (
        {
            "semantic_default_registry": load_semantic_default_policy_registry(
                PROJECT_ROOT
            ),
            "dataset_semantic_defaults": semantic_defaults,
        }
        if semantic_defaults is not None
        else {}
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
        timer=timer,
        **semantic_default_inputs,
    )


def _hybrid_service(
    adapter: _Adapter,
    *,
    timer=None,
    semantic_defaults: DatasetSemanticDefaultsV1 | None = None,
) -> IntentResolverService:
    catalog = load_hybrid_catalog(PROJECT_ROOT)
    semantic_default_inputs = (
        {
            "semantic_default_registry": load_semantic_default_policy_registry(
                PROJECT_ROOT
            ),
            "dataset_semantic_defaults": semantic_defaults,
        }
        if semantic_defaults is not None
        else {}
    )
    return IntentResolverService(
        adapter=adapter,
        entity_repository=_EmptyEntities(),
        catalog=catalog,
        manifest=build_hybrid_manifest(catalog, hybrid_manifest_versions()),
        active_dataset_pin=ActiveDatasetPin(
            dataset_version="dataset-v1", manifest_hash="a" * 64
        ),
        query_contract_registry=load_query_contract_registry(PROJECT_ROOT),
        utcnow=lambda: NOW,
        timer=timer,
        **semantic_default_inputs,
    )


def _hybrid_proposal(
    prepared: PreparedHybridResolutionRequest,
    *,
    semantic_ids: tuple[str, ...] = ("fee_rate",),
    state: str = "selected",
) -> str:
    mention_id = next(
        item.mention_id
        for item in prepared.view.mention_spans.items
        if item.text == "비용 부담"
    )
    return json.dumps(
        {
            "proposal_schema_version": "3.0",
            "frames": [
                {
                    "segment_ids": ["s1"],
                    "action_choice": {
                        "state": "selected",
                        "selected_ids": ["rank"],
                        "evidence_ids": [],
                        "reason_code": "explicit",
                    },
                    "product_family_choice": {
                        "state": "selected",
                        "selected_ids": ["domestic_etf"],
                        "evidence_ids": [],
                        "reason_code": "explicit",
                    },
                    "entity_type_ids": ["FinancialProduct"],
                    "semantic_links": [
                        {
                            "mention_id": mention_id,
                            "state": state,
                            "semantic_ids": list(semantic_ids),
                            "reason_code": (
                                "ambiguous" if state == "ambiguous" else "implicit"
                            ),
                        }
                    ],
                    "unmapped_mention_ids": [],
                    "semantic_coverage": {"state": "covered", "reason": "none"},
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


def _semantic_defaults(
    family: str = "domestic_etf",
) -> DatasetSemanticDefaultsV1:
    return DatasetSemanticDefaultsV1(
        dataset_version="dataset-v1",
        manifest_hash="a" * 64,
        defaults=(
            SemanticAsOfDefaultV1(
                default_record_id=f"dataset-v1-{family}-aum",
                product_family_id=family,
                semantic_id="aum",
                as_of_date=date(2026, 8, 21),
            ),
        ),
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
    context = _context("상품 알려줘")
    adapter = _Adapter([])
    service = _service(adapter)
    adapter.responses.append(_generic_lookup_proposal(await service.prepare(context)))
    attempt = await service.resolve_query_contract_candidates(context)

    assert attempt.telemetry.model_call_count == 1
    assert attempt.telemetry.repair_used is False
    assert attempt.telemetry.candidate_judge_used is False
    assert attempt.telemetry.complete_candidate_count == 1
    assert len(attempt.candidates.frames[0].complete_candidates) == 1
    assert adapter.calls and len(adapter.calls) == 1
    with pytest.raises(FrozenInstanceError):
        attempt.resolution = attempt.resolution  # type: ignore[misc]


@pytest.mark.asyncio
async def test_hybrid_query_contract_path_uses_v3_end_to_end_with_one_call() -> None:
    context = _context("비용 부담이 작은 ETF 다섯 개")
    adapter = _Adapter([])
    service = _hybrid_service(adapter)
    prepared = await service.prepare_hybrid(context)
    adapter.responses.append(_hybrid_proposal(prepared))

    attempt = await service.resolve_hybrid_query_contract_candidates(context)

    assert isinstance(attempt, QueryContractResolutionAttemptV3)
    assert isinstance(attempt.resolution, ValidatedIntentResolutionV3)
    assert attempt.telemetry.model_call_count == 1
    assert attempt.telemetry.repair_used is False
    assert attempt.telemetry.candidate_judge_used is False
    assert attempt.telemetry.complete_candidate_count == 1
    assert (
        attempt.candidates.complete_candidates[0].contract.ordering[0].field_concept_id
        == "fee_rate"
    )
    assert len(adapter.calls) == 1
    envelope = adapter.calls[0]
    assert envelope.response_schema["properties"]["proposal_schema_version"]["enum"] == [
        "3.0"
    ]
    assert "compact_semantic_catalog" in json.loads(envelope.user_message)["view"]
    with pytest.raises(FrozenInstanceError):
        attempt.resolution = attempt.resolution  # type: ignore[misc]


@pytest.mark.asyncio
async def test_hybrid_service_injects_pinned_aum_date_into_v3_solver() -> None:
    context = _context("비용 부담이 작은 ETF 다섯 개")
    adapter = _Adapter([])
    service = _hybrid_service(adapter, semantic_defaults=_semantic_defaults())
    prepared = await service.prepare_hybrid(context)
    adapter.responses.append(_hybrid_proposal(prepared, semantic_ids=("aum",)))

    attempt = await service.resolve_hybrid_query_contract_candidates(context)

    contract = attempt.candidates.complete_candidates[0].contract
    assert contract.qualifiers.as_of_date == date(2026, 8, 21)
    assert {
        item.source_ref
        for item in contract.provenance
        if item.source_kind is ProvenanceSourceKind.REGISTRY_DEFAULT
        and item.semantic_input_id.startswith("qualifiers.as_of_date")
    } == {"active-dataset-as-of.v1", "dataset-v1-domestic_etf-aum"}


@pytest.mark.asyncio
async def test_injected_semantic_defaults_do_not_change_v2_solver_behavior() -> None:
    context = _context()
    adapter = _Adapter([_proposal()])
    service = _service(adapter, semantic_defaults=_semantic_defaults())

    attempt = await service.resolve_query_contract_candidates(context)

    assert attempt.candidates.complete_candidates == ()
    assert attempt.candidates.frames[0].contract_readiness.reason_codes == (
        "REQUIRED_QUALIFIER_MISSING",
    )


@pytest.mark.asyncio
async def test_hybrid_ambiguous_semantic_link_never_calls_candidate_judge() -> None:
    context = _context("비용 부담이 작은 ETF 다섯 개")
    adapter = _Adapter([])
    service = _hybrid_service(adapter)
    prepared = await service.prepare_hybrid(context)
    adapter.responses.append(
        _hybrid_proposal(
            prepared,
            semantic_ids=("fee_rate", "product_risk_grade"),
            state="ambiguous",
        )
    )

    attempt = await service.resolve_hybrid_query_contract_candidates(context)

    assert attempt.telemetry.model_call_count == 1
    assert attempt.telemetry.repair_used is False
    assert attempt.telemetry.candidate_judge_used is False
    assert attempt.candidates.complete_candidates == ()
    assert (
        attempt.candidates.frames[0].contract_readiness.readiness
        is ContractReadiness.AMBIGUOUS
    )
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
async def test_hybrid_schema_repair_is_separate_and_precludes_judge() -> None:
    context = _context("비용 부담이 작은 ETF 다섯 개")
    clock = _Clock()
    adapter = _TimedAdapter([], clock)
    service = _hybrid_service(adapter, timer=clock)
    prepared = await service.prepare_hybrid(context)
    adapter.responses.extend(["{}", _hybrid_proposal(prepared)])

    attempt = await service.resolve_hybrid_query_contract_candidates(context)

    assert attempt.telemetry.model_call_count == 2
    assert attempt.telemetry.repair_used is True
    assert attempt.telemetry.candidate_judge_used is False
    assert attempt.telemetry.axis_model_ms == 25
    assert attempt.telemetry.repair_ms == 25
    assert len(adapter.calls) == 2


@pytest.mark.asyncio
async def test_hybrid_unknown_semantic_id_uses_the_shared_repair_allowance() -> None:
    context = _context("비용 부담이 작은 ETF 다섯 개")
    adapter = _Adapter([])
    service = _hybrid_service(adapter)
    prepared = await service.prepare_hybrid(context)
    adapter.responses.extend(
        [
            _hybrid_proposal(prepared, semantic_ids=("unknown_semantic",)),
            _hybrid_proposal(prepared),
        ]
    )

    attempt = await service.resolve_hybrid_query_contract_candidates(context)

    assert attempt.telemetry.model_call_count == 2
    assert attempt.telemetry.repair_used is True
    assert attempt.telemetry.candidate_judge_used is False
    assert len(adapter.calls) == 2


@pytest.mark.asyncio
async def test_hybrid_equal_candidates_use_one_offered_id_judge_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context("비용 부담이 작은 ETF 다섯 개")
    adapter = _Adapter([])
    service = _hybrid_service(adapter)
    prepared = await service.prepare_hybrid(context)
    proposal = _hybrid_proposal(prepared)
    resolution_v3 = service.validate_hybrid_response(prepared, proposal)
    solved = solve_query_contracts(
        resolution=resolution_v3,
        view=prepared.view,
        exact_locks=prepared.view.exact_semantic_locks,
        registry=load_query_contract_registry(PROJECT_ROOT),
        semantic_catalog=load_hybrid_catalog(PROJECT_ROOT),
    )
    first = solved.frames[0].complete_candidates[0]
    alternate = QueryContractCandidate(
        candidate_id="query-contract-v3-alternate",
        contract=first.contract,
    )
    ambiguous = QueryContractCandidateSet(
        frames=(
            solved.frames[0].model_copy(
                update={
                    "complete_candidates": (first, alternate),
                    "contract_readiness": ContractReadinessRecordV2(
                        readiness=ContractReadiness.AMBIGUOUS,
                        reason_codes=(),
                    ),
                }
            ),
        )
    )
    monkeypatch.setattr(
        service_module, "solve_query_contracts", lambda **_kwargs: ambiguous
    )
    adapter.responses.extend(
        [proposal, json.dumps({"candidate_id": alternate.candidate_id})]
    )

    attempt = await service.resolve_hybrid_query_contract_candidates(context)

    assert attempt.telemetry.model_call_count == 2
    assert attempt.telemetry.repair_used is False
    assert attempt.telemetry.candidate_judge_used is True
    assert attempt.telemetry.offered_candidate_count == 2
    assert attempt.telemetry.complete_candidate_count == 1
    assert tuple(
        item.candidate_id for item in attempt.candidates.complete_candidates
    ) == (alternate.candidate_id,)
    assert len(adapter.calls) == 2


@pytest.mark.asyncio
async def test_exact_public_fund_family_replaces_an_hcx_family_omission() -> None:
    service = _service(_Adapter([_proposal()]))
    prepared = await service.prepare(_context("공모펀드 순자산 알려줘"))

    source = resolution()
    public_evidence = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if item.text == "공모펀드"
    )
    source_frame = source.canonical_frames[0].model_copy(
        update={
            "frame_status": ResolutionStatus.AMBIGUOUS,
            "evidence_span_ids": (public_evidence,),
            "product_family_choice": ProductFamilyChoice(
                state=ChoiceState.AMBIGUOUS,
                selected_ids=(),
                evidence_span_ids=(public_evidence,),
                reason_code="ambiguous",
            ),
        }
    )
    source = source.model_copy(
        update={
            "canonical_frames": (source_frame,),
            "resolution_status": ResolutionStatus.AMBIGUOUS,
            "issues": (
                ResolutionIssue(
                    issue_id="issue-family",
                    code="AMBIGUITY_UNRESOLVED",
                    related_ids=(source_frame.frame_id,),
                    evidence_span_ids=(public_evidence,),
                ),
            ),
        }
    )

    reconciled = reconcile_exact_axis_locks(
        source,
        prepared.view.exact_semantic_locks,
        prepared.semantic_candidates,
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
    assert reconciled.canonical_frames[0].frame_status is ResolutionStatus.RESOLVED
    assert reconciled.resolution_status is ResolutionStatus.RESOLVED


@pytest.mark.asyncio
async def test_exact_family_lock_never_overwrites_conflicting_selected_family() -> None:
    service = _service(_Adapter([_proposal()]))
    prepared = await service.prepare(_context("공모펀드 순자산 알려줘"))
    public_evidence = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if item.text == "공모펀드"
    )
    source = resolution()
    conflicting = source.canonical_frames[0].model_copy(
        update={
            "evidence_span_ids": (public_evidence,),
            "product_family_choice": ProductFamilyChoice(
                state=ChoiceState.SELECTED,
                selected_ids=(ProductFamily.DOMESTIC_ETF,),
                evidence_span_ids=(public_evidence,),
                reason_code="explicit",
            ),
        }
    )
    source = source.model_copy(update={"canonical_frames": (conflicting,)})

    with pytest.raises(ResolverContractError, match="EXACT_LOCK_CONFLICT"):
        reconcile_exact_axis_locks(
            source,
            prepared.view.exact_semantic_locks,
            prepared.semantic_candidates,
            prepared.view,
        )


@pytest.mark.asyncio
async def test_exact_family_lock_resolves_true_unmapped_family_omission() -> None:
    service = _service(_Adapter([_proposal()]))
    prepared = await service.prepare(_context("공모펀드 순자산 알려줘"))
    public_evidence = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if item.text == "공모펀드"
    )
    source = resolution()
    source_frame = source.canonical_frames[0].model_copy(
        update={
            "frame_status": ResolutionStatus.UNMAPPED,
            "evidence_span_ids": (public_evidence,),
            "product_family_choice": ProductFamilyChoice(
                state=ChoiceState.UNMAPPED,
                selected_ids=(),
                evidence_span_ids=(public_evidence,),
                reason_code="lexical_ood",
            ),
        }
    )
    source = source.model_copy(
        update={
            "canonical_frames": (source_frame,),
            "resolution_status": ResolutionStatus.UNMAPPED,
            "issues": (
                ResolutionIssue(
                    issue_id="issue-family",
                    code="SEMANTIC_CONCEPT_UNMAPPED",
                    related_ids=(source_frame.frame_id,),
                    evidence_span_ids=(public_evidence,),
                ),
            ),
        }
    )

    reconciled = reconcile_exact_axis_locks(
        source,
        prepared.view.exact_semantic_locks,
        prepared.semantic_candidates,
        prepared.view,
    )

    assert reconciled.issues == ()
    assert reconciled.canonical_frames[0].frame_status is ResolutionStatus.RESOLVED
    assert reconciled.resolution_status is ResolutionStatus.RESOLVED


@pytest.mark.asyncio
async def test_same_segment_family_lock_changes_only_its_evidence_owned_frame() -> None:
    service = _service(_Adapter([_proposal()]))
    prepared = await service.prepare(_context("공모펀드와 국내 ETF를 각각 알려줘"))
    public_evidence = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if item.text == "공모펀드"
    )
    etf_evidence = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if item.text == "ETF"
    )
    source = resolution()
    first = source.canonical_frames[0].model_copy(
        update={
            "frame_id": "frame-public",
            "ordinal": 0,
            "segment_ids": ("s1",),
            "evidence_span_ids": (public_evidence,),
            "product_family_choice": ProductFamilyChoice(
                state=ChoiceState.AMBIGUOUS,
                selected_ids=(),
                evidence_span_ids=(public_evidence,),
                reason_code="ambiguous",
            ),
        }
    )
    second = source.canonical_frames[0].model_copy(
        update={
            "frame_id": "frame-etf",
            "ordinal": 1,
            "segment_ids": ("s1",),
            "evidence_span_ids": (etf_evidence,),
            "product_family_choice": ProductFamilyChoice(
                state=ChoiceState.SELECTED,
                selected_ids=(ProductFamily.DOMESTIC_ETF,),
                evidence_span_ids=(etf_evidence,),
                reason_code="explicit",
            ),
        }
    )
    source = source.model_copy(update={"canonical_frames": (first, second)})

    reconciled = reconcile_exact_axis_locks(
        source,
        prepared.view.exact_semantic_locks,
        prepared.semantic_candidates,
        prepared.view,
    )

    assert [
        tuple(item.value for item in frame.product_family_choice.selected_ids)
        for frame in reconciled.canonical_frames
    ] == [("public_fund",), ("domestic_etf",)]


@pytest.mark.asyncio
async def test_unattributed_same_segment_family_lock_fails_closed() -> None:
    service = _service(_Adapter([_proposal()]))
    prepared = await service.prepare(_context("공모펀드와 국내 ETF를 각각 알려줘"))
    source = resolution()
    first = source.canonical_frames[0].model_copy(
        update={"frame_id": "frame-one", "ordinal": 0, "segment_ids": ("s1",)}
    )
    second = source.canonical_frames[0].model_copy(
        update={"frame_id": "frame-two", "ordinal": 1, "segment_ids": ("s1",)}
    )
    source = source.model_copy(update={"canonical_frames": (first, second)})

    with pytest.raises(
        ResolverContractError, match="EXACT_FAMILY_LOCK_UNATTRIBUTED"
    ):
        reconcile_exact_axis_locks(
            source,
            prepared.view.exact_semantic_locks,
            prepared.semantic_candidates,
            prepared.view,
        )


@pytest.mark.asyncio
async def test_family_reconciliation_preserves_unrelated_frame_ambiguity() -> None:
    service = _service(_Adapter([_proposal()]))
    prepared = await service.prepare(_context("공모펀드 순자산 알려줘"))
    public_evidence = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if item.text == "공모펀드"
    )
    source = resolution()
    frame = source.canonical_frames[0].model_copy(
        update={
            "frame_status": ResolutionStatus.AMBIGUOUS,
            "evidence_span_ids": (public_evidence,),
            "product_family_choice": ProductFamilyChoice(
                state=ChoiceState.AMBIGUOUS,
                selected_ids=(),
                evidence_span_ids=(public_evidence,),
                reason_code="ambiguous",
            ),
        }
    )
    source = source.model_copy(
        update={
            "canonical_frames": (frame,),
            "resolution_status": ResolutionStatus.AMBIGUOUS,
            "issues": (
                ResolutionIssue(
                    issue_id="issue-family",
                    code="AMBIGUITY_UNRESOLVED",
                    related_ids=(frame.frame_id,),
                    evidence_span_ids=(public_evidence,),
                ),
                ResolutionIssue(
                    issue_id="issue-reference",
                    code="REFERENCE_AMBIGUOUS",
                    related_ids=(frame.frame_id,),
                    evidence_span_ids=(),
                ),
            ),
        }
    )

    reconciled = reconcile_exact_axis_locks(
        source,
        prepared.view.exact_semantic_locks,
        prepared.semantic_candidates,
        prepared.view,
    )

    assert reconciled.canonical_frames[0].frame_status is ResolutionStatus.AMBIGUOUS
    assert reconciled.resolution_status is ResolutionStatus.AMBIGUOUS
    assert {item.code for item in reconciled.issues} == {"REFERENCE_AMBIGUOUS"}


@pytest.mark.asyncio
async def test_reference_id_issue_only_marks_its_evidence_owned_frame() -> None:
    service = _service(_Adapter([_proposal()]))
    prepared = await service.prepare(_context("공모펀드 순자산 알려줘"))
    public_evidence = next(
        item.evidence_id
        for item in prepared.view.evidence_candidates
        if item.text == "공모펀드"
    )
    reference_evidence = EvidenceCandidate(
        evidence_id="evidence-reference-s2",
        segment_id="s2",
        start_char=0,
        end_char=4,
        text="그 상품",
        source_kinds=(EvidenceSourceKind.REFERENCE,),
        offered_semantic_ids=(),
    )
    resolver_view = prepared.view.model_copy(
        update={
            "reference_candidates": (
                ResolverViewReferenceCandidate(
                    reference_id="reference-real-2",
                    segment_id="s2",
                    text="그 상품",
                    start_char=0,
                    end_char=4,
                ),
            ),
            "evidence_candidates": (
                *prepared.view.evidence_candidates,
                reference_evidence,
            ),
        }
    )
    source = resolution()
    template = source.canonical_frames[0]
    first = template.model_copy(
        update={
            "frame_id": "frame-family",
            "ordinal": 0,
            "segment_ids": ("s1",),
            "evidence_span_ids": (public_evidence,),
            "frame_status": ResolutionStatus.AMBIGUOUS,
            "product_family_choice": ProductFamilyChoice(
                state=ChoiceState.AMBIGUOUS,
                selected_ids=(),
                evidence_span_ids=(public_evidence,),
                reason_code="ambiguous",
            ),
        }
    )
    second = template.model_copy(
        update={
            "frame_id": "frame-reference",
            "ordinal": 1,
            "segment_ids": ("s2",),
            "evidence_span_ids": (reference_evidence.evidence_id,),
            "frame_status": ResolutionStatus.AMBIGUOUS,
        }
    )
    third = template.model_copy(
        update={
            "frame_id": "frame-unrelated",
            "ordinal": 2,
            "segment_ids": ("s3",),
            "evidence_span_ids": (),
            "frame_status": ResolutionStatus.RESOLVED,
        }
    )
    source = source.model_copy(
        update={
            "canonical_frames": (first, second, third),
            "resolution_status": ResolutionStatus.AMBIGUOUS,
            "issues": (
                ResolutionIssue(
                    issue_id="issue-family",
                    code="AMBIGUITY_UNRESOLVED",
                    related_ids=(first.frame_id,),
                    evidence_span_ids=(public_evidence,),
                ),
                ResolutionIssue(
                    issue_id="issue-reference",
                    code="REFERENCE_AMBIGUOUS",
                    related_ids=("reference-real-2",),
                    evidence_span_ids=(),
                ),
            ),
        }
    )

    reconciled = reconcile_exact_axis_locks(
        source,
        resolver_view.exact_semantic_locks,
        prepared.semantic_candidates,
        resolver_view,
    )

    assert tuple(frame.frame_status for frame in reconciled.canonical_frames) == (
        ResolutionStatus.RESOLVED,
        ResolutionStatus.AMBIGUOUS,
        ResolutionStatus.RESOLVED,
    )


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
async def test_repair_provider_wait_is_not_double_counted_as_validation_time() -> None:
    clock = _Clock()
    adapter = _TimedAdapter(["{}", _proposal()], clock)
    attempt = await _service(adapter, timer=clock).resolve_query_contract_candidates(
        _context()
    )

    stage_sum = sum(
        (
            attempt.telemetry.normalization_ms,
            attempt.telemetry.candidate_ms,
            attempt.telemetry.axis_model_ms,
            attempt.telemetry.validation_ms,
            attempt.telemetry.exact_lock_reconciliation_ms,
            attempt.telemetry.candidate_solve_ms,
            attempt.telemetry.tie_break_ms,
            attempt.telemetry.candidate_judge_ms,
        )
    )
    assert attempt.telemetry.axis_model_ms == 50
    assert attempt.telemetry.validation_ms == 0
    assert stage_sum == round(clock.value * 1_000)


@pytest.mark.asyncio
async def test_equal_quality_candidates_use_one_offered_id_judge_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context("상품 알려줘")
    registry = load_query_contract_registry(PROJECT_ROOT)
    adapter = _Adapter([])
    service = _service(adapter)
    prepared = await service.prepare(context)
    proposal = _generic_lookup_proposal(prepared)
    axis_resolution = service.validate_axis_response(prepared, proposal)
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
        [proposal, json.dumps({"candidate_id": alternate.candidate_id})]
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
    context = _context("상품 알려줘")
    registry = load_query_contract_registry(PROJECT_ROOT)
    adapter = _Adapter([])
    service = _service(adapter)
    prepared = await service.prepare(context)
    proposal = _generic_lookup_proposal(prepared)
    axis_resolution = service.validate_axis_response(prepared, proposal)
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
    adapter.responses.append(proposal)

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
