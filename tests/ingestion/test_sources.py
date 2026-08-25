from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from financial_agent.ingestion import (
    BuildReport,
    MappedRow,
    MappingIssue,
    SourceSpec,
    SourceVerificationError,
    download_verified_object,
    iter_workbook_rows,
    manifest_hash,
    sha256_path,
    verify_local_source,
    verify_schema_header,
)
from financial_agent.ingestion.pipeline import SOURCE_SPECS
from tests.fixtures.ingestion import write_data_workbook, write_schema_workbook


EXPECTED_COLUMNS = ("PD_NO", "ZERO_VALUE", "BLANK_VALUE", "TEXT_NULL")

EXPECTED_CURRENT_SOURCE_CONTRACTS = {
    "PRBD01N001": {
        "data_file_name": "prbd01n001_data.xlsx",
        "schema_file_name": "prbd01n001_schema.xlsx",
        "natural_key": ("pd_no", "pd_exg_mkt", "info_base_dt", "info_seq"),
        "row_count": 21_882,
        "field_count": 58,
    },
    "PREF01N001": {
        "data_file_name": "pref01n001_data.xlsx",
        "schema_file_name": "pref01n001_schema.xlsx",
        "natural_key": ("pd_itm_no",),
        "row_count": 1_780,
        "field_count": 98,
    },
    "PREF02N001": {
        "data_file_name": "pref02n001_data.xlsx",
        "schema_file_name": "pref02n001_schema.xlsx",
        "natural_key": ("pd_itm_no",),
        "row_count": 6_037,
        "field_count": 49,
    },
    "PRFD01N001": {
        "data_file_name": "prfd01n001_data.xlsx",
        "schema_file_name": "prfd01n001_schema.xlsx",
        "natural_key": ("itm_no",),
        "row_count": 23_676,
        "field_count": 75,
    },
}


def test_current_organizer_source_contracts_match_the_replacement_files() -> None:
    assert set(SOURCE_SPECS) == set(EXPECTED_CURRENT_SOURCE_CONTRACTS)
    for source_code, expected in EXPECTED_CURRENT_SOURCE_CONTRACTS.items():
        spec = SOURCE_SPECS[source_code]
        assert spec.data_file_name == expected["data_file_name"]
        assert spec.data_sheet_name == "data"
        assert spec.schema_file_name == expected["schema_file_name"]
        assert spec.schema_sheet_name == "schema"
        assert spec.natural_key == expected["natural_key"]
        assert spec.expected_row_count == expected["row_count"]
        assert len(spec.expected_columns) == expected["field_count"]


def source_spec(*, expected_row_count: int = 1) -> SourceSpec:
    return SourceSpec(
        source_code="organizer",
        table_id="SYN01N001",
        data_file_name="synthetic_datarows.xlsx",
        data_sheet_name="datarows",
        schema_file_name="synthetic_schema.xlsx",
        schema_sheet_name="Sheet1_Schema",
        expected_columns=EXPECTED_COLUMNS,
        expected_row_count=expected_row_count,
        natural_key=("PD_NO",),
        parser_version="1",
        mapping_version="1",
    )


