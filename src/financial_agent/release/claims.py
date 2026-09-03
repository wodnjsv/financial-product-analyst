"""Build exact AtomicClaims only from evidence-bound tool fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from financial_agent.contracts import (
    AtomicClaim,
    CalculationRecord,
    CalculationType,
    ClaimSupport,
    ClaimType,
    EvidenceBundle,
    EvidenceKind,
    EvidenceRecord,
    MissingData,
    SupportKind,
)
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.execution import ResultField, ResultRow, ToolResult
from financial_agent.contracts.values import decode_contract_value
from financial_agent.contracts.enums import ToolStatus


_STRUCTURAL_FIELDS = frozenset(
    {
        "product_name",
        "subject_id",
        "predicate_id",
        "object_id",
        "relation_assertion_id",
        "document_id",
        "chunk_id",
        "section_type",
        "source_id",
        "source_locator",
        "document_version",
        "published_at",
        "available_at",
        "evidence_id",
    }
)


@dataclass(frozen=True, slots=True)
class ClaimAssembly:
    bundle: EvidenceBundle
    claims: tuple[AtomicClaim, ...]
    supports: tuple[ClaimSupport, ...]
    evidence_records: tuple[EvidenceRecord, ...]
    calculation_records: tuple[CalculationRecord, ...] = ()


class EvidenceBundleAssembler:
    def assemble(
        self,
        results: tuple[ToolResult, ...],
        *,
        evidence_records: tuple[EvidenceRecord, ...],
        calculation_records: tuple[CalculationRecord, ...] = (),
        subtask_ids: Mapping[str, str] | None = None,
    ) -> ClaimAssembly:
        if not results:
            raise ValueError("TOOL_RESULTS_REQUIRED")
        _validate_result_pins(results)
        context = results[0]
        evidence_by_id = _unique_evidence(evidence_records, context.dataset_version)
        calculation_by_id = _unique_calculations(calculation_records)
        subtask_ids = subtask_ids or {}

        claims: list[AtomicClaim] = []
        supports: list[ClaimSupport] = []
        answered: list[str] = []
        unanswered: list[str] = []
        missing: list[MissingData] = []
        used_evidence: set[str] = set()
        used_calculations: set[str] = set()

        for result in results:
            subtask_id = subtask_ids.get(result.task_id, result.task_id)
            before = len(claims)
            if result.status is ToolStatus.SUCCESS:
                for row in result.result_rows:
                    produced = _claims_for_row(
                        row,
                        result,
                        subtask_id=subtask_id,
                        evidence_by_id=evidence_by_id,
                        calculation_by_id=calculation_by_id,
                    )
                    for claim, support in produced:
                        claims.append(claim)
                        supports.append(support)
                        if support.evidence_id is not None:
                            used_evidence.add(support.evidence_id)
                        elif support.calculation_id is not None:
                            calculation = calculation_by_id[support.calculation_id]
                            used_calculations.add(calculation.calculation_id)
                            used_evidence.update(calculation.input_evidence_ids)
            if len(claims) > before:
                answered.append(subtask_id)
            else:
                unanswered.append(subtask_id)
                missing.append(
                    MissingData(
                        subtask_id=subtask_id,
                        requirement_id="evidence_bound_result",
                        reason_code=(
                            "NO_RESULT_IN_BOUNDED_SCOPE"
                            if result.status is ToolStatus.EMPTY
                            else "NO_EXACT_FIELD_EVIDENCE"
                        ),
                    )
                )

        claim_tuple = tuple(sorted(claims, key=lambda item: item.claim_id))
        support_tuple = tuple(
            sorted(supports, key=lambda item: (item.claim_id, item.ordinal))
        )
        bundle_draft = EvidenceBundle(
            request_key=context.request_key,
            run_id=context.run_id,
            dataset_version=context.dataset_version,
            cutoff_date=context.cutoff_date,
            producer="evidence-bundle-assembler.v1",
            created_at=context.created_at,
            bundle_id="pending",
            answered_subtasks=tuple(sorted(set(answered))),
            unanswered_subtasks=tuple(sorted(set(unanswered))),
            evidence_ids=tuple(sorted(used_evidence)),
            calculation_ids=tuple(sorted(used_calculations)),
            candidate_claim_ids=tuple(item.claim_id for item in claim_tuple),
            missing_data=tuple(sorted(missing, key=lambda item: item.subtask_id)),
            bundle_hash="0" * 64,
        )
        bundle_hash = canonical_sha256(
            bundle_draft,
            exclude_fields=("bundle_id", "bundle_hash"),
        )
        bundle = bundle_draft.model_copy(
            update={
                "bundle_id": f"evidence-bundle-{bundle_hash[:24]}",
                "bundle_hash": bundle_hash,
            }
        )
        return ClaimAssembly(
            bundle=bundle,
            claims=claim_tuple,
            supports=support_tuple,
            evidence_records=tuple(
                evidence_by_id[evidence_id]
                for evidence_id in sorted(used_evidence)
            ),
            calculation_records=tuple(
                calculation_by_id[calculation_id]
                for calculation_id in sorted(used_calculations)
            ),
        )


def _claims_for_row(
    row: ResultRow,
    result: ToolResult,
    *,
    subtask_id: str,
    evidence_by_id: Mapping[str, EvidenceRecord],
    calculation_by_id: Mapping[str, CalculationRecord],
) -> tuple[tuple[AtomicClaim, ClaimSupport], ...]:
    fields = {item.field_id: item for item in row.fields}
    calculation_id = _string_field(fields.get("calculation_id"))
    if calculation_id is not None:
        return (
            _calculation_claim(
                row,
                fields,
                result,
                subtask_id=subtask_id,
                calculation_id=calculation_id,
                calculation_by_id=calculation_by_id,
                evidence_by_id=evidence_by_id,
            ),
        )
    explicit_evidence_id = _string_field(fields.get("evidence_id"))
    if {"subject_id", "predicate_id", "object_id"} <= set(fields):
        if explicit_evidence_id is None:
            raise ValueError("RESULT_EVIDENCE_MISMATCH")
        evidence = _require_result_evidence(
            explicit_evidence_id, result, evidence_by_id
        )
        subject_id = _required_string_field(fields["subject_id"])
        predicate_id = _required_string_field(fields["predicate_id"])
        object_id = _required_string_field(fields["object_id"])
        if (
            evidence.evidence_kind is not EvidenceKind.RELATION
            or evidence.subject_id != subject_id
            or evidence.predicate_id != predicate_id
            or decode_contract_value(evidence.normalized_value) != object_id
        ):
            raise ValueError("RESULT_EVIDENCE_MISMATCH")
        return (_claim_with_support(
            subtask_id=subtask_id,
            claim_type=ClaimType.RELATION,
            subject_id=subject_id,
            predicate_id=predicate_id,
            object_id=object_id,
            value=None,
            unit=None,
            currency=None,
            evidence=evidence,
        ),)

    if "chunk_text" in fields:
        if (
            explicit_evidence_id is None
            or not row.entity_ids
            or "chunk_id" not in fields
        ):
            raise ValueError("RESULT_EVIDENCE_MISMATCH")
        evidence = _require_result_evidence(
            explicit_evidence_id, result, evidence_by_id
        )
        text = fields["chunk_text"]
        chunk_id = _required_string_field(fields["chunk_id"])
        if (
            evidence.evidence_kind is not EvidenceKind.DOCUMENT_SPAN
            or evidence.subject_id != row.entity_ids[0]
            or decode_contract_value(evidence.normalized_value)
            != chunk_id
            or evidence.raw_value_repr != decode_contract_value(text.value)
            or evidence.predicate_id is None
        ):
            raise ValueError("RESULT_EVIDENCE_MISMATCH")
        return (_claim_with_support(
            subtask_id=subtask_id,
            claim_type=ClaimType.DIRECT_FACT,
            subject_id=row.entity_ids[0],
            predicate_id=evidence.predicate_id,
            object_id=None,
            value=text.value,
            unit=evidence.unit,
            currency=evidence.currency,
            evidence=evidence,
        ),)

    produced: list[tuple[AtomicClaim, ClaimSupport]] = []
    for field in row.fields:
        if field.field_id in _STRUCTURAL_FIELDS:
            continue
        matches = tuple(
            evidence
            for evidence_id in result.evidence_refs
            if (evidence := evidence_by_id.get(evidence_id)) is not None
            and _field_matches(row, field, evidence)
        )
        if len(matches) != 1:
            raise ValueError("RESULT_EVIDENCE_MISMATCH")
        evidence = matches[0]
        produced.append(
            _claim_with_support(
                subtask_id=subtask_id,
                claim_type=ClaimType.DIRECT_FACT,
                subject_id=row.entity_ids[0],
                predicate_id=field.field_id,
                object_id=None,
                value=evidence.normalized_value,
                unit=evidence.unit,
                currency=evidence.currency,
                evidence=evidence,
            )
        )
    return tuple(produced)


def _claim_with_support(
    *,
    subtask_id: str,
    claim_type: ClaimType,
    subject_id: str,
    predicate_id: str,
    object_id: str | None,
    value,
    unit: str | None,
    currency: str | None,
    evidence: EvidenceRecord,
) -> tuple[AtomicClaim, ClaimSupport]:
    seed = {
        "subtask_id": subtask_id,
        "claim_type": claim_type.value,
        "subject_id": subject_id,
        "predicate_id": predicate_id,
        "object_id": object_id,
        "value": None if value is None else value.model_dump(mode="json"),
        "unit": unit,
        "currency": currency,
        "evidence_id": evidence.evidence_id,
    }
    claim_id = "claim-" + canonical_sha256(seed)[:24]
    draft = AtomicClaim(
        claim_id=claim_id,
        claim_type=claim_type,
        subtask_id=subtask_id,
        subject_id=subject_id,
        predicate_id=predicate_id,
        object_id=object_id,
        value=value,
        unit=unit,
        currency=currency,
        display_policy_id=(
            "relation-object.v1"
            if claim_type is ClaimType.RELATION
            else "direct-value.v1"
        ),
        claim_hash="0" * 64,
    )
    claim = draft.model_copy(
        update={
            "claim_hash": canonical_sha256(
                draft, exclude_fields=("claim_hash",)
            )
        }
    )
    return (
        claim,
        ClaimSupport(
            claim_id=claim.claim_id,
            support_kind=SupportKind.DIRECT,
            evidence_id=evidence.evidence_id,
            support_role="primary",
            ordinal=0,
        ),
    )


def _calculation_claim(
    row: ResultRow,
    fields: Mapping[str, ResultField],
    result: ToolResult,
    *,
    subtask_id: str,
    calculation_id: str,
    calculation_by_id: Mapping[str, CalculationRecord],
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> tuple[AtomicClaim, ClaimSupport]:
    calculation = calculation_by_id.get(calculation_id)
    result_field = fields.get("result_value")
    if (
        calculation is None
        or result_field is None
        or result_field.value != calculation.result_value
        or not set(calculation.input_evidence_ids) <= set(result.evidence_refs)
        or any(
            evidence_id not in evidence_by_id
            for evidence_id in calculation.input_evidence_ids
        )
    ):
        raise ValueError("RESULT_CALCULATION_MISMATCH")
    claim_type = {
        CalculationType.RANKING: ClaimType.RANK,
        CalculationType.SIMILARITY: ClaimType.SIMILARITY,
    }.get(calculation.calculation_type, ClaimType.DERIVED_METRIC)
    subject_id = row.entity_ids[0] if row.entity_ids else subtask_id
    draft = AtomicClaim(
        claim_id="claim-"
        + canonical_sha256(
            {
                "subtask_id": subtask_id,
                "calculation_id": calculation.calculation_id,
                "subject_id": subject_id,
            }
        )[:24],
        claim_type=claim_type,
        subtask_id=subtask_id,
        subject_id=subject_id,
        predicate_id=f"calculated:{calculation.formula_id}",
        value=calculation.result_value,
        unit=calculation.unit,
        currency=calculation.currency,
        display_policy_id="calculated-value.v1",
        claim_hash="0" * 64,
    )
    claim = draft.model_copy(
        update={
            "claim_hash": canonical_sha256(
                draft, exclude_fields=("claim_hash",)
            )
        }
    )
    return claim, ClaimSupport(
        claim_id=claim.claim_id,
        support_kind=SupportKind.CALCULATION,
        calculation_id=calculation.calculation_id,
        support_role="calculation_result",
        ordinal=0,
    )


def _field_matches(
    row: ResultRow,
    field: ResultField,
    evidence: EvidenceRecord,
) -> bool:
    return bool(row.entity_ids) and (
        evidence.subject_id == row.entity_ids[0]
        and evidence.predicate_id == field.field_id
        and evidence.normalized_value == field.value
        and evidence.unit == field.unit_id
        and evidence.currency == field.currency
        and evidence.applicable_date == field.applicable_date
    )


def _require_result_evidence(
    evidence_id: str,
    result: ToolResult,
    evidence_by_id: Mapping[str, EvidenceRecord],
) -> EvidenceRecord:
    if evidence_id not in result.evidence_refs or evidence_id not in evidence_by_id:
        raise ValueError("RESULT_EVIDENCE_MISMATCH")
    return evidence_by_id[evidence_id]


def _string_field(field: ResultField | None) -> str | None:
    if field is None:
        return None
    value = decode_contract_value(field.value)
    return value if isinstance(value, str) and value else None


def _required_string_field(field: ResultField) -> str:
    value = _string_field(field)
    if value is None:
        raise ValueError("RESULT_EVIDENCE_MISMATCH")
    return value


def _unique_evidence(
    records: tuple[EvidenceRecord, ...], dataset_version: str
) -> Mapping[str, EvidenceRecord]:
    indexed: dict[str, EvidenceRecord] = {}
    for record in records:
        if record.dataset_version != dataset_version:
            raise ValueError("EVIDENCE_DATASET_VERSION_MISMATCH")
        if record.evidence_id in indexed:
            raise ValueError("DUPLICATE_EVIDENCE_RECORD")
        indexed[record.evidence_id] = record
    return indexed


def _unique_calculations(
    records: tuple[CalculationRecord, ...],
) -> Mapping[str, CalculationRecord]:
    indexed: dict[str, CalculationRecord] = {}
    for record in records:
        if record.calculation_id in indexed:
            raise ValueError("DUPLICATE_CALCULATION_RECORD")
        indexed[record.calculation_id] = record
    return indexed


def _validate_result_pins(results: tuple[ToolResult, ...]) -> None:
    first = results[0]
    seen: set[str] = set()
    for result in results:
        if result.task_id in seen:
            raise ValueError("DUPLICATE_TOOL_RESULT")
        seen.add(result.task_id)
        if (
            result.request_key != first.request_key
            or result.run_id != first.run_id
            or result.dataset_version != first.dataset_version
            or result.cutoff_date != first.cutoff_date
            or result.created_at != first.created_at
        ):
            raise ValueError("TOOL_RESULT_PIN_MISMATCH")
        if result.result_hash != canonical_sha256(
            result, exclude_fields=("result_hash",)
        ):
            raise ValueError("TOOL_RESULT_HASH_MISMATCH")
