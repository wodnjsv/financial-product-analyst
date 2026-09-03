"""Render released text exclusively from Claim and Evidence ledger values."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Mapping

from financial_agent.contracts import (
    ClaimBinding,
    EvaluationApiResponse,
    ReleasedAnswer,
    SourceRecord,
)
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.values import decode_contract_value

from .claims import ClaimAssembly
from .gate import ClaimGateDecision


class DeterministicRenderer:
    def __init__(
        self,
        *,
        entity_labels: Mapping[str, str] | None = None,
        predicate_labels: Mapping[str, str] | None = None,
    ) -> None:
        self._entity_labels = dict(entity_labels or {})
        self._predicate_labels = dict(predicate_labels or {})

    def render(
        self,
        decision: ClaimGateDecision,
        assembly: ClaimAssembly,
        *,
        sources: tuple[SourceRecord, ...],
    ) -> ReleasedAnswer:
        plan = decision.plan
        claims = {item.claim_id: item for item in assembly.claims}
        supports = {item.claim_id: item for item in assembly.supports}
        evidence = {item.evidence_id: item for item in assembly.evidence_records}
        calculations = {
            item.calculation_id: item for item in assembly.calculation_records
        }
        source_by_id = {item.source_id: item for item in sources}
        if len(source_by_id) != len(sources):
            raise ValueError("DUPLICATE_SOURCE_RECORD")

        ordered_claim_ids = tuple(
            slot.claim_id
            for block in plan.blocks
            for slot in block.claim_slots
        )
        expected_decision_hash = canonical_sha256(
            {
                "plan_hash": plan.plan_hash,
                "verification_report_id": decision.report.verification_report_id,
                "authorized_claim_ids": list(decision.authorized_claim_ids),
                "registry": "claim-gate-registry.v1",
            }
        )
        if (
            decision.decision_hash != expected_decision_hash
            or decision.authorized_claim_ids != ordered_claim_ids
        ):
            raise ValueError("RENDERER_GATE_DECISION_INVALID")
        source_numbers: dict[str, int] = {}
        evidence_ids_by_claim: dict[str, tuple[str, ...]] = {}
        answer_lines: list[str] = []
        bindings: list[ClaimBinding] = []

        for index, claim_id in enumerate(ordered_claim_ids, start=1):
            claim = claims[claim_id]
            support = supports.get(claim_id)
            if support is None:
                raise ValueError("RENDERER_EVIDENCE_REQUIRED")
            evidence_ids = (
                (support.evidence_id,)
                if support.evidence_id is not None
                else (
                    calculations[support.calculation_id].input_evidence_ids
                    if support.calculation_id in calculations
                    else ()
                )
            )
            records = tuple(
                evidence[evidence_id]
                for evidence_id in evidence_ids
                if evidence_id in evidence
            )
            if not records or len(records) != len(evidence_ids):
                raise ValueError("RENDERER_EVIDENCE_REQUIRED")
            if any(record.source_id not in source_by_id for record in records):
                raise ValueError("RENDERER_SOURCE_REQUIRED")
            for record in records:
                source_numbers.setdefault(record.source_id, len(source_numbers) + 1)
            claim_source_numbers = tuple(
                dict.fromkeys(source_numbers[record.source_id] for record in records)
            )
            evidence_ids_by_claim[claim_id] = tuple(
                record.evidence_id for record in records
            )
            answer_lines.append(
                self._claim_line(claim, records[0], claim_source_numbers)
            )
            bindings.append(
                ClaimBinding(
                    output_locator=f"answer.line.{index}",
                    claim_ids=(claim_id,),
                    evidence_ids=tuple(record.evidence_id for record in records),
                )
            )

        if not answer_lines:
            if plan.answer_disposition.value == "abstain":
                answer_lines.append("검증 가능한 근거가 없어 답변을 제공할 수 없습니다.")
            else:
                answer_lines.append(
                    "현재 확정된 공식 데이터 범위에서는 요청한 내용을 확인할 수 없습니다."
                )

        context_lines = []
        for source_id, number in sorted(
            source_numbers.items(), key=lambda item: item[1]
        ):
            source = source_by_id[source_id]
            source_evidence = tuple(
                item
                for item in assembly.evidence_records
                if item.source_id == source_id
                and item.evidence_id
                in {
                    evidence_id
                    for values in evidence_ids_by_claim.values()
                    for evidence_id in values
                }
            )
            locators = ", ".join(
                sorted({_locator(item.source_locator) for item in source_evidence})
            )
            context_lines.append(f"[{number}] {source.source_title} · {locators}")

        draft = ReleasedAnswer(
            request_key=plan.request_key,
            run_id=plan.run_id,
            dataset_version=plan.dataset_version,
            cutoff_date=plan.cutoff_date,
            producer="deterministic-renderer.v1",
            created_at=plan.created_at,
            answer_disposition=plan.answer_disposition,
            answer_text="\n".join(answer_lines),
            retrieved_context_text="\n".join(context_lines),
            think_trace_text=(
                f"검증된 Claim {len(ordered_claim_ids)}개와 "
                f"Evidence {len({item for values in evidence_ids_by_claim.values() for item in values})}개를 "
                "Claim Gate 통과 후 결정론적으로 렌더링했습니다."
            ),
            claim_bindings=tuple(bindings),
            response_hash="0" * 64,
        )
        return draft.model_copy(
            update={
                "response_hash": canonical_sha256(
                    draft, exclude_fields=("response_hash",)
                )
            }
        )

    def _claim_line(
        self, claim, evidence, source_numbers: tuple[int, ...]
    ) -> str:
        subject = self._entity_labels.get(claim.subject_id, claim.subject_id)
        predicate = self._predicate_labels.get(
            claim.predicate_id, claim.predicate_id
        )
        if claim.object_id is not None:
            value = self._entity_labels.get(claim.object_id, claim.object_id)
        else:
            value = _format_value(decode_contract_value(claim.value))
        suffixes = []
        unit = claim.currency or claim.unit
        if unit:
            suffixes.append(unit)
        applicable_date = evidence.applicable_date or evidence.valid_from
        if applicable_date is not None:
            suffixes.append(f"({applicable_date.isoformat()})")
        suffix = " " + " ".join(suffixes) if suffixes else ""
        citations = "".join(f"[{number}]" for number in source_numbers)
        return f"{subject}의 {predicate}: {value}{suffix} {citations}"


def to_evaluation_response(
    released: ReleasedAnswer,
    *,
    question_id: str,
    question: str,
) -> EvaluationApiResponse:
    return EvaluationApiResponse(
        question_id=question_id,
        question=question,
        retrieved_context=released.retrieved_context_text,
        think_trace=released.think_trace_text,
        answer=released.answer_text,
    )


def _format_value(value) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return "없음"
    return str(value)


def _locator(locator) -> str:
    parts = [locator.uri_or_object_key]
    if locator.sheet:
        parts.append(f"sheet={locator.sheet}")
    if locator.row is not None:
        parts.append(f"row={locator.row}")
    if locator.column:
        parts.append(f"column={locator.column}")
    if locator.page is not None:
        parts.append(f"page={locator.page}")
    if locator.section:
        parts.append(f"section={locator.section}")
    return ";".join(parts)
