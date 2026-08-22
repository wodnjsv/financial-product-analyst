from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.ingestion.mapping.common import make_record_hash, stable_id
from financial_agent.ingestion.models import MappedRow, MappingIssue, SourceSpec
from financial_agent.ingestion.pipeline import (
    CUTOFF_DATE,
    OrganizerSourceValidationError,
    _database_component_hashes,
    build_organizer_dataset,
)
from financial_agent.ingestion.sources import SourceVerificationError
from financial_agent.ingestion.sources import sha256_path
from financial_agent.ingestion.writer import DatasetBuildWriter
from tests.fixtures.ingestion import write_data_workbook, write_schema_workbook


SOURCE_CODES = ("PRBD01N001", "PREF01N001", "PREF02N001", "PRFD01N001")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _spec(source_code: str, row_count: int) -> SourceSpec:
    return SourceSpec(
        source_code=source_code,
        table_id=source_code,
        data_file_name=f"{source_code}.xlsx",
        data_sheet_name="datarows",
        schema_file_name=f"{source_code}-schema.xlsx",
        schema_sheet_name="schema",
        expected_columns=("key", "value"),
        expected_row_count=row_count,
        natural_key=("key",),
        parser_version="1",
        mapping_version="1",
    )


def _mapped_row(
    row_number: int,
    disposition: str = "accepted",
    *,
    issues: tuple[MappingIssue, ...] = (),
) -> MappedRow:
    return MappedRow(
        row_number=row_number,
        disposition=disposition,  # type: ignore[arg-type]
        records_by_table={},
        issues=issues,
    )


class RecordingWriter:
    instances: list["RecordingWriter"] = []

    def __init__(self, engine: object) -> None:
        self.engine = engine
        self.created: list[tuple[str, str]] = []
        self.batch_sizes: list[int] = []
        self.batches: list[tuple[MappedRow, ...]] = []
        type(self).instances.append(self)

    async def create_building_dataset(
        self,
        dataset_version: str,
        manifest_hash: str,
        cutoff_date: object,
    ) -> None:
        self.created.append((dataset_version, manifest_hash))

    async def write_rows(
        self,
        dataset_version: str,
        rows: Sequence[MappedRow],
    ) -> None:
        self.batch_sizes.append(len(rows))
        self.batches.append(tuple(rows))

    async def table_counts(self, dataset_version: str) -> Mapping[str, int]:
        return {"catalog.entity": sum(self.batch_sizes)}


def _configure_synthetic_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    row_counts: Mapping[str, int],
    dispositions: Mapping[str, Sequence[str]] | None = None,
    raw_value: str = "safe",
) -> None:
    from financial_agent.ingestion import pipeline

    specs = {code: _spec(code, row_counts.get(code, 0)) for code in SOURCE_CODES}
    monkeypatch.setattr(pipeline, "SOURCE_SPECS", specs)
    monkeypatch.setattr(pipeline, "DatasetBuildWriter", RecordingWriter)

    @contextmanager
    def snapshots(
        data_paths: Mapping[str, Path],
        schema_paths: Mapping[str, Path],
    ):
        yield data_paths, schema_paths

    monkeypatch.setattr(pipeline, "_snapshot_source_inputs", snapshots)
    monkeypatch.setattr(
        pipeline,
        "verify_local_source",
        lambda path, expected_sha256=None: expected_sha256 or "a" * 64,
    )
    monkeypatch.setattr(
        pipeline,
        "verify_schema_header",
        lambda path, spec: spec.expected_columns,
    )

    def rows(path: Path, spec: SourceSpec):
        for index in range(spec.expected_row_count):
            yield {"key": f"{spec.source_code}-{index}", "value": raw_value}

    monkeypatch.setattr(pipeline, "iter_workbook_rows", rows)
    monkeypatch.setattr(
        pipeline,
        "_prescan_source",
        lambda source_code, rows: tuple(rows) and None,
    )

    counters = {code: 0 for code in SOURCE_CODES}

    def map_source_row(
        source_code: str,
        row_number: int,
        row: Mapping[str, object],
        context: object,
    ) -> MappedRow:
        index = counters[source_code]
        counters[source_code] += 1
        disposition = (
            dispositions[source_code][index]
            if dispositions is not None and source_code in dispositions
            else "accepted"
        )
        return _mapped_row(row_number, disposition)

    monkeypatch.setattr(pipeline, "_map_source_row", map_source_row)
    monkeypatch.setattr(
        pipeline,
        "_database_component_hashes",
        lambda engine, dataset_version: _async_value(
            {"postgresql": "b" * 64, "evidence": "c" * 64}
        ),
    )


