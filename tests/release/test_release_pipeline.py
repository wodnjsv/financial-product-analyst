from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from financial_agent.contracts import (
    AnswerDisposition,
    BlockType,
    CalculationRecord,
    CalculationType,
    CutoffStatus,
    EvidenceKind,
    EvidenceRecord,
    SourceLocator,
    SourceRecord,
)
from financial_agent.contracts.answer import AnswerBlock, AnswerPlan, ClaimSlot
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.enums import ResultType, ToolStatus, VerificationStatus
from financial_agent.contracts.execution import ResultField, ResultRow, ToolResult
from financial_agent.contracts.values import encode_contract_value
from financial_agent.release import (
    ClaimGate,
    DeterministicRenderer,
    EvidenceBundleAssembler,
    EvidenceVerifier,
    build_default_answer_plan,
    to_evaluation_response,
)


CONTEXT = {
    "request_key": "e" * 64,
    "run_id": "run-1",
    "dataset_version": "dataset-v1",
    "cutoff_date": date(2026, 8, 24),
    "created_at": datetime(2026, 8, 24, tzinfo=UTC),
}


def _source(*, eligible: bool = True) -> SourceRecord:
    return SourceRecord(
        source_id="source-1",
        publisher="publisher-1",
        publisher_type="regulator",
        source_title="공식 투자설명서",
        source_type="investment_prospectus",
        authority_tier="tier-1",
        source_locator_root="dart:receipt-1",
        content_checksum="a" * 64,
        eligible_for_claim=eligible,
    )


def _evidence(
    *,
    evidence_id: str = "evidence-1",
    kind: EvidenceKind = EvidenceKind.OBSERVATION,
    predicate: str = "aum",
    value="1000000",
) -> EvidenceRecord:
    tagged = encode_contract_value(value)
    assert tagged.type != "tuple"
    draft = EvidenceRecord(
        evidence_id=evidence_id,
        evidence_kind=kind,
        source_id="source-1",
        dataset_version="dataset-v1",
        subject_id="product-1",
        predicate_id=predicate,
        value_or_object_id=tagged,
        normalized_value=tagged,
        unit="KRW" if predicate == "aum" else None,
        currency="KRW" if predicate == "aum" else None,
        applicable_date=date(2026, 8, 22),
        published_at=datetime(2026, 8, 23, tzinfo=UTC),
        available_at=datetime(2026, 8, 23, tzinfo=UTC),
        source_locator=SourceLocator(
            locator_type="row",
            uri_or_object_key="official/source.xlsx",
            sheet="ETF",
            row=2,
            column="AUM",
        ),
        parser_version="parser-v1",
        mapping_version="mapping-v1",
        cutoff_status=CutoffStatus.ELIGIBLE,
        record_hash="0" * 64,
    )
    return draft.model_copy(
        update={
            "record_hash": canonical_sha256(
                draft, exclude_fields=("record_hash",)
            )
        }
    )


def _result(evidence_id: str = "evidence-1") -> ToolResult:
    draft = ToolResult(
        **CONTEXT,
        producer="executor:rdb_lookup",
        task_id="task-1",
        status=ToolStatus.SUCCESS,
        result_type=ResultType.ROW_SET,
        result_rows=(
            ResultRow(
                row_id="row-1",
                entity_ids=("product-1",),
                fields=(
                    ResultField(
                        field_id="aum",
                        value=encode_contract_value("1000000"),
                        unit_id="KRW",
                        currency="KRW",
                        applicable_date=date(2026, 8, 22),
                    ),
                ),
            ),
        ),
        evidence_refs=(evidence_id,),
        result_hash="0" * 64,
        latency_ms=1,
    )
    return draft.model_copy(
        update={
            "result_hash": canonical_sha256(
                draft, exclude_fields=("result_hash",)
            )
        }
    )


