from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.ingestion.mapping.common import make_record_hash, stable_id
from financial_agent.ingestion.models import (
    IdentifierCandidate,
    MappedRow,
    MappingIssue,
    SourceSpec,
)
from financial_agent.ingestion.pipeline import (
    CUTOFF_DATE,
    OrganizerSourceValidationError,
    _preflight_sources,
    _database_component_hashes,
    build_organizer_dataset,
    write_preflighted_organizer_rows,
)
from financial_agent.ingestion.sources import SourceVerificationError
from financial_agent.ingestion.sources import sha256_path
from financial_agent.ingestion.writer import DatasetBuildWriter
from tests.fixtures.ingestion import write_data_workbook, write_schema_workbook


SOURCE_CODES = ("PRBD01N001", "PREF01N001", "PREF02N001", "PRFD01N001")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_new_ingestion_builds_use_the_current_cutoff() -> None:
    assert CUTOFF_DATE.isoformat() == "2026-08-24"


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
        identity_index: object,
    ) -> MappedRow:
        del row, context, identity_index
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


@pytest.mark.asyncio
async def test_official_writer_flushes_before_a_batch_exceeds_record_limit(
) -> None:
    from financial_agent.ingestion.official_pipeline import (
        _PreparedOfficialSource,
        _write_official_sources,
    )

    RecordingWriter.instances.clear()
    writer = RecordingWriter(object())
    rows = tuple(
        MappedRow(
            row_number=row_number,
            disposition="accepted",
            records_by_table={
                "observation.observation_record": ({},) * 60_000
            },
            issues=(),
        )
        for row_number in (1, 2)
    )
    source = _PreparedOfficialSource(
        source_code="SEC_NPORT_2026Q2",
        snapshot_count=1,
        row_factories=(lambda: iter(rows),),
    )

    result = await _write_official_sources(
        writer,
        dataset_version="bounded-official-write",
        sources=(source,),
        batch_size=1_000,
    )

    assert writer.batch_sizes == [1, 1]
    assert result.source_counts["SEC_NPORT_2026Q2"]["rows"] == 2


def _inputs(order: Sequence[str] = SOURCE_CODES):
    data_paths = {code: Path(f"/{code}.xlsx") for code in order}
    schema_paths = {code: Path(f"/{code}-schema.xlsx") for code in order}
    data_hashes = {code: code.encode().hex().ljust(64, "0")[:64] for code in order}
    schema_hashes = {
        code: code[::-1].encode().hex().ljust(64, "1")[:64] for code in order
    }
    return data_paths, schema_paths, data_hashes, schema_hashes


def test_preflight_exposes_the_manifest_used_for_its_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from financial_agent.contracts import canonical_sha256

    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 1 for code in SOURCE_CODES},
    )
    inputs = _inputs()

    preflight = _preflight_sources(
        data_paths=inputs[0],
        schema_paths=inputs[1],
        data_sha256=inputs[2],
        schema_sha256=inputs[3],
    )

    assert canonical_sha256(preflight.manifest) == preflight.manifest_hash


def test_preflight_freezes_one_cross_source_identity_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from financial_agent.ingestion import pipeline

    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 1 for code in SOURCE_CODES},
    )

    def candidates(source_code: str, rows: object):
        tuple(rows)  # type: ignore[arg-type]
        if source_code == "PREF01N001":
            return (
                IdentifierCandidate(
                    source_code=source_code,
                    row_number=2,
                    natural_key="KR7005930003",
                    entity_role="DomesticETF",
                    scheme="ISIN",
                    value="KR7005930003",
                ),
            )
        if source_code == "PRFD01N001":
            return (
                IdentifierCandidate(
                    source_code=source_code,
                    row_number=2,
                    natural_key="FUND-1",
                    entity_role="FundShareClass",
                    scheme="ISIN",
                    value="KR7005930003",
                ),
            )
        return ()

    monkeypatch.setattr(
        pipeline,
        "collect_organizer_identifier_candidates",
        candidates,
    )
    inputs = _inputs(tuple(reversed(SOURCE_CODES)))

    preflight = _preflight_sources(
        data_paths=inputs[0],
        schema_paths=inputs[1],
        data_sha256=inputs[2],
        schema_sha256=inputs[3],
    )

    resolution = preflight.identity_index.resolve("ISIN", "KR7005930003")
    assert resolution.status == "MATCHED"
    assert resolution.canonical_identity is not None
    assert resolution.canonical_identity.roles == frozenset(
        {"DomesticETF", "FundShareClass"}
    )


