from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from financial_agent.contracts.enums import (
    CalculationType,
    ClaimType,
    CutoffStatus,
    SupportKind,
)
from financial_agent.contracts.evidence import (
    AtomicClaim,
    CalculationRecord,
    ClaimQualifier,
    ClaimSupport,
    EvidenceBundle,
    EvidenceRecord,
    PopulationDefinition,
)
from financial_agent.contracts.values import (
    NullValue,
    decode_contract_value,
    encode_contract_value,
)


def test_claim_support_requires_exactly_one_support_target() -> None:
    with pytest.raises(ValidationError):
        ClaimSupport(
            claim_id="claim-1",
            support_kind=SupportKind.DIRECT,
            evidence_id="evidence-1",
            calculation_id="calculation-1",
            support_role="value",
            ordinal=0,
        )

    with pytest.raises(ValidationError):
        ClaimSupport(
            claim_id="claim-1",
            support_kind=SupportKind.DIRECT,
            evidence_id=None,
            calculation_id=None,
            support_role="value",
            ordinal=0,
        )


def test_evidence_bundle_keeps_candidate_claims_unreleased(
    load_fixture_json,
) -> None:
    bundle = EvidenceBundle.model_validate_json(
        load_fixture_json("evidence_bundle.json")
    )
    assert bundle.candidate_claim_ids == ("claim-rank-1",)
    assert "releaseable_claim_ids" not in EvidenceBundle.model_fields


def test_after_cutoff_evidence_can_be_represented_for_rejection(
    load_fixture, dump_json
) -> None:
    payload = load_fixture("evidence_record.json") | {
        "applicable_date": "2026-07-12",
        "cutoff_status": "after_cutoff",
    }
    evidence = EvidenceRecord.model_validate_json(dump_json(payload))
    assert evidence.cutoff_status is CutoffStatus.AFTER_CUTOFF
    assert evidence.value_or_object_id.type == "decimal"


def test_evidence_record_rejects_untagged_values(load_fixture, dump_json) -> None:
    payload = load_fixture("evidence_record.json")
    payload["value_or_object_id"] = 125000000

    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate_json(dump_json(payload))


def test_evidence_record_does_not_infer_missing_metadata(
    load_fixture, dump_json
) -> None:
    payload = load_fixture("evidence_record.json") | {
        "value_or_object_id": {"type": "null", "value": None},
        "normalized_value": {"type": "null", "value": None},
        "unit": None,
        "currency": None,
        "applicable_date": None,
        "valid_from": None,
        "valid_to": None,
        "published_at": None,
        "available_at": None,
        "vintage_date": None,
    }

    evidence = EvidenceRecord.model_validate_json(dump_json(payload))

    assert isinstance(evidence.value_or_object_id, NullValue)
    assert isinstance(evidence.normalized_value, NullValue)
    assert decode_contract_value(evidence.value_or_object_id) is None
    assert decode_contract_value(evidence.normalized_value) is None
    assert evidence.unit is None
    assert evidence.currency is None
    assert evidence.applicable_date is None
    assert evidence.valid_from is None
    assert evidence.valid_to is None
    assert evidence.published_at is None
    assert evidence.available_at is None
    assert evidence.vintage_date is None


@pytest.mark.parametrize(
    "payload_update",
    [
        {"evidence_kind": "query_scope", "scope_completeness": None},
        {"evidence_kind": "observation", "scope_completeness": "closed_world"},
    ],
)
def test_scope_completeness_is_only_allowed_for_query_scope(
    load_fixture, dump_json, payload_update: dict[str, object]
) -> None:
    payload = load_fixture("evidence_record.json") | payload_update

    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate_json(dump_json(payload))


def test_evidence_record_rejects_reversed_validity_window(
    load_fixture, dump_json
) -> None:
    payload = load_fixture("evidence_record.json") | {
        "valid_from": "2026-07-11",
        "valid_to": "2026-07-10",
    }

    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate_json(dump_json(payload))


def test_ranking_calculation_requires_population_definition() -> None:
    with pytest.raises(ValidationError):
        CalculationRecord(
            calculation_id="calculation-rank-1",
            calculation_type=CalculationType.RANKING,
            formula_id="ranking.desc.v1",
            formula_version="v1",
            input_evidence_ids=("evidence-aum-1",),
            input_calculation_ids=(),
            parameters=(),
            population_definition=None,
            exclusion_evidence_ids=(),
            tie_break_rule="product-id-asc",
            result_value=encode_contract_value(1),
            unit="rank",
            currency=None,
            rounding_rule=None,
            calculation_hash="d" * 64,
        )


def test_aggregation_calculation_requires_population_definition() -> None:
    with pytest.raises(ValidationError):
        CalculationRecord(
            calculation_id="calculation-aggregate-1",
            calculation_type=CalculationType.AGGREGATION,
            formula_id="sum.v1",
            formula_version="v1",
            input_evidence_ids=("evidence-aum-1",),
            result_value=encode_contract_value(Decimal("125000000")),
            unit="unit-krw",
            currency="KRW",
            calculation_hash="d" * 64,
        )