def test_direct_fact_reaches_deterministic_verified_release() -> None:
    evidence = _evidence()
    assembly = EvidenceBundleAssembler().assemble(
        (_result(),),
        evidence_records=(evidence,),
    )

    assert len(assembly.claims) == 1
    assert assembly.claims[0].predicate_id == "aum"
    assert assembly.supports[0].evidence_id == evidence.evidence_id

    report = EvidenceVerifier().verify(
        assembly,
        sources=(_source(),),
    )
    assert report.verification_status is VerificationStatus.PASS
    assert report.recommended_answer_disposition is AnswerDisposition.ANSWER
    assert report.releaseable_claim_ids == (assembly.claims[0].claim_id,)

    plan = build_default_answer_plan(report)
    decision = ClaimGate().authorize(plan, report, assembly)
    released = DeterministicRenderer(
        entity_labels={"product-1": "KODEX 200"},
        predicate_labels={"aum": "순자산총액"},
    ).render(decision, assembly, sources=(_source(),))

    assert released.answer_text == "KODEX 200의 순자산총액: 1000000 KRW (2026-08-22) [1]"
    assert "공식 투자설명서" in released.retrieved_context_text
    assert "검증된 Claim 1개" in released.think_trace_text
    response = to_evaluation_response(
        released,
        question_id="q-1",
        question="KODEX 200의 AUM은?",
    )
    assert response.answer == released.answer_text
    assert response.retrieved_context == released.retrieved_context_text


def test_relation_claim_requires_exact_relation_evidence() -> None:
    evidence = _evidence(
        kind=EvidenceKind.RELATION,
        predicate="managedBy",
        value="manager-1",
    )
    result = _result().model_copy(
        update={
            "producer": "executor:graph_traversal",
            "result_rows": (
                ResultRow(
                    row_id="relation-1",
                    entity_ids=("product-1", "manager-1"),
                    fields=(
                        ResultField(
                            field_id="subject_id",
                            value=encode_contract_value("product-1"),
                        ),
                        ResultField(
                            field_id="predicate_id",
                            value=encode_contract_value("managedBy"),
                        ),
                        ResultField(
                            field_id="object_id",
                            value=encode_contract_value("manager-1"),
                        ),
                        ResultField(
                            field_id="evidence_id",
                            value=encode_contract_value("evidence-1"),
                        ),
                    ),
                ),
            ),
        }
    )
    result = result.model_copy(
        update={
            "result_hash": canonical_sha256(
                result, exclude_fields=("result_hash",)
            )
        }
    )
    assembly = EvidenceBundleAssembler().assemble(
        (result,), evidence_records=(evidence,)
    )

    assert assembly.claims[0].object_id == "manager-1"
    assert assembly.claims[0].value is None

    mismatched = evidence.model_copy(update={"predicate_id": "issuedBy"})
    with pytest.raises(ValueError, match="RESULT_EVIDENCE_MISMATCH"):
        EvidenceBundleAssembler().assemble(
            (result,), evidence_records=(mismatched,)
        )