async def _async_value(value: object) -> object:
    return value


def _inputs(order: Sequence[str] = SOURCE_CODES):
    data_paths = {code: Path(f"/{code}.xlsx") for code in order}
    schema_paths = {code: Path(f"/{code}-schema.xlsx") for code in order}
    data_hashes = {code: code.encode().hex().ljust(64, "0")[:64] for code in order}
    schema_hashes = {
        code: code[::-1].encode().hex().ljust(64, "1")[:64] for code in order
    }
    return data_paths, schema_paths, data_hashes, schema_hashes


@pytest.mark.asyncio
async def test_manifest_and_report_are_independent_of_input_mapping_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingWriter.instances.clear()
    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 1 for code in SOURCE_CODES},
    )
    first_inputs = _inputs(SOURCE_CODES)
    second_inputs = _inputs(tuple(reversed(SOURCE_CODES)))

    first = await build_organizer_dataset(
        object(),
        dataset_version="organizer-a",
        data_paths=first_inputs[0],
        schema_paths=first_inputs[1],
        data_sha256=first_inputs[2],
        schema_sha256=first_inputs[3],
    )
    second = await build_organizer_dataset(
        object(),
        dataset_version="organizer-b",
        data_paths=second_inputs[0],
        schema_paths=second_inputs[1],
        data_sha256=second_inputs[2],
        schema_sha256=second_inputs[3],
    )

    assert first.dataset_manifest_hash == second.dataset_manifest_hash
    assert list(first.to_json_mapping()["source_counts"]) == list(SOURCE_CODES)


@pytest.mark.asyncio
async def test_every_source_row_has_exactly_one_disposition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingWriter.instances.clear()
    dispositions = {
        code: ("accepted", "limited", "quarantined") for code in SOURCE_CODES
    }
    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 3 for code in SOURCE_CODES},
        dispositions=dispositions,
    )
    inputs = _inputs()

    report = await build_organizer_dataset(
        object(),
        dataset_version="organizer-dispositions",
        data_paths=inputs[0],
        schema_paths=inputs[1],
        data_sha256=inputs[2],
        schema_sha256=inputs[3],
    )

    for counts in report.source_counts.values():
        assert counts == {
            "accepted": 1,
            "fatal": 0,
            "limited": 1,
            "quarantined": 1,
            "rows": 3,
        }
        assert counts["accepted"] + counts["limited"] + counts["quarantined"] == counts["rows"]


@pytest.mark.asyncio
async def test_preflight_aggregates_source_failures_before_any_dataset_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from financial_agent.ingestion import pipeline

    RecordingWriter.instances.clear()
    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 1 for code in SOURCE_CODES},
    )

    def verify(path: Path, expected_sha256: str | None = None) -> str:
        if path.name == "PRBD01N001.xlsx":
            raise SourceVerificationError(
                "SOURCE_CHECKSUM_MISMATCH", "must not escape"
            )
        return expected_sha256 or "a" * 64

    def schema(path: Path, spec: SourceSpec) -> tuple[str, ...]:
        if spec.source_code == "PREF01N001":
            raise SourceVerificationError("SOURCE_SCHEMA_MISMATCH", "raw header")
        return spec.expected_columns

    monkeypatch.setattr(pipeline, "verify_local_source", verify)
    monkeypatch.setattr(pipeline, "verify_schema_header", schema)
    inputs = _inputs()

    with pytest.raises(OrganizerSourceValidationError) as failure:
        await build_organizer_dataset(
            object(),
            dataset_version="organizer-invalid",
            data_paths=inputs[0],
            schema_paths=inputs[1],
            data_sha256=inputs[2],
            schema_sha256=inputs[3],
        )

    assert failure.value.code == "SOURCE_PREFLIGHT_FAILED"
    assert failure.value.issue_counts == {
        "SOURCE_CHECKSUM_MISMATCH": 1,
        "SOURCE_SCHEMA_MISMATCH": 1,
    }
    assert RecordingWriter.instances == []
    assert "raw header" not in str(failure.value)


