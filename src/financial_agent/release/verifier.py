"""Deterministic, ordered verification of candidate claims."""

from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from zoneinfo import ZoneInfo

from financial_agent.contracts import (
    AnswerDisposition,
    CalculationType,
    CheckResult,
    CheckStatus,
    CheckTargetType,
    ClaimType,
    CutoffStatus,
    EvidenceKind,
    RejectedClaim,
    Repairability,
    SourceRecord,
    SubtaskCoverage,
    SubtaskImportance,
    VerificationReport,
    VerificationStatus,
)
from financial_agent.contracts.canonical import canonical_sha256
from financial_agent.contracts.values import decode_contract_value

from .claims import ClaimAssembly


_RULE_VERSION = "1.0"
_SEOUL = ZoneInfo("Asia/Seoul")
_APPROVED_CALCULATION_RECIPES = MappingProxyType(
    {
        (
            CalculationType.CONVERSION,
            "identity-unit.v1",
            "1.0",
        ): "identity",
    }
)


class EvidenceVerifier:
    def verify(
        self,
        assembly: ClaimAssembly,
        *,
        sources: tuple[SourceRecord, ...],
    ) -> VerificationReport:
        bundle = assembly.bundle
        expected_bundle_hash = canonical_sha256(
            bundle, exclude_fields=("bundle_id", "bundle_hash")
        )
        if (
            bundle.bundle_hash != expected_bundle_hash
            or bundle.bundle_id != f"evidence-bundle-{expected_bundle_hash[:24]}"
        ):
            raise ValueError("EVIDENCE_BUNDLE_HASH_MISMATCH")
        evidence = {item.evidence_id: item for item in assembly.evidence_records}
        calculations = {
            item.calculation_id: item for item in assembly.calculation_records
        }
        source_by_id = _unique_sources(sources)
        supports = {item.claim_id: item for item in assembly.supports}
        if len(supports) != len(assembly.supports):
            raise ValueError("DUPLICATE_CLAIM_SUPPORT")
        checks: list[CheckResult] = []
        releaseable: list[str] = []
        rejected: list[RejectedClaim] = []

        for claim in assembly.claims:
            support = supports.get(claim.claim_id)
            record = (
                evidence.get(support.evidence_id)
                if support is not None and support.evidence_id is not None
                else None
            )
            calculation = (
                calculations.get(support.calculation_id)
                if support is not None and support.calculation_id is not None
                else None
            )
            supporting_records = (
                (record,)
                if record is not None
                else tuple(
                    evidence[evidence_id]
                    for evidence_id in (
                        calculation.input_evidence_ids
                        if calculation is not None
                        else ()
                    )
                    if evidence_id in evidence
                )
            )
            record = supporting_records[0] if supporting_records else None
            ordered = (
                (
                    "contract-version.v1",
                    _contract_ok(claim, support, supporting_records, calculation),
                ),
                (
                    "source-authority.v1",
                    _sources_ok(supporting_records, source_by_id),
                ),
                (
                    "cutoff.v1",
                    _cutoffs_ok(supporting_records, bundle.cutoff_date),
                ),
                ("ontology.v1", _ontology_ok(claim, record, calculation)),
                (
                    "calculation-comparability.v1",
                    _calculation_ok(claim, calculation, supporting_records),
                ),
                ("coverage-policy.v1", _coverage_ok(claim, record)),
            )
            claim_failed = False
            for rule_id, (passed, reason_code) in ordered:
                if not passed:
                    claim_failed = True
                checks.append(
                    _check(
                        claim.claim_id,
                        rule_id,
                        passed,
                        reason_code,
                        tuple(item.evidence_id for item in supporting_records),
                    )
                )
            if claim_failed:
                rejected.append(
                    RejectedClaim(
                        claim_id=claim.claim_id,
                        reason_code=next(
                            item.reason_code
                            for item in checks
                            if item.target_id == claim.claim_id
                            and item.status is CheckStatus.FAIL
                        ),
                    )
                )
            else:
                releaseable.append(claim.claim_id)

        coverage = tuple(
            SubtaskCoverage(
                subtask_id=subtask_id,
                importance=SubtaskImportance.REQUIRED_INDEPENDENT,
                answered=subtask_id in bundle.answered_subtasks,
                reason_code=(
                    None
                    if subtask_id in bundle.answered_subtasks
                    else next(
                        (
                            item.reason_code
                            for item in bundle.missing_data
                            if item.subtask_id == subtask_id
                        ),
                        "NO_VERIFIED_RESULT",
                    )
                ),
            )
            for subtask_id in sorted(
                {*bundle.answered_subtasks, *bundle.unanswered_subtasks}
            )
        )
        verification_status = (
            VerificationStatus.FAIL if rejected else VerificationStatus.PASS
        )
        disposition = (
            _disposition(bundle)
            if verification_status is VerificationStatus.PASS
            else None
        )
        draft = VerificationReport(
            request_key=bundle.request_key,
            run_id=bundle.run_id,
            dataset_version=bundle.dataset_version,
            cutoff_date=bundle.cutoff_date,
            producer="evidence-verifier.v1",
            created_at=bundle.created_at,
            verification_report_id="pending",
            verification_status=verification_status,
            recommended_answer_disposition=disposition,
            claim_checks=tuple(checks),
            calculation_checks=(),
            subtask_coverage=coverage,
            releaseable_claim_ids=(
                tuple(releaseable)
                if verification_status is VerificationStatus.PASS
                else ()
            ),
            rejected_claims=tuple(rejected),
        )
        report_hash = canonical_sha256(
            draft, exclude_fields=("verification_report_id",)
        )
        return draft.model_copy(
            update={
                "verification_report_id": f"verification-report-{report_hash[:24]}"
            }
        )