def test_preflight_aggregates_identity_failures_without_raw_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from financial_agent.ingestion import pipeline

    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 1 for code in SOURCE_CODES},
    )
    private_value = "KR7005930004"

    def candidates(source_code: str, rows: object):
        tuple(rows)  # type: ignore[arg-type]
        if source_code != "PREF01N001":
            return ()
        return (
            IdentifierCandidate(
                source_code=source_code,
                row_number=2,
                natural_key="PRIVATE-NATURAL-KEY",
                entity_role="DomesticETF",
                scheme="ISIN",
                value=private_value,
            ),
        )

    monkeypatch.setattr(
        pipeline,
        "collect_organizer_identifier_candidates",
        candidates,
    )
    inputs = _inputs()

    with pytest.raises(OrganizerSourceValidationError) as failure:
        _preflight_sources(
            data_paths=inputs[0],
            schema_paths=inputs[1],
            data_sha256=inputs[2],
            schema_sha256=inputs[3],
        )

    assert failure.value.issue_counts == {"IDENTITY_ISIN_INVALID": 1}
    assert private_value not in str(failure.value)
    assert "PRIVATE-NATURAL-KEY" not in str(failure.value)


@pytest.mark.asyncio
async def test_preflighted_write_reuses_an_existing_building_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingWriter.instances.clear()
    _configure_synthetic_pipeline(
        monkeypatch,
        row_counts={code: 2 for code in SOURCE_CODES},
    )
    inputs = _inputs()
    preflight = _preflight_sources(
        data_paths=inputs[0],
        schema_paths=inputs[1],
        data_sha256=inputs[2],
        schema_sha256=inputs[3],
    )
    writer = RecordingWriter(object())

    result = await write_preflighted_organizer_rows(
        writer,
        dataset_version="combined-building",
        data_paths=inputs[0],
        preflight=preflight,
        batch_size=1,
    )

    assert writer.created == []
    assert writer.batch_sizes[:4] == [4, 1, 1, 1]
    assert result.passed is True
    assert result.issue_counts == {}
    assert all(counts["rows"] == 2 for counts in result.source_counts.values())


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
        identity_index: object,
    ) -> MappedRow:
        del source, context, identity_index
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
        identity_index: object,
    ) -> MappedRow:
        del row, context, identity_index
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
    "command",
    (
        "capture-official",
        "validate-official",
        "load-stage03b",
        "verify-official-object-storage",
    ),
)
def test_cli_exposes_stage03b_commands_without_inline_secrets(
    command: str,
) -> None:
    from financial_agent.ingestion import cli

    arguments = cli._parser().parse_args([command])

    assert arguments.command == command


def test_cli_exposes_bounded_stage03b_capacity_probe_arguments() -> None:
    from financial_agent.ingestion import cli

    arguments = cli._parser().parse_args(
        ("measure-stage03b-capacity", "--full-holdings", "1300568")
    )

    assert arguments.command == "measure-stage03b-capacity"
    assert arguments.full_holdings == 1_300_568
    assert arguments.sample_products == 100
    assert arguments.current_storage_gib == 20