@pytest.mark.asyncio
async def test_build_reads_an_immutable_snapshot_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from financial_agent.ingestion import pipeline

    source_code = "SYN0001"
    spec = SourceSpec(
        source_code=source_code,
        table_id=source_code,
        data_file_name="synthetic-data.xlsx",
        data_sheet_name="datarows",
        schema_file_name="synthetic-schema.xlsx",
        schema_sheet_name="Sheet1_Schema",
        expected_columns=("key", "value"),
        expected_row_count=1,
        natural_key=("key",),
        parser_version="1",
        mapping_version="1",
    )
    data_path = write_data_workbook(
        tmp_path / spec.data_file_name,
        headers=spec.expected_columns,
        rows=(("SYN-001", "VERIFIED"),),
    )
    schema_path = write_schema_workbook(
        tmp_path / spec.schema_file_name,
        headers=spec.expected_columns,
    )
    data_hash = sha256_path(data_path)
    schema_hash = sha256_path(schema_path)
    original_preflight = pipeline._preflight_sources
    observed_values: list[object] = []

    def preflight(**kwargs: object):
        result = original_preflight(**kwargs)  # type: ignore[arg-type]
        write_data_workbook(
            data_path,
            headers=spec.expected_columns,
            rows=(("SYN-001", "REPLACED"),),
        )
        return result

    def map_row(
        source: str,
        row_number: int,
        row: Mapping[str, object],
        context: object,
    ) -> MappedRow:
        observed_values.append(row["value"])
        return _mapped_row(row_number)

    RecordingWriter.instances.clear()
    monkeypatch.setattr(pipeline, "SOURCE_SPECS", {source_code: spec})
    monkeypatch.setattr(pipeline, "DatasetBuildWriter", RecordingWriter)
    monkeypatch.setattr(pipeline, "_preflight_sources", preflight)
    monkeypatch.setattr(pipeline, "_map_source_row", map_row)
    monkeypatch.setattr(
        pipeline,
        "_database_component_hashes",
        lambda engine, dataset_version: _async_value(
            {"postgresql": "b" * 64, "evidence": "c" * 64}
        ),
    )

    await build_organizer_dataset(
        object(),
        dataset_version="organizer-snapshot",
        data_paths={source_code: data_path},
        schema_paths={source_code: schema_path},
        data_sha256={source_code: data_hash},
        schema_sha256={source_code: schema_hash},
    )

    assert observed_values == ["VERIFIED"]


@pytest.mark.asyncio
async def test_pipeline_writes_source_rows_in_one_thousand_row_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingWriter.instances.clear()
    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={SOURCE_CODES[0]: 2_001},
    )
    inputs = _inputs()

    await build_organizer_dataset(
        object(),
        dataset_version="organizer-batches",
        data_paths=inputs[0],
        schema_paths=inputs[1],
        data_sha256=inputs[2],
        schema_sha256=inputs[3],
    )

    assert RecordingWriter.instances[0].batch_sizes[1:] == [1_000, 1_000, 1]


@pytest.mark.asyncio
async def test_verified_source_records_are_written_before_mapped_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingWriter.instances.clear()
    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 1 for code in SOURCE_CODES},
    )
    inputs = _inputs()

    await build_organizer_dataset(
        object(),
        dataset_version="organizer-sources",
        data_paths=inputs[0],
        schema_paths=inputs[1],
        data_sha256=inputs[2],
        schema_sha256=inputs[3],
    )

    foundation_batch = RecordingWriter.instances[0].batches[0]
    assert len(foundation_batch) == 4
    assert all(row.row_number == 0 for row in foundation_batch)
    source_records = [
        row.records_by_table["evidence.source_record"][0]
        for row in foundation_batch
    ]
    assert {record["content_checksum"] for record in source_records} == set(
        inputs[2].values()
    )
    assert all(record["authority_tier"] == "organizer" for record in source_records)