def test_document_span_releases_exact_chunk_text_not_chunk_id() -> None:
    evidence = _evidence(
        kind=EvidenceKind.DOCUMENT_SPAN,
        predicate="risk_factor",
        value="chunk-risk-1",
    ).model_copy(
        update={
            "unit": None,
            "currency": None,
            "raw_value_repr": "시장가격과 순자산가치의 괴리 위험이 있습니다.",
        }
    )
    evidence = evidence.model_copy(
        update={
            "record_hash": canonical_sha256(
                evidence, exclude_fields=("record_hash",)
            )
        }
    )
    result = _result().model_copy(
        update={
            "producer": "executor:keyword_search",
            "result_rows": (
                ResultRow(
                    row_id="chunk-risk-1",
                    entity_ids=("product-1",),
                    fields=(
                        ResultField(
                            field_id="chunk_id",
                            value=encode_contract_value("chunk-risk-1"),
                        ),
                        ResultField(
                            field_id="chunk_text",
                            value=encode_contract_value(
                                "시장가격과 순자산가치의 괴리 위험이 있습니다."
                            ),
                        ),
                        ResultField(
                            field_id="evidence_id",
                            value=encode_contract_value("evidence-1"),
                        ),
                    ),
                ),
            ),
        }
    )
    result = result.model_copy(
        update={
            "result_hash": canonical_sha256(result, exclude_fields=("result_hash",))
        }
    )

    assembly = EvidenceBundleAssembler().assemble(
        (result,), evidence_records=(evidence,)
    )
    assert assembly.claims[0].value.value == evidence.raw_value_repr
    report = EvidenceVerifier().verify(assembly, sources=(_source(),))
    plan = build_default_answer_plan(report)
    released = DeterministicRenderer().render(
        ClaimGate().authorize(plan, report, assembly),
        assembly,
        sources=(_source(),),
    )
    assert evidence.raw_value_repr in released.answer_text
    assert "chunk-risk-1" not in released.answer_text


def test_unmatched_global_evidence_never_becomes_a_claim() -> None:
    with pytest.raises(ValueError, match="RESULT_EVIDENCE_MISMATCH"):
        EvidenceBundleAssembler().assemble(
            (_result(),),
            evidence_records=(
                _evidence(predicate="fee_rate", value="0.1"),
            ),
        )


def test_verifier_rejects_ineligible_source_and_after_cutoff_evidence() -> None:
    assembly = EvidenceBundleAssembler().assemble(
        (_result(),), evidence_records=(_evidence(),)
    )
    report = EvidenceVerifier().verify(
        assembly,
        sources=(_source(eligible=False),),
    )
    assert report.verification_status is VerificationStatus.FAIL
    assert report.releaseable_claim_ids == ()
    assert any(check.reason_code == "SOURCE_NOT_CLAIM_ELIGIBLE" for check in report.claim_checks)

    late = _evidence().model_copy(
        update={"available_at": datetime(2026, 8, 25, tzinfo=UTC)}
    )
    late = late.model_copy(
        update={
            "record_hash": canonical_sha256(
                late, exclude_fields=("record_hash",)
            )
        }
    )
    late_assembly = replace(assembly, evidence_records=(late,))
    late_report = EvidenceVerifier().verify(late_assembly, sources=(_source(),))
    assert late_report.verification_status is VerificationStatus.FAIL
    assert any(check.reason_code == "EVIDENCE_AFTER_CUTOFF" for check in late_report.claim_checks)

    seoul_late = _evidence().model_copy(
        update={"available_at": datetime(2026, 8, 24, 15, tzinfo=UTC)}
    )
    seoul_late = seoul_late.model_copy(
        update={
            "record_hash": canonical_sha256(
                seoul_late, exclude_fields=("record_hash",)
            )
        }
    )
    seoul_late_assembly = replace(assembly, evidence_records=(seoul_late,))
    seoul_late_report = EvidenceVerifier().verify(
        seoul_late_assembly, sources=(_source(),)
    )
    assert seoul_late_report.verification_status is VerificationStatus.FAIL

    late_vintage = _evidence().model_copy(
        update={"vintage_date": date(2026, 8, 25)}
    )
    late_vintage = late_vintage.model_copy(
        update={
            "record_hash": canonical_sha256(
                late_vintage, exclude_fields=("record_hash",)
            )
        }
    )
    late_vintage_report = EvidenceVerifier().verify(
        replace(assembly, evidence_records=(late_vintage,)),
        sources=(_source(),),
    )
    assert late_vintage_report.verification_status is VerificationStatus.FAIL


