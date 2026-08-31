from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from financial_agent.ingestion.cli import (
    IngestionArgumentError,
    _DartCorpusRunReport,
    _load_dart_corpus_configuration,
    _parser,
    _write_dart_corpus_report,
)


def _arguments(limit: str | None = None):
    values = ["ingest-dart-corpus"]
    if limit is not None:
        values.extend(("--limit", limit))
    return _parser().parse_args(values)


def _environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    key_file = tmp_path / "api.txt"
    key_file.write_text(
        "export FINANCIAL_AGENT_KRX_API_KEY=krx-secret\n"
        "OPEN DART = dart-secret-value\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "publisher-aliases.json"
    mapping.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "aliases": [
                    {
                        "manager_entity_id": "institution:manager-one",
                        "corp_code": "00123456",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    run_root = tmp_path / "dart-run"
    output = tmp_path / "dart-report.json"
    monkeypatch.setenv("FINANCIAL_AGENT_DART_API_KEY_FILE", str(key_file))
    monkeypatch.setenv(
        "FINANCIAL_AGENT_BUILD_DATABASE_URL",
        "postgresql+psycopg://owner:password@127.0.0.1:55441/database",
    )
    monkeypatch.setenv("FINANCIAL_AGENT_DATASET_VERSION", "documents-building-v1")
    monkeypatch.setenv("FINANCIAL_AGENT_DART_TEMP_ROOT", str(run_root))
    monkeypatch.setenv(
        "FINANCIAL_AGENT_DART_PUBLISHER_MAPPING", str(mapping)
    )
    monkeypatch.setenv("FINANCIAL_AGENT_DART_REPORT", str(output))
    return key_file, mapping, output


def test_repository_ignores_the_user_api_file() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    assert "api.txt" in {
        line.strip()
        for line in (repository_root / ".gitignore").read_text(
            encoding="utf-8"
        ).splitlines()
    }


def test_configuration_reads_only_the_named_dart_key_and_strict_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, output = _environment(monkeypatch, tmp_path)

    configuration = _load_dart_corpus_configuration(_arguments("10"))

    assert configuration.dart_api_key == "dart-secret-value"
    assert configuration.limit == 10
    assert configuration.publisher_aliases == {
        "institution:manager-one": "00123456"
    }
    assert configuration.report_path == output


def test_configuration_does_not_require_a_manual_publisher_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch, tmp_path)
    monkeypatch.delenv("FINANCIAL_AGENT_DART_PUBLISHER_MAPPING")

    configuration = _load_dart_corpus_configuration(_arguments("1"))

    assert configuration.publisher_aliases == {}


@pytest.mark.parametrize("limit", ("0", "-1", "not-a-number"))
def test_configuration_rejects_invalid_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
) -> None:
    _environment(monkeypatch, tmp_path)

    with pytest.raises(IngestionArgumentError):
        _load_dart_corpus_configuration(_arguments(limit))


def test_configuration_rejects_unknown_mapping_fields_and_duplicate_dart_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file, mapping, _ = _environment(monkeypatch, tmp_path)
    mapping.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "aliases": [],
                "unexpected": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(IngestionArgumentError):
        _load_dart_corpus_configuration(_arguments())

    mapping.write_text(
        json.dumps({"schema_version": "1.0", "aliases": []}),
        encoding="utf-8",
    )
    key_file.write_text(
        "OPEN DART=first-secret\nFINANCIAL_AGENT_DART_API_KEY=second-secret\n",
        encoding="utf-8",
    )
    with pytest.raises(IngestionArgumentError):
        _load_dart_corpus_configuration(_arguments())


def test_configuration_rejects_paths_inside_the_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch, tmp_path)
    repository_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv(
        "FINANCIAL_AGENT_DART_TEMP_ROOT",
        str(repository_root / "tmp" / "dart-run"),
    )

    with pytest.raises(IngestionArgumentError):
        _load_dart_corpus_configuration(_arguments())


def test_report_contains_only_sanitized_counts_ids_hashes_and_reason_codes(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "report.json"
    report = _DartCorpusRunReport(
        schema_version="1.0",
        generated_at=datetime(2026, 8, 31, tzinfo=UTC),
        cutoff_date=date(2026, 8, 24),
        dataset_version="documents-building-v1",
        inventory_hash="a" * 64,
        organizer_product_count=25_239,
        organizer_target_count=15_569,
        selected_target_count=1,
        publisher_binding_count=1,
        publisher_failure_count=0,
        requested_publisher_count=1,
        discovered_document_count=1,
        indexed_document_ids=("dart:20260716000161:full-prospectus",),
        indexed_target_ids=("domestic_etf:product-one",),
        failed_targets=(("public_fund:product-two", "document_not_found"),),
        rejected_dart_filing_count=3,
        captured_bytes=1_024,
        chunk_count=6,
        provisional_selected_token_count=2_400,
        token_counter_identity="WhitespaceTokenCounter",
        deleted_pdf_count=1,
        deleted_bytes=1_024,
        quarantined_pdf_count=0,
        quarantined_bytes=0,
    )

    report_hash = _write_dart_corpus_report(report, destination)
    payload = destination.read_text(encoding="utf-8")

    assert len(report_hash) == 64
    assert "SYNTHETIC-SECRET" not in payload
    assert "추종지수의 변동" not in payload
    assert json.loads(payload)["inventory_hash"] == "a" * 64