def _check(
    claim_id: str,
    rule_id: str,
    passed: bool,
    reason_code: str,
    evidence_ids: tuple[str, ...],
) -> CheckResult:
    status = CheckStatus.PASS if passed else CheckStatus.FAIL
    return CheckResult(
        check_id="check-"
        + canonical_sha256(
            {
                "claim_id": claim_id,
                "rule_id": rule_id,
                "status": status.value,
                "reason_code": reason_code,
            }
        )[:24],
        target_type=CheckTargetType.CLAIM,
        target_id=claim_id,
        rule_id=rule_id,
        rule_version=_RULE_VERSION,
        status=status,
        reason_code=reason_code,
        related_evidence_ids=evidence_ids,
        repairability=(
            Repairability.NONE if passed else Repairability.LEDGER_REBUILD
        ),
    )


def _contract_ok(claim, support, evidence_records, calculation):
    passed = (
        support is not None
        and bool(evidence_records)
        and claim.claim_hash
        == canonical_sha256(claim, exclude_fields=("claim_hash",))
        and all(
            evidence.record_hash
            == canonical_sha256(evidence, exclude_fields=("record_hash",))
            for evidence in evidence_records
        )
        and (
            calculation is None
            or calculation.calculation_hash
            == canonical_sha256(calculation, exclude_fields=("calculation_hash",))
        )
    )
    return passed, "OK" if passed else "CONTRACT_OR_HASH_MISMATCH"


def _sources_ok(evidence_records, source_by_id):
    passed = bool(evidence_records) and all(
        (source := source_by_id.get(evidence.source_id)) is not None
        and source.eligible_for_claim
        for evidence in evidence_records
    )
    return passed, "OK" if passed else "SOURCE_NOT_CLAIM_ELIGIBLE"


def _cutoffs_ok(evidence_records, cutoff_date):
    if not evidence_records:
        return False, "EVIDENCE_MISSING"
    results = tuple(_cutoff_ok(evidence, cutoff_date) for evidence in evidence_records)
    return (
        all(item[0] for item in results),
        "OK" if all(item[0] for item in results) else "EVIDENCE_AFTER_CUTOFF",
    )


def _cutoff_ok(evidence, cutoff_date):
    dates = (
        evidence.available_at,
        evidence.published_at,
    )
    after_cutoff = any(
        isinstance(value, datetime)
        and value.astimezone(_SEOUL).date() > cutoff_date
        for value in dates
    ) or any(
        value is not None and value > cutoff_date
        for value in (
            evidence.applicable_date,
            evidence.valid_from,
            evidence.vintage_date,
        )
    )
    valid = evidence.valid_to is None or evidence.valid_to >= cutoff_date
    passed = (
        evidence.cutoff_status is CutoffStatus.ELIGIBLE
        and not after_cutoff
        and valid
    )
    return passed, "OK" if passed else "EVIDENCE_AFTER_CUTOFF"