def test_verifier_and_gate_reject_tampered_bundle_or_report() -> None:
    evidence = _evidence()
    assembly = EvidenceBundleAssembler().assemble(
        (_result(),), evidence_records=(evidence,)
    )
    tampered_bundle = assembly.bundle.model_copy(update={"producer": "tampered"})
    with pytest.raises(ValueError, match="EVIDENCE_BUNDLE_HASH_MISMATCH"):
        EvidenceVerifier().verify(
            replace(assembly, bundle=tampered_bundle), sources=(_source(),)
        )

    report = EvidenceVerifier().verify(assembly, sources=(_source(),))
    plan = build_default_answer_plan(report)
    tampered_report = report.model_copy(update={"releaseable_claim_ids": ()})
    with pytest.raises(ValueError, match="CLAIM_GATE_REPORT_HASH_MISMATCH"):
        ClaimGate().authorize(plan, tampered_report, assembly)


def test_claim_gate_blocks_unknown_template_and_nonreleaseable_claim() -> None:
    evidence = _evidence()
    assembly = EvidenceBundleAssembler().assemble(
        (_result(),), evidence_records=(evidence,)
    )
    report = EvidenceVerifier().verify(assembly, sources=(_source(),))
    plan = build_default_answer_plan(report)

    unknown = plan.model_copy(
        update={
            "blocks": (
                plan.blocks[0].model_copy(update={"template_id": "invented.v1"}),
            )
        }
    )
    unknown = unknown.model_copy(
        update={"plan_hash": canonical_sha256(unknown, exclude_fields=("plan_hash",))}
    )
    with pytest.raises(ValueError, match="CLAIM_GATE_TEMPLATE_NOT_REGISTERED"):
        ClaimGate().authorize(unknown, report, assembly)

    empty = plan.model_copy(update={"blocks": (), "plan_hash": "0" * 64})
    empty = empty.model_copy(
        update={"plan_hash": canonical_sha256(empty, exclude_fields=("plan_hash",))}
    )
    with pytest.raises(ValueError, match="CLAIM_GATE_PLAN_SHAPE_INCOMPATIBLE"):
        ClaimGate().authorize(empty, report, assembly)

    foreign = AnswerPlan(
        **CONTEXT,
        producer="answer-composer",
        verification_report_id=report.verification_report_id,
        answer_disposition=AnswerDisposition.ANSWER,
        renderer_profile_id="competition-ko.v1",
        blocks=(
            AnswerBlock(
                block_id="block-1",
                block_type=BlockType.FACT_LIST,
                template_id="fact-list.v1",
                claim_slots=(
                    ClaimSlot(slot_id="claim-1", claim_id="foreign-claim"),
                ),
            ),
        ),
        plan_hash="0" * 64,
    )
    foreign = foreign.model_copy(
        update={"plan_hash": canonical_sha256(foreign, exclude_fields=("plan_hash",))}
    )
    with pytest.raises(ValueError, match="CLAIM_GATE_CLAIM_NOT_RELEASEABLE"):
        ClaimGate().authorize(foreign, report, assembly)


def test_empty_result_is_limitation_not_no_match_without_closed_world_scope() -> None:
    empty = _result().model_copy(
        update={
            "status": ToolStatus.EMPTY,
            "result_rows": (),
            "evidence_refs": (),
        }
    )
    empty = empty.model_copy(
        update={
            "result_hash": canonical_sha256(empty, exclude_fields=("result_hash",))
        }
    )
    assembly = EvidenceBundleAssembler().assemble((empty,), evidence_records=())
    report = EvidenceVerifier().verify(assembly, sources=())

    assert assembly.claims == ()
    assert assembly.bundle.unanswered_subtasks == ("task-1",)
    assert report.verification_status is VerificationStatus.PASS
    assert report.recommended_answer_disposition is AnswerDisposition.LIMITATION

    plan = build_default_answer_plan(report)
    assert plan.blocks[0].block_type is BlockType.LIMITATION
    decision = ClaimGate().authorize(plan, report, assembly)
    released = DeterministicRenderer().render(decision, assembly, sources=())
    assert "확인할 수 없습니다" in released.answer_text


