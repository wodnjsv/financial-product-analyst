from __future__ import annotations

import csv
import gc
import io
import stat
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

import financial_agent.ingestion.official.sec_nport as sec_nport_module
from financial_agent.ingestion.official import (
    NportArchiveLimits,
    NportProductBinding,
    iter_eligible_nport_funds,
    verify_and_extract_nport,
)
from financial_agent.ingestion.official.identity import OfficialIdentityIndex
from financial_agent.ingestion.official.sec_series_class import (
    build_sec_series_class_index,
    parse_sec_series_class,
)
from financial_agent.ingestion.models import MappedRow
from financial_agent.ingestion.sources import SourceVerificationError
from financial_agent.ingestion.writer import DatasetBuildWriter
from tests.fixtures.official_ingestion import (
    official_manifest,
    sec_nport_tsv_files,
    sec_series_class_payload,
    write_sec_nport_archive,
)


def _capture_error(
    archive: Path,
    destination: Path,
    *,
    limits: NportArchiveLimits | None = None,
) -> SourceVerificationError:
    with pytest.raises(SourceVerificationError) as captured:
        verify_and_extract_nport(
            archive,
            destination,
            limits or NportArchiveLimits(),
        )
    assert captured.value.__cause__ is None
    assert not destination.exists()
    return captured.value


def _decode_tsv(payload: bytes) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8")), delimiter="\t")
    return tuple(reader.fieldnames or ()), [dict(row) for row in reader]