def test_approved_models_preserve_exact_task_2_payloads() -> None:
    issue = MappingIssue(
        source_code="organizer",
        row_number=2,
        column="PD_NO",
        code="MISSING_NATURAL_KEY",
        severity="quarantined",
    )
    mapped = MappedRow(
        row_number=2,
        disposition="quarantined",
        records_by_table={"catalog.entity": ()},
        issues=(issue,),
    )
    report = BuildReport(
        dataset_version="stage03a-test",
        cutoff_date=date(2026, 7, 11),
        dataset_manifest_hash="a" * 64,
        source_counts={
            "PREF01N001": {"limited": 1, "accepted": 2},
            "PRBD01N001": {"quarantined": 1},
        },
        table_counts={"observation.observation_record": 3, "catalog.entity": 2},
        issue_counts={"MISSING_NATURAL_KEY": 1},
        component_hashes={"postgresql": "b" * 64, "evidence": "c" * 64},
        passed=False,
    )

    assert mapped.issues == (issue,)
    assert report.to_json_mapping() == {
        "component_hashes": {"evidence": "c" * 64, "postgresql": "b" * 64},
        "cutoff_date": "2026-07-11",
        "dataset_manifest_hash": "a" * 64,
        "dataset_version": "stage03a-test",
        "issue_counts": {"MISSING_NATURAL_KEY": 1},
        "passed": False,
        "source_counts": {
            "PRBD01N001": {"quarantined": 1},
            "PREF01N001": {"accepted": 2, "limited": 1},
        },
        "table_counts": {"catalog.entity": 2, "observation.observation_record": 3},
    }
    assert (
        manifest_hash(report.to_json_mapping())
        == "018e6933b827a17c8f24e10f415c2a01ba05604ceda8e543b23b74231e5f1ab9"
    )


def test_schema_reader_requires_the_exact_ordered_columns(tmp_path: Path) -> None:
    schema_path = write_schema_workbook(
        tmp_path / "schema.xlsx", headers=EXPECTED_COLUMNS
    )

    assert verify_schema_header(schema_path, source_spec()) == EXPECTED_COLUMNS


def test_schema_reader_rejects_header_whitespace_change(tmp_path: Path) -> None:
    schema_path = write_schema_workbook(
        tmp_path / "schema-whitespace.xlsx",
        headers=("PD_NO ", "ZERO_VALUE", "BLANK_VALUE", "TEXT_NULL"),
    )

    with pytest.raises(SourceVerificationError) as captured:
        verify_schema_header(schema_path, source_spec())

    assert captured.value.code == "SOURCE_SCHEMA_MISMATCH"


def test_reader_rejects_changed_header(tmp_path: Path) -> None:
    path = write_data_workbook(
        tmp_path / "changed.xlsx",
        headers=("PD_NO", "CHANGED", "BLANK_VALUE", "TEXT_NULL"),
        rows=(("SYN-BOND-001", 0, None, "NULL"),),
    )

    with pytest.raises(SourceVerificationError) as captured:
        list(iter_workbook_rows(path, source_spec()))

    assert captured.value.code == "SOURCE_HEADER_MISMATCH"
    assert str(captured.value) == "workbook header differs from the approved schema"


def test_reader_rejects_header_whitespace_change(tmp_path: Path) -> None:
    path = write_data_workbook(
        tmp_path / "header-whitespace.xlsx",
        headers=("PD_NO ", "ZERO_VALUE", "BLANK_VALUE", "TEXT_NULL"),
        rows=(("SYN-BOND-001", 0, None, "NULL"),),
    )

    with pytest.raises(SourceVerificationError) as captured:
        list(iter_workbook_rows(path, source_spec()))

    assert captured.value.code == "SOURCE_HEADER_MISMATCH"


def test_reader_rejects_unexpected_row_count(tmp_path: Path) -> None:
    path = write_data_workbook(
        tmp_path / "row-count.xlsx",
        headers=EXPECTED_COLUMNS,
        rows=(
            ("SYN-BOND-001", 0, None, "NULL"),
            ("SYN-BOND-002", 1, "", "value"),
        ),
    )

    with pytest.raises(SourceVerificationError) as captured:
        list(iter_workbook_rows(path, source_spec(expected_row_count=1)))

    assert captured.value.code == "SOURCE_ROW_COUNT_MISMATCH"
    assert str(captured.value) == "workbook row count differs from the approved source"


