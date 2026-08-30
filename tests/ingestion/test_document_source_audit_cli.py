from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path

import pytest

from financial_agent.documents import DocumentRole, PublisherRole
from financial_agent.documents.source_manifest import (
    DocumentSourceAuditEntry,
    DocumentSourceAuditReport,
    DocumentSourceAttempt,
    DocumentSourceCandidate,
    DocumentSourceTarget,
    SourceAuditStatus,
    SourceAuthorityTier,
)
from financial_agent.ingestion import cli
from financial_agent.ingestion.document_sources import (
    DocumentDiscoveryContext,
    SourceAdapterResult,
)
from financial_agent.ingestion.document_sources.audit import audit_document_sources


_CUTOFF = date(2026, 8, 24)
_GENERATED_AT = datetime(2026, 8, 24, 12, tzinfo=UTC)
_DATASET_VERSION = "facts-v1"


def _target(
    entity_id: str,
    *,
    product_family: str = "domestic_etf",
    identifiers: tuple[tuple[str, str], ...] = (("DART_CORP_CODE", "00123456"),),
) -> DocumentSourceTarget:
    return DocumentSourceTarget(
        dataset_version=_DATASET_VERSION,
        entity_id=entity_id,
        entity_type="product",
        canonical_name=f"Product {entity_id}",
        product_family=product_family,
        required_role=DocumentRole.PRODUCT_SUMMARY,
        binding_role="subject_product",
        identifiers=identifiers,
        cutoff_date=_CUTOFF,
    )


def _candidate(
    entity_id: str,
    *,
    document_type: str = "summary_prospectus",
) -> DocumentSourceCandidate:
    return DocumentSourceCandidate(
        document_id=f"document-{entity_id}",
        source_code="DART",
        authority_tier=SourceAuthorityTier.TIER_1_REGULATORY,
        publisher_code="FSS_DART",
        publisher_role=PublisherRole.REGULATOR_DISCLOSURE,
        document_type=document_type,
        document_version="2026.1",
        source_locator=(
            "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260820000123"
        ),
        discovery_locator="https://dart.fss.or.kr/",
        jurisdiction="KR",
        original_language="ko",
        published_at=_GENERATED_AT,
        available_at=_GENERATED_AT,
        effective_from=_CUTOFF,
        effective_to=None,
        media_type="text/html",
        accession_or_receipt_id="20260820000123",
    )


def _eligible_entry(entity_id: str = "domestic-etf-1") -> DocumentSourceAuditEntry:
    return DocumentSourceAuditEntry(
        target=_target(entity_id),
        status=SourceAuditStatus.ELIGIBLE,
        reason_code=None,
        candidate=_candidate(entity_id),
    )


def _unavailable_entry(
    status: SourceAuditStatus,
    *,
    entity_id: str,
    source_code: str = "DART",
) -> DocumentSourceAuditEntry:
    return DocumentSourceAuditEntry(
        target=_target(entity_id),
        status=status,
        reason_code=f"synthetic_{status.value}",
        candidate=None,
        attempted_source=DocumentSourceAttempt(
            source_code=source_code,
            source_locator=None,
            discovery_locator=None,
        ),
    )


def _report(
    entries: tuple[DocumentSourceAuditEntry, ...],
) -> DocumentSourceAuditReport:
    return DocumentSourceAuditReport(
        schema_version="1.0",
        generated_at=_GENERATED_AT,
        cutoff_date=_CUTOFF,
        dataset_version=_DATASET_VERSION,
        entries=entries,
    )