def _encode_tsv(
    fields: tuple[str, ...], rows: list[dict[str, str]]
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output, fieldnames=fields, delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _replace_rows(
    files: dict[str, bytes], name: str, rows: list[dict[str, str]]
) -> None:
    fields, _ = _decode_tsv(files[name])
    files[name] = _encode_tsv(fields, rows)


def _write_mapping_files(
    root: Path, files: dict[str, bytes] | None = None
) -> dict[str, Path]:
    values = files or sec_nport_tsv_files()
    root.mkdir()
    paths: dict[str, Path] = {}
    for name, payload in values.items():
        path = root / name
        path.write_bytes(payload)
        paths[name] = path
    return paths


def _nport_manifest(files: dict[str, bytes]):
    package = b"".join(files[name] for name in sorted(files))
    return official_manifest(
        source_code="SEC_NPORT_2026Q2",
        object_name="2026q2_nport.zip",
        payload=package,
        applicable_date=date(2026, 3, 31),
        published_at=datetime(2026, 6, 30, tzinfo=UTC),
        available_at=datetime(2026, 7, 9, tzinfo=UTC),
        media_type="application/zip",
    )


def _series_index(rows: tuple[dict[str, str], ...] | None = None):
    payload = sec_series_class_payload(rows)
    manifest = official_manifest(
        source_code="SEC_SERIES_CLASS_20260601",
        object_name="series-class.csv",
        payload=payload,
        applicable_date=date(2026, 6, 1),
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        available_at=datetime(2026, 6, 1, tzinfo=UTC),
        media_type="text/csv",
    )
    return build_sec_series_class_index(
        manifest, parse_sec_series_class(payload)
    )


def _binding(
    *, product_id: str = "organizer-overseas-etf-1", ticker: str = "synx"
) -> NportProductBinding:
    return NportProductBinding(
        product_entity_id=product_id,
        cik="0000123456",
        class_ticker=ticker,
    )


def _map_files(
    tmp_path: Path,
    files: dict[str, bytes] | None = None,
    bindings: tuple[NportProductBinding, ...] | None = None,
    series_index: OfficialIdentityIndex | None = None,
    matched_product_sample_size: int | None = None,
) -> tuple[MappedRow, ...]:
    values = files or sec_nport_tsv_files()
    return tuple(
        iter_eligible_nport_funds(
            _write_mapping_files(tmp_path / "nport-files", values),
            date(2026, 7, 11),
            manifest=_nport_manifest(values),
            series_class_index=series_index or _series_index(),
            product_bindings=bindings or (_binding(),),
            matched_product_sample_size=matched_product_sample_size,
        )
    )


def _records(
    rows: tuple[MappedRow, ...], table: str
) -> tuple[dict[str, object], ...]:
    return tuple(
        dict(record)
        for row in rows
        for record in row.records_by_table[table]
    )


def test_capacity_probe_selects_a_stable_sample_of_matched_products(
    tmp_path: Path,
) -> None:
    mapped = _map_files(
        tmp_path,
        bindings=(
            _binding(product_id="product-b"),
            _binding(product_id="unmatched", ticker="MISS"),
            _binding(product_id="product-a"),
        ),
        matched_product_sample_size=1,
    )

    assert len(mapped) == 1
    relations = _records(mapped, "relation.relation_record")
    assert {
        row["subject_id"]
        for row in relations
        if row["predicate_id"] == "holdsSecurity"
    } == {"product-a"}
    assert {
        row["metric_id"]
        for row in _records(mapped, "observation.observation_record")
    } == {
        "official_holding_asset_category",
        "official_holding_balance",
        "official_holding_currency",
        "official_holding_currency_value",
        "official_holding_investment_country",
        "official_holding_weight_pct",
    }


def test_capacity_probe_rejects_a_sample_larger_than_the_matched_population(
    tmp_path: Path,
) -> None:
    with pytest.raises(SourceVerificationError) as captured:
        _map_files(
            tmp_path,
            bindings=(_binding(),),
            matched_product_sample_size=2,
        )

    assert captured.value.code == "SEC_NPORT_SAMPLE_INSUFFICIENT"


def test_nport_extractor_writes_only_the_five_approved_files(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files() | {"README.txt": b"official package note\n"}
    archive = write_sec_nport_archive(tmp_path / "nport.zip", files)
    destination = tmp_path / "extracted"

    extracted = verify_and_extract_nport(
        archive, destination, NportArchiveLimits()
    )

    assert set(extracted) == set(sec_nport_tsv_files())
    assert {path.name for path in destination.iterdir()} == set(extracted)
    assert all(path.parent == destination for path in extracted.values())


def test_nport_extractor_rejects_an_existing_destination(tmp_path: Path) -> None:
    archive = write_sec_nport_archive(tmp_path / "nport.zip")
    destination = tmp_path / "existing"
    destination.mkdir()

    with pytest.raises(SourceVerificationError) as captured:
        verify_and_extract_nport(
            archive, destination, NportArchiveLimits()
        )

    assert captured.value.code == "SEC_NPORT_DESTINATION_EXISTS"


@pytest.mark.parametrize("unsafe_name", ("../escape.tsv", "nested/file.tsv"))
def test_nport_extractor_rejects_non_root_members(
    tmp_path: Path, unsafe_name: str
) -> None:
    archive = write_sec_nport_archive(
        tmp_path / "nport.zip",
        sec_nport_tsv_files() | {unsafe_name: b"unsafe"},
    )

    error = _capture_error(archive, tmp_path / "extracted")

    assert error.code == "SEC_NPORT_ARCHIVE_INVALID"
    assert not (tmp_path / "escape.tsv").exists()


def test_nport_extractor_rejects_a_symlink_member(tmp_path: Path) -> None:
    archive_path = write_sec_nport_archive(tmp_path / "nport.zip")
    with zipfile.ZipFile(archive_path, "a") as archive:
        info = zipfile.ZipInfo("unsafe-link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "SUBMISSION.tsv")

    error = _capture_error(archive_path, tmp_path / "extracted")

    assert error.code == "SEC_NPORT_ARCHIVE_INVALID"


def test_nport_extractor_rejects_duplicate_members(tmp_path: Path) -> None:
    archive_path = write_sec_nport_archive(tmp_path / "nport.zip")
    with zipfile.ZipFile(archive_path, "a") as archive:
        with pytest.warns(UserWarning):
            archive.writestr(
                "SUBMISSION.tsv", sec_nport_tsv_files()["SUBMISSION.tsv"]
            )

    error = _capture_error(archive_path, tmp_path / "extracted")

    assert error.code == "SEC_NPORT_ARCHIVE_INVALID"


def test_nport_extractor_rejects_a_missing_required_file(tmp_path: Path) -> None:
    files = sec_nport_tsv_files()
    files.pop("IDENTIFIERS.tsv")
    archive = write_sec_nport_archive(tmp_path / "nport.zip", files)

    error = _capture_error(archive, tmp_path / "extracted")

    assert error.code == "SEC_NPORT_FILES_MISSING"


def test_nport_extractor_rejects_an_unexpected_case_variant(tmp_path: Path) -> None:
    files = sec_nport_tsv_files() | {
        "submission.tsv": sec_nport_tsv_files()["SUBMISSION.tsv"]
    }
    archive = write_sec_nport_archive(tmp_path / "nport.zip", files)

    error = _capture_error(archive, tmp_path / "extracted")

    assert error.code == "SEC_NPORT_ARCHIVE_INVALID"


def test_nport_extractor_enforces_the_archive_byte_limit(tmp_path: Path) -> None:
    archive = write_sec_nport_archive(tmp_path / "nport.zip")
    limits = NportArchiveLimits(maximum_archive_bytes=archive.stat().st_size - 1)

    error = _capture_error(archive, tmp_path / "extracted", limits=limits)

    assert error.code == "SEC_NPORT_LIMIT_EXCEEDED"


def test_nport_extractor_enforces_the_member_count_limit(tmp_path: Path) -> None:
    archive = write_sec_nport_archive(
        tmp_path / "nport.zip",
        sec_nport_tsv_files() | {"README.txt": b"note"},
    )
    limits = NportArchiveLimits(maximum_members=5)

    error = _capture_error(archive, tmp_path / "extracted", limits=limits)

    assert error.code == "SEC_NPORT_LIMIT_EXCEEDED"


def test_nport_extractor_enforces_the_expanded_byte_limit(tmp_path: Path) -> None:
    files = sec_nport_tsv_files()
    archive = write_sec_nport_archive(tmp_path / "nport.zip", files)
    limits = NportArchiveLimits(
        maximum_expanded_bytes=sum(map(len, files.values())) - 1
    )

    error = _capture_error(archive, tmp_path / "extracted", limits=limits)

    assert error.code == "SEC_NPORT_LIMIT_EXCEEDED"


def test_nport_extractor_rejects_a_suspicious_compression_ratio(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files() | {"REPETITIVE.tsv": b"A" * 1_000_000}
    archive = write_sec_nport_archive(tmp_path / "nport.zip", files)

    error = _capture_error(archive, tmp_path / "extracted")

    assert error.code == "SEC_NPORT_LIMIT_EXCEEDED"


def test_nport_extractor_rejects_invalid_utf8(tmp_path: Path) -> None:
    files = sec_nport_tsv_files()
    files["IDENTIFIERS.tsv"] += b"\xff"
    archive = write_sec_nport_archive(tmp_path / "nport.zip", files)

    error = _capture_error(archive, tmp_path / "extracted")

    assert error.code == "SEC_NPORT_TSV_INVALID"


def test_nport_extractor_rejects_a_wrong_required_header(tmp_path: Path) -> None:
    files = sec_nport_tsv_files()
    files["SUBMISSION.tsv"] = files["SUBMISSION.tsv"].replace(
        b"FILING_DATE", b"WRONG_DATE", 1
    )
    archive = write_sec_nport_archive(tmp_path / "nport.zip", files)

    error = _capture_error(archive, tmp_path / "extracted")

    assert error.code == "SEC_NPORT_TSV_INVALID"


def test_nport_mapper_selects_latest_eligible_amendment_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    submission_fields, submissions = _decode_tsv(files["SUBMISSION.tsv"])
    registrant_fields, registrants = _decode_tsv(files["REGISTRANT.tsv"])
    fund_fields, funds = _decode_tsv(files["FUND_REPORTED_INFO.tsv"])
    selected_accession = submissions[0]["ACCESSION_NUMBER"]
    original_accession = "0000000000-26-000000"
    after_cutoff_accession = "0000000000-26-000002"
    submissions.extend(
        (
            dict(submissions[0])
            | {
                "ACCESSION_NUMBER": original_accession,
                "FILING_DATE": "15-MAY-2026",
                "SUB_TYPE": "NPORT-P",
            },
            dict(submissions[0])
            | {
                "ACCESSION_NUMBER": after_cutoff_accession,
                "FILING_DATE": "12-JUL-2026",
                "SUB_TYPE": "NPORT-P/A",
            },
        )
    )
    for accession in (original_accession, after_cutoff_accession):
        registrants.append(
            dict(registrants[0]) | {"ACCESSION_NUMBER": accession}
        )
        funds.append(dict(funds[0]) | {"ACCESSION_NUMBER": accession})
    files["SUBMISSION.tsv"] = _encode_tsv(submission_fields, submissions)
    files["REGISTRANT.tsv"] = _encode_tsv(registrant_fields, registrants)
    files["FUND_REPORTED_INFO.tsv"] = _encode_tsv(fund_fields, funds)

    mapped = _map_files(tmp_path, files)

    relations = _records(mapped, "relation.relation_record")
    holding = next(item for item in relations if item["predicate_id"] == "holdsSecurity")
    evidence = _records(mapped, "evidence.evidence_record")
    holding_evidence = next(
        item for item in evidence if item["predicate_id"] == "holdsSecurity"
    )
    assert holding["subject_id"] == "organizer-overseas-etf-1"
    assert holding_evidence["locator_record_key"] == (
        f"{selected_accession}:1001"
    )
    assert holding_evidence["applicable_date"] == date(2026, 3, 31)
    assert holding_evidence["published_at"] == datetime(
        2026, 6, 20, tzinfo=UTC
    )
    assert "sub_type=NPORT-P/A" in str(
        holding_evidence["normalized_value"]["value"]
    )
    scope = next(
        item for item in evidence if item["evidence_kind"] == "query_scope"
    )
    assert scope["locator_row"] == 2
    assert all(
        after_cutoff_accession not in str(item["locator_record_key"])
        for item in evidence
    )


def test_nport_mapper_excludes_an_official_filing_without_a_series_id(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    submission_fields, submissions = _decode_tsv(files["SUBMISSION.tsv"])
    registrant_fields, registrants = _decode_tsv(files["REGISTRANT.tsv"])
    fund_fields, funds = _decode_tsv(files["FUND_REPORTED_INFO.tsv"])
    unbound_accession = "0000000000-26-000099"
    submissions.append(
        dict(submissions[0]) | {"ACCESSION_NUMBER": unbound_accession}
    )
    registrants.append(
        dict(registrants[0]) | {"ACCESSION_NUMBER": unbound_accession}
    )
    funds.append(
        dict(funds[0])
        | {"ACCESSION_NUMBER": unbound_accession, "SERIES_ID": ""}
    )
    files["SUBMISSION.tsv"] = _encode_tsv(submission_fields, submissions)
    files["REGISTRANT.tsv"] = _encode_tsv(registrant_fields, registrants)
    files["FUND_REPORTED_INFO.tsv"] = _encode_tsv(fund_fields, funds)

    mapped = _map_files(tmp_path, files)

    assert len(mapped) == 1
    assert mapped[0].disposition == "accepted"


def test_nport_mapper_selects_the_latest_eligible_report_period(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    newer_accession = "0000000000-26-000004"
    for name in ("SUBMISSION.tsv", "REGISTRANT.tsv", "FUND_REPORTED_INFO.tsv"):
        fields, rows = _decode_tsv(files[name])
        newer = dict(rows[0]) | {"ACCESSION_NUMBER": newer_accession}
        if name == "SUBMISSION.tsv":
            newer |= {"FILING_DATE": "10-JUL-2026", "REPORT_DATE": "30-JUN-2026"}
        rows.append(newer)
        files[name] = _encode_tsv(fields, rows)
    holding_fields, holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    holdings.append(
        dict(holdings[0])
        | {
            "ACCESSION_NUMBER": newer_accession,
            "HOLDING_ID": "3001",
            "ISSUER_CUSIP": "",
        }
    )
    files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(
        holding_fields, holdings
    )
    identifier_fields, identifiers = _decode_tsv(files["IDENTIFIERS.tsv"])
    identifiers.append(
        dict(identifiers[0])
        | {
            "HOLDING_ID": "3001",
            "IDENTIFIERS_ID": "3",
            "IDENTIFIER_ISIN": "",
        }
    )
    files["IDENTIFIERS.tsv"] = _encode_tsv(identifier_fields, identifiers)

    mapped = _map_files(tmp_path, files)

    holding_evidence = next(
        item
        for item in _records(mapped, "evidence.evidence_record")
        if item["predicate_id"] == "holdsSecurity"
    )
    assert holding_evidence["locator_record_key"] == f"{newer_accession}:3001"
    assert holding_evidence["applicable_date"] == date(2026, 6, 30)


def test_nport_mapper_uses_exact_product_binding_and_never_series_identifier(
    tmp_path: Path,
) -> None:
    mapped = _map_files(
        tmp_path,
        bindings=(
            _binding(),
            _binding(product_id="unmatched-product", ticker="NOPE"),
        ),
    )

    holding_relations = tuple(
        item
        for item in _records(mapped, "relation.relation_record")
        if item["predicate_id"] == "holdsSecurity"
    )
    assert {item["subject_id"] for item in holding_relations} == {
        "organizer-overseas-etf-1"
    }
    identifiers = _records(mapped, "catalog.identifier")
    assert not any(
        item["scheme"] in {"SEC_SERIES_ID", "SEC_CLASS_ID"}
        for item in identifiers
    )
    unmatched = next(row for row in mapped if row.row_number == 2)
    assert unmatched.disposition == "limited"
    assert not unmatched.records_by_table["relation.relation_record"]
    scope = next(
        item
        for item in unmatched.records_by_table["evidence.evidence_record"]
        if item["evidence_kind"] == "query_scope"
    )
    assert scope["scope_completeness"] == "bounded_unknown"
    assert scope["normalized_value"]["value"] == "NOT_COVERED"


def test_nport_mapper_does_not_cross_assign_two_series_of_one_registrant(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    second_accession = "0000000000-26-000003"
    for name in ("SUBMISSION.tsv", "REGISTRANT.tsv", "FUND_REPORTED_INFO.tsv"):
        fields, rows = _decode_tsv(files[name])
        second = dict(rows[0]) | {"ACCESSION_NUMBER": second_accession}
        if name == "FUND_REPORTED_INFO.tsv":
            second |= {
                "SERIES_ID": "S000000002",
                "SERIES_NAME": "Second Synthetic ETF Series",
            }
        rows.append(second)
        files[name] = _encode_tsv(fields, rows)
    holding_fields, holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    holdings.append(
        dict(holdings[0])
        | {
            "ACCESSION_NUMBER": second_accession,
            "HOLDING_ID": "2001",
            "ISSUER_NAME": "Second Synthetic Issuer",
            "ISSUER_TITLE": "Second Synthetic Security",
            "ISSUER_CUSIP": "",
        }
    )
    files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(
        holding_fields, holdings
    )
    identifier_fields, identifiers = _decode_tsv(files["IDENTIFIERS.tsv"])
    identifiers.append(
        dict(identifiers[0])
        | {
            "HOLDING_ID": "2001",
            "IDENTIFIERS_ID": "2",
            "IDENTIFIER_ISIN": "",
            "IDENTIFIER_TICKER": "SYN2H",
        }
    )
    files["IDENTIFIERS.tsv"] = _encode_tsv(identifier_fields, identifiers)
    index = _series_index(
        (
            {
                "CIK": "0000123456",
                "Series ID": "S000000001",
                "Series Name": "Synthetic ETF Series",
                "Class ID": "C000000001",
                "Class Name": "Synthetic ETF Class",
                "Class Ticker": "SYNX",
            },
            {
                "CIK": "0000123456",
                "Series ID": "S000000002",
                "Series Name": "Second Synthetic ETF Series",
                "Class ID": "C000000002",
                "Class Name": "Second Synthetic ETF Class",
                "Class Ticker": "SYN2",
            },
        )
    )

    mapped = _map_files(tmp_path, files, series_index=index)

    holding_relations = tuple(
        item
        for item in _records(mapped, "relation.relation_record")
        if item["predicate_id"] == "holdsSecurity"
    )
    assert len(holding_relations) == 1
    assert holding_relations[0]["subject_id"] == "organizer-overseas-etf-1"
    assert not any(
        item["canonical_name"] == "Second Synthetic Security"
        for item in _records(mapped, "catalog.entity")
    )


def test_nport_mapper_keeps_duplicate_lots_and_does_not_promote_duplicate_ids(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    holding_fields, holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    identifier_fields, identifiers = _decode_tsv(files["IDENTIFIERS.tsv"])
    holdings.append(dict(holdings[0]) | {"HOLDING_ID": "1002", "BALANCE": "25"})
    identifiers.append(
        dict(identifiers[0])
        | {"HOLDING_ID": "1002", "IDENTIFIERS_ID": "2"}
    )
    files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(
        holding_fields, holdings
    )
    files["IDENTIFIERS.tsv"] = _encode_tsv(identifier_fields, identifiers)

    mapped = _map_files(tmp_path, files)

    holding_relations = tuple(
        item
        for item in _records(mapped, "relation.relation_record")
        if item["predicate_id"] == "holdsSecurity"
    )
    assert len(holding_relations) == 2
    assert len({item["relation_id"] for item in holding_relations}) == 2
    assert len({item["object_id"] for item in holding_relations}) == 2
    assert not any(
        item["scheme"] in {"ISIN", "CUSIP"}
        for item in _records(mapped, "catalog.identifier")
    )
    scope = next(
        item
        for item in _records(mapped, "evidence.evidence_record")
        if item["evidence_kind"] == "query_scope"
    )
    assert scope["normalized_value"]["value"] == "PARTIALLY_COVERED"
    assert scope["scope_completeness"] == "bounded_unknown"


def test_nport_mapper_bounds_each_output_row_to_250_holdings(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    holding_fields, holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    identifier_fields, identifiers = _decode_tsv(files["IDENTIFIERS.tsv"])
    holdings[0]["ISSUER_CUSIP"] = ""
    identifiers[0]["IDENTIFIER_ISIN"] = ""
    for offset in range(2, 252):
        holding_id = str(1000 + offset)
        holdings.append(
            dict(holdings[0])
            | {
                "HOLDING_ID": holding_id,
                "ISSUER_NAME": f"Synthetic Issuer {offset}",
                "ISSUER_TITLE": f"Synthetic Security {offset}",
            }
        )
        identifiers.append(
            dict(identifiers[0])
            | {
                "HOLDING_ID": holding_id,
                "IDENTIFIERS_ID": str(offset),
                "IDENTIFIER_TICKER": f"S{offset}",
            }
        )
    files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(
        holding_fields, holdings
    )
    files["IDENTIFIERS.tsv"] = _encode_tsv(identifier_fields, identifiers)

    mapped = _map_files(tmp_path, files)

    holding_counts = tuple(
        sum(
            record["predicate_id"] == "holdsSecurity"
            for record in row.records_by_table["relation.relation_record"]
        )
        for row in mapped
    )
    assert holding_counts == (250, 1)
    assert len(_records(mapped, "observation.observation_record")) == 251 * 6


def test_nport_mapper_does_not_retain_all_source_rows_in_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = sec_nport_tsv_files()
    _, base_holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    _, base_identifiers = _decode_tsv(files["IDENTIFIERS.tsv"])
    original_iter_tsv = sec_nport_module._iter_tsv

    class TrackedRow:
        active = 0

        def __init__(self, row_number: int, values: dict[str, str]) -> None:
            self.row_number = row_number
            self.values = values
            TrackedRow.active += 1

        def __del__(self) -> None:
            TrackedRow.active -= 1

    def tracked_rows(paths: object, name: str):
        if name == "FUND_REPORTED_HOLDING.tsv":
            for offset in range(1, 1_001):
                yield TrackedRow(
                    offset + 1,
                    dict(base_holdings[0])
                    | {
                        "HOLDING_ID": str(10_000 + offset),
                        "ISSUER_CUSIP": "",
                    },
                )
            return
        if name == "IDENTIFIERS.tsv":
            for offset in range(1, 1_001):
                yield TrackedRow(
                    offset + 1,
                    dict(base_identifiers[0])
                    | {
                        "HOLDING_ID": str(10_000 + offset),
                        "IDENTIFIERS_ID": str(offset),
                        "IDENTIFIER_ISIN": "",
                    },
                )
            return
        yield from original_iter_tsv(paths, name)

    monkeypatch.setattr(sec_nport_module, "_iter_tsv", tracked_rows)
    mapped = iter_eligible_nport_funds(
        _write_mapping_files(tmp_path / "nport-files", files),
        date(2026, 7, 11),
        manifest=_nport_manifest(files),
        series_class_index=_series_index(),
        product_bindings=(_binding(),),
    )

    first = next(mapped)
    gc.collect()

    assert first.records_by_table["relation.relation_record"]
    assert TrackedRow.active <= 2
    mapped.close()


def test_nport_mapper_redacts_a_temporary_join_store_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_detail = "PRIVATE-NPORT-TEMPORARY-PATH"

    def fail_connect(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise sec_nport_module.sqlite3.OperationalError(private_detail)

    monkeypatch.setattr(sec_nport_module.sqlite3, "connect", fail_connect)

    with pytest.raises(SourceVerificationError) as captured:
        _map_files(tmp_path)

    assert captured.value.code == "SEC_NPORT_JOIN_STORE_FAILED"
    assert captured.value.__cause__ is None
    assert private_detail not in str(captured.value)


def test_nport_mapper_promotes_unique_isin_but_ticker_is_alias_only(
    tmp_path: Path,
) -> None:
    mapped = _map_files(tmp_path)

    identifiers = _records(mapped, "catalog.identifier")
    assert any(
        item["scheme"] == "ISIN"
        and item["identifier_value"] == "US0000000002"
        for item in identifiers
    )
    assert not any(item["scheme"] == "TICKER" for item in identifiers)
    aliases = _records(mapped, "catalog.alias")
    assert any(item["alias_text"] == "SYNH" for item in aliases)
    security = _records(mapped, "catalog.security")[0]
    assert security["ticker_display"] == "SYNH"
    assert security["isin_display"] == "US0000000002"


def test_nport_mapper_uses_unique_valid_cusip_when_isin_is_absent(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    identifier_fields, identifiers = _decode_tsv(files["IDENTIFIERS.tsv"])
    identifiers[0]["IDENTIFIER_ISIN"] = ""
    files["IDENTIFIERS.tsv"] = _encode_tsv(identifier_fields, identifiers)

    mapped = _map_files(tmp_path, files)

    security_ids = tuple(
        item
        for item in _records(mapped, "catalog.identifier")
        if item["scheme"] == "CUSIP"
    )
    assert len(security_ids) == 1
    assert security_ids[0]["identifier_value"] == "000000000"
    scope = next(
        item
        for item in _records(mapped, "evidence.evidence_record")
        if item["evidence_kind"] == "query_scope"
    )
    assert scope["normalized_value"]["value"] == "COVERED"
    assert scope["scope_completeness"] == "closed_world"


def test_nport_mapper_preserves_percentage_points_and_all_holding_metrics(
    tmp_path: Path,
) -> None:
    mapped = _map_files(tmp_path)

    observations = _records(mapped, "observation.observation_record")
    values = {item["metric_id"]: item for item in observations}
    assert values["official_holding_weight_pct"]["numeric_value"] == Decimal(
        "4.25"
    )
    assert values["official_holding_weight_pct"]["unit"] == "percentage_point"
    assert values["official_holding_balance"]["numeric_value"] == Decimal("100")
    assert values["official_holding_currency_value"]["numeric_value"] == Decimal(
        "1000.25"
    )
    assert values["official_holding_currency"]["text_value"] == "USD"
    assert values["official_holding_asset_category"]["text_value"] == "EC"
    assert values["official_holding_investment_country"]["text_value"] == "US"
    assert {item["relation_id"] for item in observations} == {
        next(
            item["relation_id"]
            for item in _records(mapped, "relation.relation_record")
            if item["predicate_id"] == "holdsSecurity"
        )
    }


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    ((".25", Decimal("0.25")), ("-.25", Decimal("-0.25"))),
)
def test_nport_mapper_accepts_the_official_leading_decimal_point_format(
    tmp_path: Path,
    raw_value: str,
    expected: Decimal,
) -> None:
    files = sec_nport_tsv_files()
    fields, holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    holdings[0]["PERCENTAGE"] = raw_value
    files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(fields, holdings)

    mapped = _map_files(tmp_path, files)

    weight = next(
        item
        for item in _records(mapped, "observation.observation_record")
        if item["metric_id"] == "official_holding_weight_pct"
    )
    assert weight["numeric_value"] == expected
    assert len(_records(mapped, "evidence.evidence_observation_origin")) == 6
    observation_evidence = tuple(
        item
        for item in _records(mapped, "evidence.evidence_record")
        if item["evidence_kind"] == "observation"
    )
    assert {item["subject_id"] for item in observation_evidence} == {
        "organizer-overseas-etf-1"
    }


def test_nport_mapper_preserves_official_not_applicable_currency(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    fields, holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    holdings[0]["CURRENCY_CODE"] = "N/A"
    files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(fields, holdings)

    mapped = _map_files(tmp_path, files)

    relations = _records(mapped, "relation.relation_record")
    assert any(row["predicate_id"] == "holdsSecurity" for row in relations)
    observations = {
        row["metric_id"]: row
        for row in _records(mapped, "observation.observation_record")
    }
    assert observations["official_holding_currency"]["value_status"] == "unknown"
    assert observations["official_holding_currency"]["text_value"] is None
    assert observations["official_holding_currency"]["reason_code"] == (
        "SOURCE_VALUE_NOT_APPLICABLE"
    )
    assert observations["official_holding_currency_value"]["currency"] is None
    assert not mapped[0].issues
    assert mapped[0].disposition == "limited"


def test_nport_mapper_preserves_official_missing_numeric_values(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    fields, holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    for column in ("BALANCE", "CURRENCY_VALUE", "PERCENTAGE"):
        holdings[0][column] = ""
    files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(fields, holdings)

    mapped = _map_files(tmp_path, files)

    relations = _records(mapped, "relation.relation_record")
    assert any(row["predicate_id"] == "holdsSecurity" for row in relations)
    observations = {
        row["metric_id"]: row
        for row in _records(mapped, "observation.observation_record")
    }
    for metric_id in (
        "official_holding_balance",
        "official_holding_currency_value",
        "official_holding_weight_pct",
    ):
        assert observations[metric_id]["numeric_value"] is None
        assert observations[metric_id]["value_status"] == "unknown"
        assert observations[metric_id]["reason_code"] == "SOURCE_VALUE_MISSING"
    assert not mapped[0].issues
    assert mapped[0].disposition == "limited"


def test_nport_mapper_limits_a_malformed_holding_without_inventing_a_relation(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    holding_fields, holdings = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
    holdings[0]["PERCENTAGE"] = "4.25%"
    files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(
        holding_fields, holdings
    )

    mapped = _map_files(tmp_path, files)

    assert mapped[0].disposition == "limited"
    assert not any(
        item["predicate_id"] == "holdsSecurity"
        for item in _records(mapped, "relation.relation_record")
    )
    assert {issue.code for issue in mapped[0].issues} == {
        "SEC_NPORT_HOLDING_VALUE_INVALID"
    }
    scope = next(
        item
        for item in _records(mapped, "evidence.evidence_record")
        if item["evidence_kind"] == "query_scope"
    )
    assert scope["normalized_value"]["value"] == "PARTIALLY_COVERED"


@pytest.mark.parametrize(
    "mutation",
    ("duplicate_submission", "orphan_identifier", "duplicate_holding"),
)
def test_nport_mapper_rejects_structural_key_and_join_corruption(
    tmp_path: Path, mutation: str
) -> None:
    files = sec_nport_tsv_files()
    if mutation == "duplicate_submission":
        fields, rows = _decode_tsv(files["SUBMISSION.tsv"])
        rows.append(dict(rows[0]))
        files["SUBMISSION.tsv"] = _encode_tsv(fields, rows)
    elif mutation == "orphan_identifier":
        fields, rows = _decode_tsv(files["IDENTIFIERS.tsv"])
        rows.append(
            dict(rows[0]) | {"HOLDING_ID": "9999", "IDENTIFIERS_ID": "2"}
        )
        files["IDENTIFIERS.tsv"] = _encode_tsv(fields, rows)
    else:
        fields, rows = _decode_tsv(files["FUND_REPORTED_HOLDING.tsv"])
        rows.append(dict(rows[0]))
        files["FUND_REPORTED_HOLDING.tsv"] = _encode_tsv(fields, rows)

    with pytest.raises(SourceVerificationError) as captured:
        _map_files(tmp_path, files)

    assert captured.value.code in {
        "SEC_NPORT_DUPLICATE_KEY",
        "SEC_NPORT_REFERENTIAL_INTEGRITY",
    }
    assert captured.value.__cause__ is None


def test_nport_mapper_creates_exact_registrant_identity_and_evidence(
    tmp_path: Path,
) -> None:
    mapped = _map_files(tmp_path)

    manager = next(
        item
        for item in _records(mapped, "catalog.entity")
        if item["entity_type"] == "institution"
        and item["canonical_name"] == "Synthetic Registrant"
    )
    identifiers = _records(mapped, "catalog.identifier")
    assert any(
        item["entity_id"] == manager["entity_id"]
        and item["scheme"] == "SEC_CIK"
        and item["identifier_value"] == "123456"
        for item in identifiers
    )
    managed_by = next(
        item
        for item in _records(mapped, "relation.relation_record")
        if item["predicate_id"] == "managedBy"
    )
    assert managed_by["subject_id"] == "organizer-overseas-etf-1"
    assert managed_by["object_id"] == manager["entity_id"]


def test_nport_payload_matches_the_frozen_stage_02_writer_contract(
    tmp_path: Path,
) -> None:
    mapped = _map_files(tmp_path)
    writer = DatasetBuildWriter(cast(AsyncEngine, None))

    prepared = writer._prepare_records("synthetic-stage-03b", mapped)

    assert len(prepared["relation.relation_record"]) == 2
    assert len(prepared["observation.observation_record"]) == 6
    assert len(prepared["evidence.evidence_observation_origin"]) == 6
    assert len(prepared["evidence.evidence_relation_origin"]) == 3
    assert not any(
        item["evidence_kind"] == "document_span"
        for item in prepared["evidence.evidence_record"]
    )