def test_calculation_requires_at_least_one_input() -> None:
    with pytest.raises(ValidationError):
        CalculationRecord(
            calculation_id="calculation-conversion-1",
            calculation_type=CalculationType.CONVERSION,
            formula_id="conversion.v1",
            formula_version="v1",
            result_value=encode_contract_value(Decimal("125000000")),
            unit="unit-krw",
            currency="KRW",
            calculation_hash="d" * 64,
        )


def test_ranking_calculation_requires_tie_break_rule() -> None:
    with pytest.raises(ValidationError):
        CalculationRecord(
            calculation_id="calculation-rank-1",
            calculation_type=CalculationType.RANKING,
            formula_id="ranking.desc.v1",
            formula_version="v1",
            input_evidence_ids=("evidence-aum-1",),
            population_definition=PopulationDefinition(
                population_id="population-etf-1",
                scope_evidence_id="evidence-scope-1",
                filter_ids=("filter-aum-present",),
                member_count=1,
                population_hash="3" * 64,
            ),
            result_value=encode_contract_value(1),
            unit="rank",
            calculation_hash="d" * 64,
        )


def test_atomic_claim_rejects_object_and_value_together() -> None:
    with pytest.raises(ValidationError):
        AtomicClaim(
            claim_id="claim-invalid-1",
            claim_type=ClaimType.DIRECT_FACT,
            subtask_id="q1",
            subject_id="product-syn-etf-a",
            predicate_id="managedBy",
            object_id="manager-syn-a",
            value=encode_contract_value("duplicate-value"),
            unit=None,
            currency=None,
            qualifiers=(),
            display_policy_id="text.v1",
            claim_hash="e" * 64,
        )


def test_atomic_claim_requires_object_or_value() -> None:
    with pytest.raises(ValidationError):
        AtomicClaim(
            claim_id="claim-invalid-1",
            claim_type=ClaimType.DIRECT_FACT,
            subtask_id="q1",
            subject_id="product-syn-etf-a",
            predicate_id="aum",
            value=None,
            display_policy_id="amount.v1",
            claim_hash="e" * 64,
        )


@pytest.mark.parametrize(
    "claim_type",
    [ClaimType.DATA_LIMITATION, ClaimType.POLICY_BOUNDARY],
)
def test_limitation_claims_allow_structured_qualifier_only(
    claim_type: ClaimType,
) -> None:
    claim = AtomicClaim(
        claim_id="claim-limitation-1",
        claim_type=claim_type,
        subtask_id="q1",
        subject_id="product-syn-etf-a",
        predicate_id="availability",
        value=None,
        qualifiers=(
            ClaimQualifier(
                qualifier_id="reason",
                value=encode_contract_value("missing-field"),
            ),
        ),
        display_policy_id="limitation.v1",
        claim_hash="e" * 64,
    )

    assert claim.object_id is None
    assert claim.value is None


@pytest.mark.parametrize(
    "claim_type",
    [ClaimType.DATA_LIMITATION, ClaimType.POLICY_BOUNDARY],
)
def test_qualifier_only_claim_requires_a_qualifier(
    claim_type: ClaimType,
) -> None:
    with pytest.raises(ValidationError):
        AtomicClaim(
            claim_id="claim-limitation-1",
            claim_type=claim_type,
            subtask_id="q1",
            subject_id="product-syn-etf-a",
            predicate_id="availability",
            value=None,
            display_policy_id="limitation.v1",
            claim_hash="e" * 64,
        )


@pytest.mark.parametrize(
    "id_field",
    [
        "answered_subtasks",
        "unanswered_subtasks",
        "evidence_ids",
        "calculation_ids",
        "candidate_claim_ids",
        "exclusion_evidence_ids",
    ],
)
def test_evidence_bundle_rejects_duplicate_ids(
    load_fixture, dump_json, id_field: str
) -> None:
    payload = load_fixture("evidence_bundle.json")
    values = payload[id_field]
    assert isinstance(values, list)
    duplicate = values[0] if values else "duplicate-id"
    payload[id_field] = [duplicate, duplicate]

    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate_json(dump_json(payload))


def test_evidence_bundle_rejects_answered_unanswered_overlap(
    load_fixture, dump_json
) -> None:
    payload = load_fixture("evidence_bundle.json") | {
        "answered_subtasks": ["s1"],
        "unanswered_subtasks": ["s1"],
    }

    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate_json(dump_json(payload))


def test_evidence_bundle_rejects_invalid_bundle_hash(
    load_fixture, dump_json
) -> None:
    payload = deepcopy(load_fixture("evidence_bundle.json"))
    payload["bundle_hash"] = "F" * 64

    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate_json(dump_json(payload))