def _configure_environment(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv(
        "FINANCIAL_AGENT_DOCUMENT_AUDIT_DATABASE_URL",
        "postgresql://audit:synthetic-password@localhost:5432/financial_agent",
    )
    monkeypatch.setenv("FINANCIAL_AGENT_DATASET_VERSION", _DATASET_VERSION)
    monkeypatch.setenv(
        "FINANCIAL_AGENT_DOCUMENT_AUDIT_OUTPUT_ROOT", str(root)
    )
    monkeypatch.delenv("FINANCIAL_AGENT_DART_API_KEY", raising=False)
    monkeypatch.delenv("FINANCIAL_AGENT_SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("FINANCIAL_AGENT_DOCUMENT_LOCATOR_REGISTRY", raising=False)


def _execution(report: DocumentSourceAuditReport):
    return cli._DocumentSourceAuditExecution(  # type: ignore[attr-defined]
        report=report,
        registered_authorities=None,
    )


def test_audit_cli_writes_canonical_report_atomically_and_prints_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    report = _report((_eligible_entry(),))

    async def fake_run(_configuration: object):
        return _execution(report)

    monkeypatch.setattr(cli, "_run_document_source_audit", fake_run)

    exit_code = cli.main(("audit-document-sources",))
    output = capsys.readouterr()
    destination = tmp_path / "document-source-audit.json"

    assert exit_code == 0
    assert output.err == ""
    assert output.out == (
        "DOCUMENT_SOURCE_AUDIT_OK targets=1 eligible=1 not_applicable=0 "
        f"report_hash={hashlib.sha256(destination.read_bytes()).hexdigest()}\n"
    )
    assert json.loads(destination.read_text(encoding="utf-8"))["entries"][0][
        "target"
    ]["entity_id"] == "domestic-etf-1"
    assert not tuple(tmp_path.glob(".document-source-audit-*"))


def test_audit_cli_reports_unavailable_sources_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("FINANCIAL_AGENT_DART_API_KEY", "SYNTHETIC-SECRET")
    report = _report(
        (
            _unavailable_entry(
                SourceAuditStatus.DOCUMENT_NOT_FOUND,
                entity_id="domestic-etf-1",
            ),
        )
    )

    async def fake_run(_configuration: object):
        return _execution(report)

    monkeypatch.setattr(cli, "_run_document_source_audit", fake_run)

    exit_code = cli.main(("audit-document-sources",))
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err.startswith(
        "DOCUMENT_SOURCE_AUDIT_INCOMPLETE targets=1 eligible=0 unavailable=1 "
    )
    assert "document_not_found=1" in output.err
    assert "SYNTHETIC-SECRET" not in output.err
    assert "synthetic-password" not in output.err


def test_incomplete_summary_has_exact_stable_status_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    statuses = (
        SourceAuditStatus.DOCUMENT_NOT_FOUND,
        SourceAuditStatus.IDENTIFIER_MISSING,
        SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
        SourceAuditStatus.CREDENTIALS_MISSING,
        SourceAuditStatus.ACCESS_DENIED,
        SourceAuditStatus.RATE_LIMITED,
        SourceAuditStatus.ACCESS_METHOD_UNVERIFIED,
        SourceAuditStatus.TERMS_REVIEW_REQUIRED,
        SourceAuditStatus.AFTER_CUTOFF_ONLY,
        SourceAuditStatus.VERSION_UNKNOWN,
        SourceAuditStatus.MEDIA_TYPE_UNSUPPORTED,
    )
    report = _report(
        tuple(
            _unavailable_entry(status, entity_id=f"product-{index}")
            for index, status in enumerate(reversed(statuses))
        )
    )

    async def fake_run(_configuration: object):
        return _execution(report)

    monkeypatch.setattr(cli, "_run_document_source_audit", fake_run)

    assert cli.main(("audit-document-sources",)) == 2
    output = capsys.readouterr()
    report_hash = hashlib.sha256(
        (tmp_path / "document-source-audit.json").read_bytes()
    ).hexdigest()

    assert output.out == ""
    assert output.err == (
        "DOCUMENT_SOURCE_AUDIT_INCOMPLETE targets=11 eligible=0 unavailable=11 "
        "document_not_found=1 identifier_missing=1 ambiguous_entity_binding=1 "
        "credentials_missing=1 access_denied=1 rate_limited=1 "
        "access_method_unverified=1 "
        "terms_review_required=1 after_cutoff_only=1 version_unknown=1 "
        "media_type_unsupported=1 sources=DART:11 "
        f"report_hash={report_hash}\n"
    )

    non_complete = set(SourceAuditStatus) - {
        SourceAuditStatus.ELIGIBLE,
        SourceAuditStatus.NOT_APPLICABLE_CURRENT_SCOPE,
    }
    assert set(statuses) == non_complete
    named_counts = {
        status: int(
            next(
                token.split("=", 1)[1]
                for token in output.err.split()
                if token.startswith(f"{status.value}=")
            )
        )
        for status in non_complete
    }
    unavailable_count = int(
        next(
            token.split("=", 1)[1]
            for token in output.err.split()
            if token.startswith("unavailable=")
        )
    )
    assert sum(named_counts.values()) == unavailable_count


def test_incomplete_summary_and_report_sort_exact_attempted_source_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    source_codes = ("OFFICIAL_B", "SEC", "DART", "OFFICIAL_A")
    report = _report(
        tuple(
            _unavailable_entry(
                SourceAuditStatus.DOCUMENT_NOT_FOUND,
                entity_id=f"product-{index}",
                source_code=source_code,
            )
            for index, source_code in enumerate(source_codes)
        )
    )

    async def fake_run(_configuration: object):
        return _execution(report)

    monkeypatch.setattr(cli, "_run_document_source_audit", fake_run)

    assert cli.main(("audit-document-sources",)) == 2
    output = capsys.readouterr()
    payload = json.loads(
        (tmp_path / "document-source-audit.json").read_text(encoding="utf-8")
    )

    assert "sources=DART:1,OFFICIAL_A:1,OFFICIAL_B:1,SEC:1" in output.err
    assert sorted(
        entry["attempted_source"]["source_code"]
        for entry in payload["entries"]
    ) == ["DART", "OFFICIAL_A", "OFFICIAL_B", "SEC"]
    assert "SYNTHETIC-SECRET" not in output.err
    assert "SYNTHETIC-SECRET" not in json.dumps(payload)


def test_wrong_role_result_retains_route_source_in_report_and_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_environment(monkeypatch, tmp_path)

    class WrongRoleDartAdapter:
        source_code = "DART"

        def supports(self, _target: DocumentSourceTarget) -> bool:
            return True

        def discover(
            self,
            _target: DocumentSourceTarget,
            _context: DocumentDiscoveryContext,
        ) -> SourceAdapterResult:
            return SourceAdapterResult(
                status=SourceAuditStatus.ELIGIBLE,
                reason_code=None,
                candidates=(
                    _candidate(
                        "wrong-role",
                        document_type="index_methodology",
                    ),
                ),
            )

    report = audit_document_sources(
        targets=(_target("domestic-etf-1"),),
        adapters=(WrongRoleDartAdapter(),),
        context=DocumentDiscoveryContext(
            cutoff_date=_CUTOFF,
            dart_api_key="configured",
            sec_user_agent=None,
            locator_registry_path=None,
        ),
        generated_at=_GENERATED_AT,
    )

    async def fake_run(_configuration: object):
        return _execution(report)

    monkeypatch.setattr(cli, "_run_document_source_audit", fake_run)

    assert cli.main(("audit-document-sources",)) == 2
    output = capsys.readouterr()
    payload = json.loads(
        (tmp_path / "document-source-audit.json").read_text(encoding="utf-8")
    )

    assert report.entries[0].status is SourceAuditStatus.DOCUMENT_NOT_FOUND
    assert report.entries[0].reason_code == "no_candidate_for_required_role"
    assert "sources=DART:1" in output.err
    assert payload["entries"][0]["candidate"] is None
    assert payload["entries"][0]["attempted_source"] == {
        "discovery_locator": None,
        "source_code": "DART",
        "source_locator": None,
    }


@pytest.mark.parametrize(
    ("variable", "value"),
    (
        ("FINANCIAL_AGENT_DOCUMENT_AUDIT_DATABASE_URL", " "),
        ("FINANCIAL_AGENT_DATASET_VERSION", "\t"),
        ("FINANCIAL_AGENT_DOCUMENT_AUDIT_OUTPUT_ROOT", ""),
        ("FINANCIAL_AGENT_DOCUMENT_LOCATOR_REGISTRY", "  "),
    ),
)
def test_audit_cli_rejects_blank_configured_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    variable: str,
    value: str,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(variable, value)

    assert cli.main(("audit-document-sources",)) == 2
    output = capsys.readouterr()

    assert output.out == ""
    assert output.err == "CONFIGURATION_MISSING\n"


@pytest.mark.parametrize(
    "variable",
    ("FINANCIAL_AGENT_DART_API_KEY", "FINANCIAL_AGENT_SEC_USER_AGENT"),
)
def test_blank_source_credentials_are_normalized_to_per_target_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    variable: str,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(variable, " \t ")
    observed: dict[str, object] = {}
    report = _report(
        (
            _unavailable_entry(
                SourceAuditStatus.CREDENTIALS_MISSING,
                entity_id="product-missing-credentials",
            ),
        )
    )

    async def fake_run(configuration: object):
        observed["configuration"] = configuration
        return _execution(report)

    monkeypatch.setattr(cli, "_run_document_source_audit", fake_run)

    assert cli.main(("audit-document-sources",)) == 2
    configuration = observed["configuration"]
    assert getattr(configuration, "dart_api_key") is None
    assert getattr(configuration, "sec_user_agent") is None
    assert "credentials_missing=1" in capsys.readouterr().err


@pytest.mark.parametrize("relative_path", ("reports", "../reports"))
def test_audit_cli_rejects_relative_output_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    relative_path: str,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "FINANCIAL_AGENT_DOCUMENT_AUDIT_OUTPUT_ROOT", relative_path
    )

    assert cli.main(("audit-document-sources",)) == 2

    assert capsys.readouterr().err == "CLI_ARGUMENT_INVALID\n"


def test_audit_cli_rejects_output_root_that_is_a_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "not-a-directory"
    output_file.write_text("occupied", encoding="utf-8")
    _configure_environment(monkeypatch, output_file)

    assert cli.main(("audit-document-sources",)) == 2

    assert capsys.readouterr().err == "CLI_ARGUMENT_INVALID\n"
    assert output_file.read_text(encoding="utf-8") == "occupied"


def test_audit_cli_rejects_non_postgresql_database_url_without_printing_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    secret_url = "sqlite:///SYNTHETIC-SECRET.db"
    monkeypatch.setenv("FINANCIAL_AGENT_DOCUMENT_AUDIT_DATABASE_URL", secret_url)

    assert cli.main(("audit-document-sources",)) == 2
    output = capsys.readouterr()

    assert output.out == ""
    assert "SYNTHETIC-SECRET" not in output.err


class _NeverOpen:
    def open_no_redirect(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("missing source configuration must not call the network")


def test_missing_dart_and_sec_configuration_is_reported_per_affected_target() -> None:
    overseas = _target(
        "overseas-etf-1",
        product_family="overseas_etf",
        identifiers=(
            ("SEC_CIK", "123456"),
            ("SEC_SERIES_ID", "S000000001"),
            ("SEC_CLASS_ID", "C000000001"),
        ),
    )
    configuration = cli._DocumentSourceAuditConfiguration(  # type: ignore[attr-defined]
        database_url="postgresql://audit@localhost/financial_agent",
        dataset_version=_DATASET_VERSION,
        output_root=Path("/tmp/audit-output"),
        dart_api_key=None,
        sec_user_agent=None,
        locator_registry_path=None,
    )

    execution = cli._audit_document_targets(  # type: ignore[attr-defined]
        (_target("domestic-etf-1"), overseas),
        configuration=configuration,
        opener=_NeverOpen(),
        generated_at=_GENERATED_AT,
    )

    assert [entry.status for entry in execution.report.entries] == [
        SourceAuditStatus.CREDENTIALS_MISSING,
        SourceAuditStatus.CREDENTIALS_MISSING,
    ]
    assert [entry.reason_code for entry in execution.report.entries] == [
        "dart_api_key_missing",
        "sec_user_agent_missing",
    ]


class _UnsafeBodyOpen:
    def open_no_redirect(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("raw body SYNTHETIC-SECRET <html>denied</html>")


def test_upstream_raw_body_is_not_retained_in_audit_error() -> None:
    configuration = cli._DocumentSourceAuditConfiguration(  # type: ignore[attr-defined]
        database_url="postgresql://audit@localhost/financial_agent",
        dataset_version=_DATASET_VERSION,
        output_root=Path("/tmp/audit-output"),
        dart_api_key="configured-key",
        sec_user_agent=None,
        locator_registry_path=None,
    )

    execution = cli._audit_document_targets(  # type: ignore[attr-defined]
        (_target("domestic-etf-1"),),
        configuration=configuration,
        opener=_UnsafeBodyOpen(),
        generated_at=_GENERATED_AT,
    )

    assert (
        execution.report.entries[0].status
        is SourceAuditStatus.ACCESS_METHOD_UNVERIFIED
    )
    assert execution.report.entries[0].reason_code == "dart_access_method_unverified"
    assert "SYNTHETIC-SECRET" not in repr(execution)
    assert "<html>" not in repr(execution)


class _MappingsResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _MappingsResult:
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _PolicyConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _MappingsResult:
        self.statements.append(statement)
        return _MappingsResult(self.rows)


def _policy_locator(entity_id: str) -> dict[str, object]:
    return {
        "entity_id": entity_id,
        "entity_type": "policy",
        "required_role": "policy_base",
        "binding_role": "subject_policy",
        "document_id": f"document-{entity_id}",
        "source_code": "SYNTHETIC_POLICY_AUTHORITY",
        "authority_tier": "tier_2_claim_owner",
        "publisher_code": "SYNTHETIC_POLICY_AUTHORITY",
        "publisher_role": "policy_authority",
        "source_locator": f"https://policy.example.invalid/{entity_id}.pdf",
        "discovery_locator": "https://policy.example.invalid/documents",
        "document_type": "policy_base",
        "document_version": "2026.1",
        "published_at": "2026-08-20T01:00:00Z",
        "available_at": "2026-08-20T01:05:00Z",
        "effective_from": "2026-08-20",
        "effective_to": None,
        "original_language": "ko",
        "jurisdiction": "KR",
        "media_type": "application/pdf",
        "accession_or_receipt_id": None,
    }


@pytest.mark.asyncio
async def test_policy_registry_reconciles_missing_and_type_mismatched_entities(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authority_registry = tmp_path / "authorities.json"
    authority_registry.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "authorities": [
                    {
                        "source_code": "SYNTHETIC_POLICY_AUTHORITY",
                        "authority_tier": "tier_2_claim_owner",
                        "publisher_role": "policy_authority",
                        "jurisdiction": "KR",
                        "allowed_hosts": ["policy.example.invalid"],
                        "allowed_document_roles": ["policy_base"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_DOCUMENT_AUTHORITY_REGISTRY", authority_registry)
    unreviewed_locator = _policy_locator("policy-unreviewed")
    unreviewed_locator.update(
        source_code="UNREVIEWED_AUTHORITY",
        publisher_code="UNREVIEWED_AUTHORITY",
        source_locator="https://unreviewed.example.invalid/policy.pdf",
        discovery_locator="https://unreviewed.example.invalid/documents",
    )
    registry = tmp_path / "locators.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "locators": [
                    _policy_locator("policy-present"),
                    _policy_locator("policy-absent"),
                    _policy_locator("policy-type-mismatch"),
                    unreviewed_locator,
                ],
            }
        ),
        encoding="utf-8",
    )
    connection = _PolicyConnection(
        [
            {
                "entity_id": "policy-present",
                "canonical_name": "Present policy entity",
                "entity_type": "policy",
            },
            {
                "entity_id": "policy-type-mismatch",
                "canonical_name": "Existing institution entity",
                "entity_type": "institution",
            }
        ]
    )

    reconciliation = await cli._list_exact_policy_targets(  # type: ignore[attr-defined]
        connection,  # type: ignore[arg-type]
        dataset_version=_DATASET_VERSION,
        cutoff_date=_CUTOFF,
        locator_registry_path=registry,
    )

    assert [
        (target.entity_id, target.entity_type, target.canonical_name)
        for target in reconciliation.targets
    ] == [
        ("policy-present", "policy", "Present policy entity")
    ]
    assert [
        (
            entry.target.entity_id,
            entry.target.entity_type,
            entry.target.canonical_name,
            entry.status,
            entry.reason_code,
        )
        for entry in reconciliation.unavailable_entries
    ] == [
        (
            "policy-absent",
            "policy",
            None,
            SourceAuditStatus.IDENTIFIER_MISSING,
            "policy_entity_missing",
        ),
        (
            "policy-type-mismatch",
            "institution",
            "Existing institution entity",
            SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
            "policy_entity_type_mismatch",
        ),
        (
            "policy-unreviewed",
            "policy",
            None,
            SourceAuditStatus.IDENTIFIER_MISSING,
            "policy_entity_missing",
        ),
    ]
    assert [
        entry.attempted_source.source_code
        for entry in reconciliation.unavailable_entries
        if entry.attempted_source is not None
    ] == ["REGISTERED", "REGISTERED", "REGISTERED"]

    configuration = cli._DocumentSourceAuditConfiguration(  # type: ignore[attr-defined]
        database_url="postgresql://audit@localhost/financial_agent",
        dataset_version=_DATASET_VERSION,
        output_root=tmp_path,
        dart_api_key=None,
        sec_user_agent=None,
        locator_registry_path=registry,
    )
    execution = cli._audit_document_targets(  # type: ignore[attr-defined]
        (),
        configuration=configuration,
        opener=_NeverOpen(),
        generated_at=_GENERATED_AT,
        preliminary_entries=reconciliation.unavailable_entries,
    )

    assert [entry.status for entry in execution.report.entries] == [
        SourceAuditStatus.IDENTIFIER_MISSING,
        SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
        SourceAuditStatus.IDENTIFIER_MISSING,
    ]
    assert [
        entry.attempted_source.source_code
        for entry in execution.report.entries
        if entry.attempted_source is not None
    ] == [
        "SYNTHETIC_POLICY_AUTHORITY",
        "SYNTHETIC_POLICY_AUTHORITY",
        "REGISTERED",
    ]
    assert all(
        entry.attempted_source is not None
        and (
            entry.attempted_source.source_locator is None
            or "SYNTHETIC-SECRET" not in entry.attempted_source.source_locator
        )
        for entry in execution.report.entries
    )
    assert not cli.document_source_audit_passed(execution.report)
    assert all(
        getattr(statement, "is_select", False)
        for statement in connection.statements
    )


def test_read_only_database_engine_configuration_is_used(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_environment(monkeypatch, tmp_path)
    configuration = (
        cli._load_document_source_audit_configuration()  # type: ignore[attr-defined]
    )
    observed: dict[str, object] = {}

    class _Transaction:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class _Engine:
        def begin(self) -> _Transaction:
            observed["began"] = True
            return _Transaction()

        async def dispose(self) -> None:
            observed["disposed"] = True

    def fake_create(config: object, *, read_only: bool = False) -> _Engine:
        observed["config"] = config
        observed["read_only"] = read_only
        return _Engine()

    async def fail_after_connection(
        _connection: object,
        *_args: object,
        **_kwargs: object,
    ):
        raise RuntimeError("stop after transaction setup")

    monkeypatch.setattr(cli, "create_database_engine", fake_create)
    monkeypatch.setattr(cli, "_load_document_audit_scope", fail_after_connection)

    with pytest.raises(RuntimeError, match="transaction setup"):
        cli.asyncio.run(
            cli._run_document_source_audit(  # type: ignore[attr-defined]
                configuration
            )
        )

    assert observed["read_only"] is True
    assert observed["began"] is True
    assert observed["disposed"] is True
    assert "synthetic-password" not in repr(observed["config"])