@pytest.mark.asyncio
async def test_capacity_probe_command_prints_only_aggregate_measurements(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    observed: dict[str, object] = {}
    monkeypatch.setenv(
        "FINANCIAL_AGENT_BUILD_DATABASE_URL",
        "postgresql://user:PRIVATE-PASSWORD@example.invalid/db",
    )
    monkeypatch.setenv(
        "FINANCIAL_AGENT_DATASET_VERSION",
        "PRIVATE-CAPACITY-DATASET",
    )
    monkeypatch.setattr(cli, "_source_inputs", lambda: _inputs())
    monkeypatch.setattr(
        cli,
        "_official_inputs",
        lambda: ((), Path("/official-objects")),
    )
    monkeypatch.setattr(
        cli,
        "create_async_engine",
        lambda *args, **kwargs: FakeEngine(),
    )

    async def build(engine: object, **kwargs: object) -> object:
        del engine
        observed.update(kwargs)
        return SimpleNamespace(
            sample_product_count=100,
            sample_holding_count=120_000,
            base_bytes=1_000,
            sampled_nport_bytes=2_000,
            dataset_status="building",
            active=False,
            estimate=SimpleNamespace(
                projected_total_bytes=30_000,
                safety_adjusted_bytes=39_000,
                recommended_storage_gib=50,
                additional_storage_gib=30,
            ),
        )

    monkeypatch.setattr(
        cli, "build_stage03b_capacity_probe", build, raising=False
    )
    arguments = cli._parser().parse_args(
        ("measure-stage03b-capacity", "--full-holdings", "1300568")
    )

    assert await cli._capacity_probe_command(arguments) == 0
    assert observed["dataset_version"] == "PRIVATE-CAPACITY-DATASET"
    assert observed["sample_product_count"] == 100
    assert observed["full_holding_count"] == 1_300_568
    output = capsys.readouterr().out
    assert output == (
        "CAPACITY_PROBE_OK sample_products=100 sample_holdings=120000 "
        "base_bytes=1000 sample_nport_bytes=2000 projected_bytes=30000 "
        "safety_bytes=39000 current_gib=20 recommended_gib=50 "
        "additional_gib=30 status=building active=0\n"
    )
    assert "PRIVATE-PASSWORD" not in output
    assert "PRIVATE-CAPACITY-DATASET" not in output


def test_capture_official_fails_closed_without_source_specific_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli

    monkeypatch.setenv("FINANCIAL_AGENT_KRX_API_KEY", "PRIVATE-KRX-KEY")

    assert cli.main(["capture-official"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "OFFICIAL_SOURCE_CONFIGURATION_MISSING"
    assert "PRIVATE-KRX-KEY" not in captured.err


@pytest.mark.asyncio
async def test_load_stage03b_uses_named_environment_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli

    class FakeEngine:
        async def dispose(self) -> None:
            return None

    observed: dict[str, object] = {}

    monkeypatch.setenv(
        "FINANCIAL_AGENT_BUILD_DATABASE_URL",
        "postgresql://user:PRIVATE-PASSWORD@example.invalid/db",
    )
    monkeypatch.setenv("FINANCIAL_AGENT_DATASET_VERSION", "combined-test")
    monkeypatch.setattr(cli, "_source_inputs", lambda: _inputs())
    monkeypatch.setattr(
        cli,
        "_official_inputs",
        lambda: ((), Path("/official-objects")),
    )
    monkeypatch.setattr(
        cli,
        "create_async_engine",
        lambda *args, **kwargs: FakeEngine(),
    )

    async def build(engine: object, **kwargs: object) -> object:
        observed.update(kwargs)
        return SimpleNamespace(
            passed=True,
            source_counts={
                "PREF01N001": {"rows": 1},
                "ECOS_731Y001": {"rows": 4},
            },
        )

    async def measure(engine: object, report: object) -> object:
        observed["acceptance_engine"] = engine
        observed["build_report"] = report
        return SimpleNamespace(
            reproducibility_hash="a" * 64,
            dataset_status="building",
            canonical_product_count=53_095,
            exact_reused_identity_count=217,
            aligned_ambiguous_pair_count=63,
            active=False,
        )

    def require_current(report: object) -> None:
        observed["acceptance_report"] = report

    monkeypatch.setattr(cli, "build_stage03b_dataset", build, raising=False)
    monkeypatch.setattr(
        cli, "measure_database_acceptance", measure, raising=False
    )
    monkeypatch.setattr(
        cli,
        "require_current_rebaseline_acceptance",
        require_current,
        raising=False,
    )

    assert await cli._load_stage03b_command() == 0
    assert observed["dataset_version"] == "combined-test"
    assert observed["build_report"].passed is True
    assert observed["acceptance_report"].reproducibility_hash == "a" * 64
    assert capsys.readouterr().out == (
        "STAGE03B_BUILD_OK sources=2 rows=5 status=building active=0 "
        f"acceptance={'a' * 64} products=53095 exact_reused=217 "
        "ambiguous_pairs=63\n"
    )


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
    assert "not official_data" in dockerfile
    assert "COPY data/" not in dockerfile
    for protected in ("data/", ".env.*", ".gstack/", ".agents/", ".codex/"):
        assert protected in dockerignore


@pytest.mark.parametrize(
    "required_copy",
    (
        "COPY .dockerignore ./",
        "COPY requirements/contracts.lock ./requirements/contracts.lock",
        "COPY docker/contracts.Dockerfile ./docker/contracts.Dockerfile",
    ),
)
def test_ingestion_container_copies_runtime_verification_inputs(
    required_copy: str,
) -> None:
    dockerfile = (PROJECT_ROOT / "docker" / "ingestion-check.Dockerfile").read_text(
        "utf-8"
    )

    assert required_copy in dockerfile


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