def test_calculation_claim_keeps_formula_and_input_evidence() -> None:
    evidence = _evidence(value=Decimal("1000000"))
    draft = CalculationRecord(
        calculation_id="calculation-1",
        calculation_type=CalculationType.CONVERSION,
        formula_id="identity-unit.v1",
        formula_version="1.0",
        input_evidence_ids=(evidence.evidence_id,),
        result_value=encode_contract_value(Decimal("1000000")),
        unit="KRW",
        currency="KRW",
        rounding_rule="no-rounding.v1",
        calculation_hash="0" * 64,
    )
    calculation = draft.model_copy(
        update={
            "calculation_hash": canonical_sha256(
                draft, exclude_fields=("calculation_hash",)
            )
        }
    )
    result = _result().model_copy(
        update={
            "producer": "executor:financial_calculation",
            "result_type": ResultType.CALCULATION,
            "result_rows": (
                ResultRow(
                    row_id="calculation-1",
                    entity_ids=("product-1",),
                    fields=(
                        ResultField(
                            field_id="calculation_id",
                            value=encode_contract_value("calculation-1"),
                        ),
                        ResultField(
                            field_id="result_value",
                            value=calculation.result_value,
                            unit_id="KRW",
                            currency="KRW",
                        ),
                    ),
                ),
            ),
        }
    )
    result = result.model_copy(
        update={
            "result_hash": canonical_sha256(result, exclude_fields=("result_hash",))
        }
    )

    assembly = EvidenceBundleAssembler().assemble(
        (result,),
        evidence_records=(evidence,),
        calculation_records=(calculation,),
    )
    assert assembly.bundle.calculation_ids == ("calculation-1",)
    assert assembly.supports[0].calculation_id == "calculation-1"
    report = EvidenceVerifier().verify(assembly, sources=(_source(),))
    assert report.verification_status is VerificationStatus.PASS
    plan = build_default_answer_plan(report)
    release = DeterministicRenderer(
        entity_labels={"product-1": "KODEX 200"}
    ).render(ClaimGate().authorize(plan, report, assembly), assembly, sources=(_source(),))
    assert "1000000 KRW" in release.answer_text

    unapproved_draft = calculation.model_copy(
        update={"formula_id": "model-supplied-formula", "calculation_hash": "0" * 64}
    )
    unapproved = unapproved_draft.model_copy(
        update={
            "calculation_hash": canonical_sha256(
                unapproved_draft, exclude_fields=("calculation_hash",)
            )
        }
    )
    unapproved_assembly = EvidenceBundleAssembler().assemble(
        (result,),
        evidence_records=(evidence,),
        calculation_records=(unapproved,),
    )
    unapproved_report = EvidenceVerifier().verify(
        unapproved_assembly, sources=(_source(),)
    )
    assert unapproved_report.verification_status is VerificationStatus.FAIL
    assert any(
        check.reason_code == "CALCULATION_RECIPE_NOT_APPROVED"
        for check in unapproved_report.claim_checks
    )

    similarity_draft = calculation.model_copy(
        update={
            "calculation_type": CalculationType.SIMILARITY,
            "calculation_hash": "0" * 64,
        }
    )
    similarity = similarity_draft.model_copy(
        update={
            "calculation_hash": canonical_sha256(
                similarity_draft, exclude_fields=("calculation_hash",)
            )
        }
    )
    similarity_assembly = EvidenceBundleAssembler().assemble(
        (result,),
        evidence_records=(evidence,),
        calculation_records=(similarity,),
    )
    similarity_report = EvidenceVerifier().verify(
        similarity_assembly, sources=(_source(),)
    )
    assert similarity_report.verification_status is VerificationStatus.FAIL
    assert any(
        check.reason_code == "SIMILARITY_POLICY_NOT_ACTIVE"
        for check in similarity_report.claim_checks
    )