@pytest.mark.asyncio
async def test_fatal_mapping_issue_returns_failed_report_without_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from financial_agent.ingestion import pipeline

    RecordingWriter.instances.clear()
    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 1 for code in SOURCE_CODES},
    )

    def fatal_mapper(
        source_code: str,
        row_number: int,
        row: Mapping[str, object],
        context: object,
    ) -> MappedRow:
        issue = MappingIssue(
            source_code=source_code,
            row_number=row_number,
            column="value",
            code="AFTER_CUTOFF_SOURCE_VALUE",
            severity="fatal",
        )
        return _mapped_row(row_number, "quarantined", issues=(issue,))

    monkeypatch.setattr(pipeline, "_map_source_row", fatal_mapper)
    inputs = _inputs()

    report = await build_organizer_dataset(
        object(),
        dataset_version="organizer-fatal",
        data_paths=inputs[0],
        schema_paths=inputs[1],
        data_sha256=inputs[2],
        schema_sha256=inputs[3],
    )

    assert report.passed is False
    assert report.issue_counts == {"AFTER_CUTOFF_SOURCE_VALUE": 4}
    assert all(counts["fatal"] == 1 for counts in report.source_counts.values())
    assert not hasattr(RecordingWriter.instances[0], "activate_dataset")


@pytest.mark.asyncio
async def test_build_report_never_contains_raw_source_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingWriter.instances.clear()
    raw_value = "PRIVATE-RAW-VALUE-DO-NOT-REPORT"
    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 1 for code in SOURCE_CODES},
        raw_value=raw_value,
    )
    inputs = _inputs()

    report = await build_organizer_dataset(
        object(),
        dataset_version="organizer-redaction",
        data_paths=inputs[0],
        schema_paths=inputs[1],
        data_sha256=inputs[2],
        schema_sha256=inputs[3],
    )

    assert raw_value not in json.dumps(report.to_json_mapping(), ensure_ascii=False)


