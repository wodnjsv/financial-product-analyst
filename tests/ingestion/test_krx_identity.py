from __future__ import annotations

from datetime import date

import pytest

from financial_agent.ingestion.identity import (
    build_authoritative_identity_index,
)
from financial_agent.ingestion.models import IdentifierCandidate, MappedRow
from financial_agent.ingestion.official.krx_identity import (
    map_krx_security_basic,
    parse_krx_security_basic,
)
from financial_agent.ingestion.sources import SourceVerificationError
from tests.fixtures.official_ingestion import (
    krx_security_basic_payload,
    official_manifest,
)


def _records(row: MappedRow, table: str) -> tuple[dict[str, object], ...]:
    return tuple(dict(item) for item in row.records_by_table[table])


def test_krx_basic_parser_reads_only_the_approved_response_envelope() -> None:
    payload = krx_security_basic_payload()

    rows = parse_krx_security_basic(payload, market="KOSPI")

    assert rows == (
        {
            "ISU_CD": "KR7000000001",
            "ISU_SRT_CD": "000001",
            "ISU_NM": "합성 보통주",
            "ISU_ABBRV": "합성주",
            "ISU_ENG_NM": "Synthetic Common Stock",
        },
    )


@pytest.mark.parametrize(
    "payload",
    (
        b'{"wrong":[]}',
        krx_security_basic_payload(
            (
                {
                    "ISU_CD": "KR7000000001",
                    "ISU_SRT_CD": "000001",
                    "ISU_NM": "합성 보통주",
                    "ISU_ABBRV": "합성주",
                },
            )
        ),
    ),
)
def test_krx_basic_parser_rejects_schema_drift(payload: bytes) -> None:
    with pytest.raises(SourceVerificationError) as captured:
        parse_krx_security_basic(payload, market="KOSPI")

    assert captured.value.code == "KRX_BASIC_SCHEMA_MISMATCH"
    assert captured.value.__cause__ is None


def test_krx_basic_parser_rejects_an_empty_official_population() -> None:
    with pytest.raises(SourceVerificationError) as captured:
        parse_krx_security_basic(b'{"OutBlock_1":[]}', market="KOSPI")

    assert captured.value.code == "KRX_BASIC_SCHEMA_MISMATCH"


def test_krx_basic_mapper_emits_exact_security_identity_with_evidence() -> None:
    payload = krx_security_basic_payload()
    manifest = official_manifest(
        source_code="KRX_KOSPI_BASIC",
        object_name="kospi-basic.json",
        payload=payload,
        applicable_date=date(2026, 7, 10),
    )

    mapped = tuple(
        map_krx_security_basic(
            manifest,
            parse_krx_security_basic(payload, market="KOSPI"),
        )
    )

    assert len(mapped) == 1
    assert mapped[0].disposition == "accepted"
    entities = _records(mapped[0], "catalog.entity")
    security_entity = next(item for item in entities if item["entity_type"] == "security")
    assert security_entity["canonical_name"] == "합성 보통주"
    security = _records(mapped[0], "catalog.security")[0]
    assert security == {
        "entity_id": security_entity["entity_id"],
        "security_kind": "listed_equity",
        "ticker_display": "000001",
        "isin_display": None,
    }
    identifiers = _records(mapped[0], "catalog.identifier")
    assert {(item["scheme"], item["identifier_value"]) for item in identifiers} == {
        ("KRX_STANDARD_ISSUE_CODE", "KR7000000001"),
        ("KRX_SHORT_ISSUE_CODE", "000001"),
    }
    assert {item["alias_text"] for item in _records(mapped[0], "catalog.alias")} == {
        "합성주",
        "Synthetic Common Stock",
    }
    observations = _records(mapped[0], "observation.observation_record")
    evidence = _records(mapped[0], "evidence.evidence_record")
    origins = _records(mapped[0], "evidence.evidence_observation_origin")
    assert len(observations) == len(evidence) == len(origins) == 5
    assert {item["applicable_date"] for item in observations} == {
        date(2026, 7, 10)
    }
    assert {item["locator_column"] for item in evidence} == {
        "ISU_CD",
        "ISU_SRT_CD",
        "ISU_NM",
        "ISU_ABBRV",
        "ISU_ENG_NM",
    }
    assert all(len(str(item["record_hash"])) == 64 for item in entities)
    assert _records(mapped[0], "relation.relation_record") == ()


