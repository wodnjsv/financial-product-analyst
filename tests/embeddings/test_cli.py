from __future__ import annotations

import json
from pathlib import Path

import pytest

from financial_agent.embeddings import cli
from financial_agent.embeddings.cli import (
    EmbeddingConfigurationError,
    load_configuration,
    main,
    parse_args,
    read_ncp_api_key,
    write_report,
)


def _environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    key_file = tmp_path / "api.txt"
    key_file.write_text(
        "OPEN_DART=dart-secret\nNCP_CLOVA_STUDIO_API=ncp-secret\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    monkeypatch.setenv(
        "FINANCIAL_AGENT_BUILD_DATABASE_URL",
        "postgresql+psycopg://user:password@127.0.0.1:55437/database",
    )
    monkeypatch.setenv(
        "FINANCIAL_AGENT_DATASET_VERSION",
        "organizer-dart-2026-08-24-v2",
    )
    monkeypatch.setenv("FINANCIAL_AGENT_NCP_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("FINANCIAL_AGENT_EMBEDDING_REPORT", str(report))
    return key_file, report


def test_configuration_reads_only_the_exact_named_ncp_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, report = _environment(tmp_path, monkeypatch)

    configuration = load_configuration(parse_args(("preflight",)))

    assert configuration.api_key == "ncp-secret"
    assert configuration.dataset_version == "organizer-dart-2026-08-24-v2"
    assert configuration.report_path == report


@pytest.mark.parametrize(
    "contents",
    (
        "OPEN_DART=secret\n",
        "NCP_CLOVA_STUDIO_API=one\nNCP-CLOVA-STUDIO-API=two\n",
        "NCP_CLOVA_STUDIO_API=\n",
    ),
)
def test_missing_duplicate_or_blank_named_key_is_rejected(
    tmp_path: Path,
    contents: str,
) -> None:
    key_file = tmp_path / "api.txt"
    key_file.write_text(contents, encoding="utf-8")

    with pytest.raises(EmbeddingConfigurationError, match="ncp_api_key_invalid"):
        read_ncp_api_key(key_file)


def test_parser_enforces_command_specific_arguments() -> None:
    assert parse_args(("full",)).expected_chunks == 37_629
    assert parse_args(("sample-candidates", "--limit", "10")).limit == 10
    assert parse_args(("sample", "--product-name", "KODEX 200")).product_name == "KODEX 200"
    with pytest.raises(SystemExit):
        parse_args(("sample",))
    with pytest.raises(SystemExit):
        parse_args(("preflight", "--product-name", "KODEX 200"))


def test_report_is_atomic_canonical_and_contains_no_sensitive_fields(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "report.json"
    report_hash = write_report(
        {
            "stage": "canary",
            "input_token_count": 17,
            "embedding_bytes": 4096,
        },
        destination,
    )

    raw = destination.read_bytes()
    assert json.loads(raw) == {
        "embedding_bytes": 4096,
        "input_token_count": 17,
        "stage": "canary",
    }
    assert len(report_hash) == 64
    assert not tuple(tmp_path.glob(".embedding-report-*"))


def test_report_rejects_sensitive_keys(tmp_path: Path) -> None:
    for key in ("api_key", "database_url", "embedding", "chunk_text", "query_text"):
        with pytest.raises(EmbeddingConfigurationError, match="report_sensitive_field"):
            write_report({key: "secret"}, tmp_path / f"{key}.json")


def test_main_prints_only_stable_error_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key_file, _ = _environment(tmp_path, monkeypatch)
    key_file.write_text("NCP_CLOVA_STUDIO_API=private-ncp-key\n", encoding="utf-8")

    async def fail(_configuration):
        raise EmbeddingConfigurationError("synthetic_failure")

    monkeypatch.setattr(cli, "run_command", fail)
    assert main(("canary",)) == 2
    output = capsys.readouterr()
    assert output.err.strip() == "synthetic_failure"
    assert "private-ncp-key" not in output.out + output.err