def test_cli_reports_missing_runtime_configuration_without_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli

    for name in tuple(os.environ):
        if name.startswith("FINANCIAL_AGENT_"):
            monkeypatch.delenv(name, raising=False)

    assert cli.main(["validate"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "CONFIGURATION_MISSING"


@pytest.mark.asyncio
async def test_validate_command_reads_only_from_an_immutable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli

    original_data = {"SYN0001": Path("/original/data.xlsx")}
    original_schema = {"SYN0001": Path("/original/schema.xlsx")}
    snapshot_data = {"SYN0001": Path("/snapshot/data.xlsx")}
    snapshot_schema = {"SYN0001": Path("/snapshot/schema.xlsx")}
    observed: dict[str, Mapping[str, Path]] = {}

    monkeypatch.setattr(
        cli,
        "_source_inputs",
        lambda: (
            original_data,
            original_schema,
            {"SYN0001": "a" * 64},
            {"SYN0001": "b" * 64},
        ),
    )

    @contextmanager
    def snapshots(
        data_paths: Mapping[str, Path],
        schema_paths: Mapping[str, Path],
    ):
        assert data_paths is original_data
        assert schema_paths is original_schema
        yield snapshot_data, snapshot_schema

    monkeypatch.setattr(cli, "_snapshot_source_inputs", snapshots, raising=False)

    def preflight(**kwargs: object) -> None:
        observed["data"] = kwargs["data_paths"]  # type: ignore[assignment]
        observed["schema"] = kwargs["schema_paths"]  # type: ignore[assignment]

    monkeypatch.setattr(cli, "_preflight_sources", preflight)

    assert await cli._validate_command() == 0
    assert observed == {"data": snapshot_data, "schema": snapshot_schema}
    assert capsys.readouterr().out == "SOURCE_VALIDATION_OK sources=4 rows=145393\n"


def test_cli_suppresses_unexpected_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli

    async def fail() -> None:
        raise RuntimeError("password=PRIVATE-CREDENTIAL")

    monkeypatch.setattr(cli, "_validate_command", fail)

    assert cli.main(["validate"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "INGESTION_FAILED"
    assert "PRIVATE-CREDENTIAL" not in captured.err


def test_cli_preserves_stable_dataset_writer_error_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli
    from financial_agent.ingestion.writer import DatasetBuildConflict

    async def conflict() -> None:
        raise DatasetBuildConflict("catalog.entity")

    monkeypatch.setattr(cli, "_load_command", conflict)

    assert cli.main(["load"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "BUILD_PAYLOAD_CONFLICT"
    assert "catalog.entity" not in captured.err


def test_cli_parser_has_no_database_or_credential_arguments() -> None:
    from financial_agent.ingestion import cli

    parser = cli._parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }

    assert "--database-url" not in option_strings
    assert "--access-key" not in option_strings
    assert "--secret-key" not in option_strings


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://object.example.invalid",
        "https://user:PRIVATE-PASSWORD@object.example.invalid",
        "https://object.example.invalid?token=PRIVATE-TOKEN",
        "https://object.example.invalid#PRIVATE-FRAGMENT",
    ),
)
def test_object_storage_endpoint_rejects_unsafe_urls(endpoint: str) -> None:
    from financial_agent.ingestion import cli

    with pytest.raises(RuntimeError) as failure:
        cli._validated_object_storage_endpoint(endpoint)

    assert getattr(failure.value, "code", None) == (
        "OBJECT_STORAGE_ENDPOINT_INVALID"
    )
    assert endpoint not in str(failure.value)


def test_cli_rejects_unknown_arguments_without_echoing_their_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli

    secret_value = "postgresql://user:PRIVATE-PASSWORD@example.invalid/db"

    assert cli.main(["load", "--database-url", secret_value]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "CLI_ARGUMENT_INVALID"
    assert secret_value not in captured.err


def test_ingestion_container_is_linux_amd64_and_excludes_external_data() -> None:
    dockerfile = (PROJECT_ROOT / "docker" / "ingestion-check.Dockerfile").read_text(
        "utf-8"
    )
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text("utf-8")

    assert "FROM --platform=linux/amd64 python:3.12-slim" in dockerfile
    assert "PIP_CONSTRAINT=/app/requirements/ingestion.lock" in dockerfile
    assert 'python -m pip install ".[dev,storage,ingestion]"' in dockerfile
    assert "not postgres" in dockerfile
    assert "not organizer_data" in dockerfile
    assert "not object_storage" in dockerfile
    assert "COPY data/" not in dockerfile
    for protected in ("data/", ".env.*", ".gstack/", ".agents/", ".codex/"):
        assert protected in dockerignore


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_database_component_hashes_are_stable_and_change_with_catalog_data(
    ingestion_build_engine: AsyncEngine,
) -> None:
    writer = DatasetBuildWriter(ingestion_build_engine)
    entity_id = stable_id("product", "hash-test", "same-product")

    async def write_dataset(dataset_version: str, name: str) -> None:
        payload = {
            "entity_id": entity_id,
            "entity_type": "product",
            "canonical_name": name,
            "normalized_name": name,
        }
        record = dict(payload)
        record["record_hash"] = make_record_hash(payload)
        await writer.create_building_dataset(
            dataset_version,
            "a" * 64,
            CUTOFF_DATE,
        )
        await writer.write_rows(
            dataset_version,
            (
                MappedRow(
                    row_number=2,
                    disposition="accepted",
                    records_by_table={"catalog.entity": (record,)},
                    issues=(),
                ),
            ),
        )

    first_dataset = f"component-hash-a-{uuid4().hex}"
    identical_dataset = f"component-hash-identical-{uuid4().hex}"
    changed_dataset = f"component-hash-b-{uuid4().hex}"
    await write_dataset(first_dataset, "Alpha Product")
    first = await _database_component_hashes(
        ingestion_build_engine,
        first_dataset,
    )
    repeated = await _database_component_hashes(
        ingestion_build_engine,
        first_dataset,
    )
    await write_dataset(identical_dataset, "Alpha Product")
    identical = await _database_component_hashes(
        ingestion_build_engine,
        identical_dataset,
    )
    await write_dataset(changed_dataset, "Changed Product")
    changed = await _database_component_hashes(
        ingestion_build_engine,
        changed_dataset,
    )

    assert first == repeated
    assert first == identical
    assert first["postgresql"] != changed["postgresql"]
    assert first["evidence"] == changed["evidence"]