@pytest.mark.parametrize("duplicate_field", ("standard", "short"))
def test_duplicate_krx_issue_code_rejects_the_snapshot(
    duplicate_field: str,
) -> None:
    payload = krx_security_basic_payload(
        (
            {
                "ISU_CD": "KR7000000001",
                "ISU_SRT_CD": "000001",
                "ISU_NM": "합성 보통주 A",
                "ISU_ABBRV": "합성A",
                "ISU_ENG_NM": "Synthetic A",
            },
            {
                "ISU_CD": (
                    "KR7000000001"
                    if duplicate_field == "standard"
                    else "KR7000000002"
                ),
                "ISU_SRT_CD": (
                    "000002" if duplicate_field == "standard" else "000001"
                ),
                "ISU_NM": "합성 보통주 B",
                "ISU_ABBRV": "합성B",
                "ISU_ENG_NM": "Synthetic B",
            },
        )
    )
    manifest = official_manifest(
        source_code="KRX_KOSPI_BASIC",
        object_name="kospi-basic.json",
        payload=payload,
        applicable_date=date(2026, 7, 10),
    )

    with pytest.raises(SourceVerificationError) as captured:
        tuple(
            map_krx_security_basic(
                manifest,
                parse_krx_security_basic(payload, market="KOSPI"),
            )
        )

    assert captured.value.code == "KRX_BASIC_IDENTITY_CONFLICT"
    assert captured.value.__cause__ is None


def _organizer_index(*natural_keys: str):
    return build_authoritative_identity_index(
        tuple(
            IdentifierCandidate(
                source_code="PREF02N001",
                row_number=row_number,
                natural_key=natural_key,
                entity_role="OverseasETF",
                scheme="ISIN",
                value="KR7005930003",
            )
            for row_number, natural_key in enumerate(natural_keys, start=2)
        )
    )


def test_krx_basic_mapper_reuses_an_exact_organizer_isin_without_overwrite() -> None:
    payload = krx_security_basic_payload(
        (
            {
                "ISU_CD": "KR7005930003",
                "ISU_SRT_CD": "005930",
                "ISU_NM": "삼성전자",
                "ISU_ABBRV": "삼성전자",
                "ISU_ENG_NM": "Samsung Electronics",
            },
        )
    )
    manifest = official_manifest(
        source_code="KRX_KOSPI_BASIC",
        object_name="kospi-basic.json",
        payload=payload,
        applicable_date=date(2026, 8, 22),
    )
    organizer_index = _organizer_index("organizer-product-1")
    canonical = organizer_index.resolve("ISIN", "KR7005930003")
    assert canonical.canonical_identity is not None

    mapped = tuple(
        map_krx_security_basic(
            manifest,
            parse_krx_security_basic(payload, market="KOSPI"),
            identity_index=organizer_index,
        )
    )

    assert mapped[0].disposition == "accepted"
    assert not any(
        row.get("entity_id") == canonical.canonical_identity.entity_id
        for row in _records(mapped[0], "catalog.entity")
    )
    assert not _records(mapped[0], "catalog.security")
    assert {
        row["entity_id"]
        for row in _records(mapped[0], "observation.observation_record")
    } == {canonical.canonical_identity.entity_id}


def test_krx_basic_mapper_quarantines_an_ambiguous_organizer_isin() -> None:
    payload = krx_security_basic_payload(
        (
            {
                "ISU_CD": "KR7005930003",
                "ISU_SRT_CD": "005930",
                "ISU_NM": "삼성전자",
                "ISU_ABBRV": "삼성전자",
                "ISU_ENG_NM": "Samsung Electronics",
            },
        )
    )
    manifest = official_manifest(
        source_code="KRX_KOSPI_BASIC",
        object_name="kospi-basic.json",
        payload=payload,
        applicable_date=date(2026, 8, 22),
    )

    mapped = tuple(
        map_krx_security_basic(
            manifest,
            parse_krx_security_basic(payload, market="KOSPI"),
            identity_index=_organizer_index(
                "organizer-product-1", "organizer-product-2"
            ),
        )
    )

    assert mapped[0].disposition == "quarantined"
    assert {issue.code for issue in mapped[0].issues} == {
        "ORGANIZER_IDENTITY_AMBIGUOUS"
    }