def _ontology_ok(claim, evidence, calculation):
    if calculation is not None:
        passed = (
            claim.predicate_id == f"calculated:{calculation.formula_id}"
            and claim.value == calculation.result_value
        )
        return passed, "OK" if passed else "CLAIM_CALCULATION_MISMATCH"
    if evidence is None:
        return False, "EVIDENCE_MISSING"
    target_matches = (
        claim.subject_id == evidence.subject_id
        and claim.predicate_id == evidence.predicate_id
    )
    if claim.claim_type is ClaimType.RELATION:
        target_matches = target_matches and (
            evidence.evidence_kind is EvidenceKind.RELATION
            and claim.object_id
            == decode_contract_value(evidence.normalized_value)
        )
    elif evidence.evidence_kind is EvidenceKind.DOCUMENT_SPAN:
        target_matches = target_matches and (
            claim.value is not None
            and decode_contract_value(claim.value) == evidence.raw_value_repr
        )
    else:
        target_matches = target_matches and (
            claim.value == evidence.normalized_value
        )
    return target_matches, "OK" if target_matches else "CLAIM_EVIDENCE_MISMATCH"


def _calculation_ok(claim, calculation, evidence_records):
    calculation_claim = claim.claim_type in {
        ClaimType.DERIVED_METRIC,
        ClaimType.RANK,
        ClaimType.SIMILARITY,
    }
    if not calculation_claim:
        return True, "NOT_APPLICABLE"
    if (
        claim.claim_type is ClaimType.SIMILARITY
        or calculation is not None
        and calculation.calculation_type is CalculationType.SIMILARITY
    ):
        return False, "SIMILARITY_POLICY_NOT_ACTIVE"
    if calculation is None or not calculation.input_evidence_ids:
        return False, "CALCULATION_SUPPORT_REQUIRED"
    recipe = _APPROVED_CALCULATION_RECIPES.get(
        (
            calculation.calculation_type,
            calculation.formula_id,
            calculation.formula_version,
        )
    )
    if recipe is None:
        return False, "CALCULATION_RECIPE_NOT_APPROVED"
    if tuple(calculation.input_evidence_ids) != tuple(
        evidence.evidence_id for evidence in evidence_records
    ):
        return False, "CALCULATION_INPUT_EVIDENCE_MISMATCH"
    if recipe == "identity":
        evidence = evidence_records[0] if len(evidence_records) == 1 else None
        passed = (
            evidence is not None
            and not calculation.input_calculation_ids
            and not calculation.parameters
            and calculation.population_definition is None
            and not calculation.exclusion_evidence_ids
            and calculation.tie_break_rule is None
            and calculation.rounding_rule == "no-rounding.v1"
            and calculation.result_value == evidence.normalized_value
            and calculation.unit == evidence.unit
            and calculation.currency == evidence.currency
        )
        return passed, "OK" if passed else "CALCULATION_RECOMPUTE_MISMATCH"
    return False, "CALCULATION_RECIPE_NOT_APPROVED"


def _coverage_ok(claim, evidence):
    if claim.claim_type is ClaimType.NO_MATCH:
        passed = (
            evidence is not None
            and evidence.evidence_kind is EvidenceKind.QUERY_SCOPE
            and evidence.scope_completeness == "closed_world"
        )
        return passed, "OK" if passed else "CLOSED_WORLD_SCOPE_REQUIRED"
    return True, "OK"


def _unique_sources(sources):
    indexed = {}
    for source in sources:
        if source.source_id in indexed:
            raise ValueError("DUPLICATE_SOURCE_RECORD")
        indexed[source.source_id] = source
    return indexed


def _disposition(bundle) -> AnswerDisposition:
    if bundle.answered_subtasks and not bundle.unanswered_subtasks:
        return AnswerDisposition.ANSWER
    if bundle.answered_subtasks:
        return AnswerDisposition.PARTIAL
    return AnswerDisposition.LIMITATION