def test_reader_preserves_zero_blank_and_string_null(tmp_path: Path) -> None:
    path = write_data_workbook(
        tmp_path / "values.xlsx",
        headers=EXPECTED_COLUMNS,
        rows=(("SYN-BOND-001", 0, None, "NULL"),),
    )

    assert list(iter_workbook_rows(path, source_spec())) == [
        {
            "PD_NO": "SYN-BOND-001",
            "ZERO_VALUE": 0,
            "BLANK_VALUE": None,
            "TEXT_NULL": "NULL",
        }
    ]


def test_reader_restores_trailing_blank_cells_omitted_by_read_only_xlsx(
    tmp_path: Path,
) -> None:
    path = write_data_workbook(
        tmp_path / "trailing-blanks.xlsx",
        headers=EXPECTED_COLUMNS,
        rows=(("SYN-BOND-001", 0),),
    )

    assert list(iter_workbook_rows(path, source_spec())) == [
        {
            "PD_NO": "SYN-BOND-001",
            "ZERO_VALUE": 0,
            "BLANK_VALUE": None,
            "TEXT_NULL": None,
        }
    ]


def test_local_checksum_must_match_expected(tmp_path: Path) -> None:
    path = tmp_path / "source.xlsx"
    path.write_bytes(b"synthetic workbook bytes")

    actual = sha256_path(path)
    assert verify_local_source(path, expected_sha256=actual) == actual

    with pytest.raises(SourceVerificationError) as captured:
        verify_local_source(path, expected_sha256="0" * 64)

    assert captured.value.code == "SOURCE_CHECKSUM_MISMATCH"
    assert str(captured.value) == "local source checksum differs from expected"


class FakeObjectClient:
    def __init__(self, payload: bytes, *, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def head_object(self, **_: object) -> dict[str, str]:
        return {"ETag": '"' + "0" * 64 + '"'}

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        del bucket, key
        if self.error is not None:
            raise self.error
        Path(destination).write_bytes(self.payload)


def test_object_download_is_rehashed_instead_of_trusting_etag(tmp_path: Path) -> None:
    destination = tmp_path / "download.xlsx"
    destination.write_bytes(b"previous verified bytes")
    client = FakeObjectClient(b"corrupted object bytes")

    with pytest.raises(SourceVerificationError) as captured:
        download_verified_object(
            client,
            bucket="private-bucket",
            key="organizer/2026-08-24/source.xlsx",
            expected_sha256="0" * 64,
            destination=destination,
        )

    assert captured.value.code == "OBJECT_CHECKSUM_MISMATCH"
    assert str(captured.value) == "downloaded object checksum differs from expected"
    assert destination.read_bytes() == b"previous verified bytes"


def test_source_errors_do_not_include_credentials_or_cell_values(
    tmp_path: Path,
) -> None:
    secret = "SECRET-CELL-VALUE"
    credential = "AKIA_SYNTHETIC:password"
    client = FakeObjectClient(
        b"",
        error=RuntimeError(f"https://{credential}@endpoint.invalid/{secret}"),
    )

    with pytest.raises(SourceVerificationError) as captured:
        download_verified_object(
            client,
            bucket="private-bucket",
            key="organizer/2026-08-24/source.xlsx",
            expected_sha256="0" * 64,
            destination=tmp_path / "download.xlsx",
        )

    assert captured.value.code == "OBJECT_DOWNLOAD_FAILED"
    assert str(captured.value) == "object download failed"
    assert credential not in str(captured.value)
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


def test_object_destination_errors_are_sanitized(tmp_path: Path) -> None:
    payload = b"verified synthetic bytes"
    destination = tmp_path / "existing-directory"
    destination.mkdir()

    with pytest.raises(SourceVerificationError) as captured:
        download_verified_object(
            FakeObjectClient(payload),
            bucket="private-bucket",
            key="organizer/2026-08-24/source.xlsx",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            destination=destination,
        )

    assert captured.value.code == "OBJECT_DOWNLOAD_FAILED"
    assert str(captured.value) == "object download failed"
    assert captured.value.__cause__ is None
    assert destination.is_dir()
