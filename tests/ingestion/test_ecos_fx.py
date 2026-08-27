from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from financial_agent.ingestion.official import (
    ECOS_ITEMS,
    map_ecos_fx,
    parse_ecos_731y001,
)
from financial_agent.ingestion.models import MappedRow
from financial_agent.ingestion.sources import SourceVerificationError
from tests.fixtures.official_ingestion import (
    ecos_731y001_payload,
    official_manifest,
)


def _payload_rows(payload: bytes | None = None) -> list[dict[str, str]]:
    decoded = json.loads((payload or ecos_731y001_payload()).decode("utf-8"))
    return [dict(row) for row in decoded["StatisticSearch"]["row"]]


def _records(
    rows: tuple[MappedRow, ...], table: str
) -> tuple[dict[str, object], ...]:
    return tuple(
        dict(record)
        for row in rows
        for record in row.records_by_table[table]
    )


def _manifest(
    payload: bytes, *, applicable_date: date = date(2026, 7, 10)
):
    return official_manifest(
        source_code="ECOS_731Y001",
        object_name="731Y001-daily.json",
        payload=payload,
        applicable_date=applicable_date,
    )


def test_ecos_parser_preserves_the_four_approved_numeric_text_values() -> None:
    rows = parse_ecos_731y001(ecos_731y001_payload())

    assert {str(row["ITEM_CODE1"]) for row in rows} == set(ECOS_ITEMS)
    assert {type(row["DATA_VALUE"]) for row in rows} == {str}
    assert next(
        row for row in rows if row["ITEM_CODE1"] == "0000002"
    )["ITEM_NAME1"] == "원/일본엔(100엔)"


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("STAT_CODE", "731Y999"),
        ("ITEM_NAME1", "잘못된 항목명"),
        ("UNIT_NAME", "달러"),
    ),
)
def test_ecos_parser_rejects_unapproved_codes_names_and_units(
    column: str, value: str
) -> None:
    rows = _payload_rows()
    rows[0][column] = value

    with pytest.raises(SourceVerificationError) as captured:
        parse_ecos_731y001(ecos_731y001_payload(tuple(rows)))

    assert captured.value.code == "ECOS_FX_SCHEMA_MISMATCH"
    assert captured.value.__cause__ is None


def test_ecos_parser_ignores_unapproved_rows_and_selects_the_four_allowlist_items() -> None:
    rows = _payload_rows()
    rows.append(
        dict(rows[0])
        | {
            "ITEM_CODE1": "9999999",
            "ITEM_NAME1": "공식 응답의 다른 환율 항목",
            "DATA_VALUE": "123.45",
        }
    )

    selected = parse_ecos_731y001(ecos_731y001_payload(tuple(rows)))

    assert len(selected) == 4
    assert {str(row["ITEM_CODE1"]) for row in selected} == set(ECOS_ITEMS)


def test_ecos_parser_does_not_count_an_unapproved_item_as_required_coverage() -> None:
    rows = _payload_rows()
    rows[0] = dict(rows[0]) | {
        "ITEM_CODE1": "9999999",
        "ITEM_NAME1": "공식 응답의 다른 환율 항목",
    }

    with pytest.raises(SourceVerificationError) as captured:
        parse_ecos_731y001(ecos_731y001_payload(tuple(rows)))

    assert captured.value.code == "ECOS_FX_COVERAGE_INCOMPLETE"


def test_ecos_parser_requires_every_approved_item() -> None:
    rows = tuple(_payload_rows()[1:])

    with pytest.raises(SourceVerificationError) as captured:
        parse_ecos_731y001(ecos_731y001_payload(rows))

    assert captured.value.code == "ECOS_FX_COVERAGE_INCOMPLETE"


@pytest.mark.parametrize("value", ("1,301.25", "not-a-number", "1e3"))
def test_ecos_parser_rejects_noncanonical_decimal_text(value: str) -> None:
    rows = _payload_rows()
    rows[0]["DATA_VALUE"] = value

    with pytest.raises(SourceVerificationError) as captured:
        parse_ecos_731y001(ecos_731y001_payload(tuple(rows)))

    assert captured.value.code == "ECOS_FX_VALUE_INVALID"


def test_ecos_parser_rejects_duplicate_item_dates() -> None:
    rows = _payload_rows()
    rows.append(dict(rows[0]))

    with pytest.raises(SourceVerificationError) as captured:
        parse_ecos_731y001(ecos_731y001_payload(tuple(rows)))

    assert captured.value.code == "ECOS_FX_DUPLICATE_OBSERVATION"


def test_ecos_mapper_selects_each_latest_pre_cutoff_observation_independently() -> None:
    rows = _payload_rows()
    rows.extend(
        (
            dict(rows[0]) | {"TIME": "20260709", "DATA_VALUE": "1299.75"},
            dict(rows[1]) | {"TIME": "20260708", "DATA_VALUE": "889.50"},
            dict(rows[2]) | {"TIME": "20260825", "DATA_VALUE": "9999.99"},
            dict(rows[3]) | {"TIME": "20260707", "DATA_VALUE": "179.25"},
        )
    )
    payload = ecos_731y001_payload(tuple(reversed(rows)))

    mapped = map_ecos_fx(_manifest(payload), parse_ecos_731y001(payload))
    observations = _records(mapped, "observation.observation_record")

    assert {item["metric_id"]: item["numeric_value"] for item in observations} == {
        "ecos_731y001_krw_per_usd": Decimal("1301.25"),
        "ecos_731y001_krw_per_100_jpy": Decimal("891.25"),
        "ecos_731y001_krw_per_eur": Decimal("1502.75"),
        "ecos_731y001_krw_per_cny": Decimal("181.05"),
    }
    assert {item["applicable_date"] for item in observations} == {
        date(2026, 7, 10)
    }


def test_ecos_mapper_includes_observations_on_the_cutoff_date() -> None:
    rows = tuple(
        dict(row) | {"TIME": "20260824"} for row in _payload_rows()
    )
    payload = ecos_731y001_payload(rows)

    mapped = map_ecos_fx(
        _manifest(payload, applicable_date=date(2026, 8, 24)),
        parse_ecos_731y001(payload),
    )

    assert {
        item["applicable_date"]
        for item in _records(mapped, "observation.observation_record")
    } == {date(2026, 8, 24)}


def test_ecos_mapper_rejects_a_snapshot_available_after_the_cutoff() -> None:
    payload = ecos_731y001_payload()
    manifest = replace(
        _manifest(payload, applicable_date=date(2026, 8, 24)),
        available_at=datetime(2026, 8, 25, tzinfo=UTC),
    )

    with pytest.raises(SourceVerificationError) as captured:
        map_ecos_fx(manifest, parse_ecos_731y001(payload))

    assert captured.value.code == "OFFICIAL_CUTOFF_VIOLATION"
    assert captured.value.__cause__ is None


def test_ecos_mapper_rejects_an_item_with_no_pre_cutoff_observation() -> None:
    rows = _payload_rows()
    rows[0]["TIME"] = "20260825"
    payload = ecos_731y001_payload(tuple(rows))

    with pytest.raises(SourceVerificationError) as captured:
        map_ecos_fx(_manifest(payload), parse_ecos_731y001(payload))

    assert captured.value.code == "ECOS_FX_COVERAGE_INCOMPLETE"


def test_ecos_mapper_emits_fixed_metric_semantics_and_exact_evidence() -> None:
    payload = ecos_731y001_payload()

    mapped = map_ecos_fx(_manifest(payload), parse_ecos_731y001(payload))

    assert len(mapped) == 4
    assert {row.disposition for row in mapped} == {"accepted"}
    entities = _records(mapped, "catalog.entity")
    assert {
        (item["entity_type"], item["canonical_name"]) for item in entities
    } == {("institution", "Bank of Korea")}
    institutions = _records(mapped, "catalog.institution")
    assert {item["institution_kind"] for item in institutions} == {
        "central_bank"
    }
    identifiers = _records(mapped, "catalog.identifier")
    assert {
        (item["scheme"], item["identifier_value"]) for item in identifiers
    } == {("OFFICIAL_PUBLISHER_CODE", "BOK")}

    definitions = _records(mapped, "observation.metric_definition")
    assert {item["metric_id"] for item in definitions} == {
        "ecos_731y001_krw_per_usd",
        "ecos_731y001_krw_per_100_jpy",
        "ecos_731y001_krw_per_eur",
        "ecos_731y001_krw_per_cny",
    }
    jpy_definition = next(
        item
        for item in definitions
        if item["metric_id"] == "ecos_731y001_krw_per_100_jpy"
    )
    assert '"base_units":100' in str(jpy_definition["description"])
    assert '"base_currency":"JPY"' in str(jpy_definition["description"])
    assert '"quote_currency":"KRW"' in str(jpy_definition["description"])

    observations = _records(mapped, "observation.observation_record")
    assert {item["unit"] for item in observations} == {"KRW"}
    assert {item["currency"] for item in observations} == {"KRW"}
    assert {item["published_at"] for item in observations} == {None}
    assert {item["available_at"] for item in observations} == {
        _manifest(payload).available_at
    }
    evidence = _records(mapped, "evidence.evidence_record")
    assert {item["locator_column"] for item in evidence} == {"DATA_VALUE"}
    assert {item["locator_record_key"] for item in evidence} == {
        "731Y001:0000001:20260710",
        "731Y001:0000002:20260710",
        "731Y001:0000003:20260710",
        "731Y001:0000053:20260710",
    }
    assert all(
        "item_code=" in str(item["normalized_value"]["value"])
        and "quote_currency=KRW" in str(item["normalized_value"]["value"])
        for item in evidence
    )
    assert len(_records(mapped, "evidence.evidence_observation_origin")) == 4
