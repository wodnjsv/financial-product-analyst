from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import pytest

from financial_agent.ingestion.cli import (
    _DartCorpusConfiguration,
    IngestionArgumentError,
    _DartCorpusRunReport,
    _discard_failed_dart_pdf,
    _load_dart_corpus_configuration,
    _load_dart_corpus_inventory,
    _limited_dart_inventory,
    _partition_dart_inventory,
    _parser,
    _run_dart_corpus,
    _write_dart_corpus_report,
)
from financial_agent.ingestion.document_sources.dart_targets import (
    DartRecoveryProductState,
    OrganizerDartInventory,
    OrganizerDartTarget,
)
from financial_agent.ingestion.document_sources.dart_batch import (
    DartBatchDiscoveryResult,
    DartTargetDiscoveryDisposition,
)
from financial_agent.ingestion.document_sources.dart_publishers import (
    DartPublisherReconciliation,
)
from financial_agent.documents import SourceAuditStatus


def _arguments(
    limit: str | None = None,
    target_key: str | None = None,
    missing_only: bool = False,
):
    values = ["ingest-dart-corpus"]
    if limit is not None:
        values.extend(("--limit", limit))
    if target_key is not None:
        values.extend(("--target-key", target_key))
    if missing_only:
        values.append("--missing-only")
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


def test_configuration_accepts_one_exact_target_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch, tmp_path)

    configuration = _load_dart_corpus_configuration(
        _arguments(target_key="domestic_etf:product-one")
    )

    assert configuration.target_key == "domestic_etf:product-one"
    assert configuration.limit is None


@pytest.mark.parametrize(
    ("limit", "target_key"),
    ((None, None), ("1", None), (None, "public_fund:product-one")),
)
def test_configuration_accepts_missing_only_with_each_selection_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: str | None,
    target_key: str | None,
) -> None:
    _environment(monkeypatch, tmp_path)

    configuration = _load_dart_corpus_configuration(
        _arguments(limit, target_key, missing_only=True)
    )

    assert configuration.missing_only is True
    assert configuration.limit == (int(limit) if limit is not None else None)
    assert configuration.target_key == target_key


def test_configuration_defaults_missing_only_to_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch, tmp_path)

    configuration = _load_dart_corpus_configuration(_arguments())

    assert configuration.missing_only is False


def test_parser_rejects_limit_and_target_key_together() -> None:
    with pytest.raises(IngestionArgumentError):
        _arguments("1", "domestic_etf:product-one")


def test_exact_target_selection_fails_closed_when_target_is_absent() -> None:
    target = OrganizerDartTarget(
        target_key="domestic_etf:product-one",
        product_family="domestic_etf",
        representative_entity_id="product-one",
        canonical_name="Product One",
        member_entity_ids=("product-one",),
        identifiers=(("product-one", "ISIN", "KR0000000001"),),
        manager_bindings=(("manager-one", "Manager One"),),
    )
    inventory = OrganizerDartInventory(
        dataset_version="documents-building-v1",
        cutoff_date=date(2026, 8, 24),
        product_count=1,
        targets=(target,),
        inventory_hash="a" * 64,
    )

    selected = _limited_dart_inventory(
        inventory,
        None,
        "domestic_etf:product-one",
    )
    assert selected.targets == (target,)

    with pytest.raises(IngestionArgumentError):
        _limited_dart_inventory(
            inventory,
            None,
            "domestic_etf:missing",
        )


def test_partition_blocks_unusable_representative_before_discovery() -> None:
    blocked = OrganizerDartTarget(
        target_key="public_fund:blocked",
        product_family="public_fund",
        representative_entity_id="blocked",
        canonical_name="Blocked Fund",
        member_entity_ids=("blocked",),
        identifiers=(("blocked", "PRFD_ITM_NO", "PF-BLOCKED"),),
        manager_bindings=(("manager-one", "Manager One"),),
        document_collection_block_reason=(
            "representative_identifier_unavailable"
        ),
    )
    eligible = OrganizerDartTarget(
        target_key="public_fund:eligible",
        product_family="public_fund",
        representative_entity_id="eligible",
        canonical_name="Eligible Fund",
        member_entity_ids=("eligible",),
        identifiers=(("eligible", "PRFD_ITM_NO", "PF-ELIGIBLE"),),
        manager_bindings=(("manager-one", "Manager One"),),
    )
    inventory = OrganizerDartInventory(
        dataset_version="documents-building-v1",
        cutoff_date=date(2026, 8, 24),
        product_count=2,
        targets=(blocked, eligible),
        inventory_hash="a" * 64,
    )

    actionable, failures = _partition_dart_inventory(inventory)

    assert actionable.targets == (eligible,)
    assert failures == {
        "public_fund:blocked": "representative_identifier_unavailable"
    }


@pytest.mark.asyncio
async def test_blocked_only_run_makes_no_dart_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = OrganizerDartTarget(
        target_key="public_fund:blocked",
        product_family="public_fund",
        representative_entity_id="blocked",
        canonical_name="Blocked Fund",
        member_entity_ids=("blocked",),
        identifiers=(("blocked", "PRFD_ITM_NO", "PF-BLOCKED"),),
        manager_bindings=(("manager-one", "Manager One"),),
        document_collection_block_reason=(
            "representative_identifier_unavailable"
        ),
    )
    inventory = OrganizerDartInventory(
        dataset_version="documents-building-v1",
        cutoff_date=date(2026, 8, 24),
        product_count=1,
        targets=(blocked,),
        inventory_hash="a" * 64,
    )

    class Engine:
        async def dispose(self) -> None:
            return None

    async def load(_configuration: object):
        return Engine(), inventory, {}, ()

    monkeypatch.setattr(
        "financial_agent.ingestion.cli._load_dart_corpus_inventory",
        load,
    )

    def unexpected_request(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("blocked targets must not issue a DART request")

    monkeypatch.setattr(
        "financial_agent.ingestion.cli.fetch_dart_corporation_codes",
        unexpected_request,
    )
    configuration = _DartCorpusConfiguration(
        database_url="postgresql+psycopg://unused",
        dataset_version="documents-building-v1",
        dart_api_key="secret",
        temp_root=tmp_path / "run",
        publisher_aliases={},
        report_path=tmp_path / "report.json",
        limit=None,
        target_key=None,
    )

    report = await _run_dart_corpus(configuration)

    assert report.requested_publisher_count == 0
    assert report.failed_targets == (
        ("public_fund:blocked", "representative_identifier_unavailable"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "target_key"),
    ((1, None), (None, "public_fund:missing-public")),
)
async def test_missing_only_run_discovers_only_actionable_recovery_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: int | None,
    target_key: str | None,
) -> None:
    def target(
        key: str,
        family: Literal["domestic_etf", "public_fund"],
        member: str,
    ) -> OrganizerDartTarget:
        return OrganizerDartTarget(
            target_key=key,
            product_family=family,
            representative_entity_id=member,
            canonical_name=member,
            member_entity_ids=(member,),
            identifiers=((member, "ISIN", member),),
            manager_bindings=(("manager-one", "Manager One"),),
        )

    completed = target("public_fund:complete", "public_fund", "complete")
    etn = target("domestic_etf:etn", "domestic_etf", "etn")
    private_fund = target(
        "public_fund:private", "public_fund", "private-fund"
    )
    missing = replace(
        target(
            "public_fund:missing-public", "public_fund", "missing-public"
        ),
        member_entity_ids=("missing-public", "private-member"),
        member_entity_names=(
            ("missing-public", "Missing Public"),
            ("private-member", "Private Member"),
        ),
        identifiers=(
            ("missing-public", "ISIN", "missing-public"),
            ("private-member", "ISIN", "private-member"),
        ),
    )
    inventory = OrganizerDartInventory(
        dataset_version="documents-building-v1",
        cutoff_date=date(2026, 8, 24),
        product_count=4,
        targets=(completed, etn, private_fund, missing),
        inventory_hash="a" * 64,
    )
    states = (
        DartRecoveryProductState(
            "complete", "fund_prospectus", True
        ),
        DartRecoveryProductState("etn", "etn_not_applicable", False),
        DartRecoveryProductState(
            "private-fund", "private_fund_not_applicable", False
        ),
        DartRecoveryProductState(
            "missing-public", "fund_prospectus", False
        ),
        DartRecoveryProductState(
            "private-member", "private_fund_not_applicable", False
        ),
    )

    class Engine:
        async def dispose(self) -> None:
            return None

    async def load(_configuration: object):
        return Engine(), inventory, {}, states

    monkeypatch.setattr(
        "financial_agent.ingestion.cli._load_dart_corpus_inventory", load
    )
    monkeypatch.setattr(
        "financial_agent.ingestion.cli.fetch_dart_corporation_codes",
        lambda *_args: b"synthetic-corporation-codes",
    )
    monkeypatch.setattr(
        "financial_agent.ingestion.cli.reconcile_dart_publishers",
        lambda **_kwargs: DartPublisherReconciliation((), (), "a" * 64),
    )
    requested_target_keys: tuple[str, ...] = ()
    requested_member_entity_ids: tuple[str, ...] = ()

    def discover(**kwargs: object) -> DartBatchDiscoveryResult:
        nonlocal requested_target_keys, requested_member_entity_ids
        selected_inventory = kwargs["inventory"]
        requested_target_keys = tuple(
            item.target_key for item in selected_inventory.targets
        )
        requested_member_entity_ids = tuple(
            member_id
            for item in selected_inventory.targets
            for member_id in item.member_entity_ids
        )
        return DartBatchDiscoveryResult(
            dispositions=tuple(
                DartTargetDiscoveryDisposition(
                    target_key=item.target_key,
                    member_entity_ids=item.member_entity_ids,
                    status=SourceAuditStatus.DOCUMENT_NOT_FOUND,
                    reason_code="document_not_found",
                    candidates=(),
                    resolved_product_name=None,
                )
                for item in selected_inventory.targets
            ),
            requested_publisher_codes=(),
            rejected_filings=(),
        )

    monkeypatch.setattr(
        "financial_agent.ingestion.cli.discover_dart_candidates_by_publisher",
        discover,
    )
    configuration = _DartCorpusConfiguration(
        database_url="postgresql+psycopg://unused",
        dataset_version="documents-building-v1",
        dart_api_key="secret",
        temp_root=tmp_path / "run",
        publisher_aliases={},
        report_path=tmp_path / "report.json",
        limit=limit,
        target_key=target_key,
        missing_only=True,
    )

    report = await _run_dart_corpus(configuration)

    assert requested_target_keys == ("public_fund:missing-public",)
    assert requested_member_entity_ids == ("missing-public",)
    assert report.already_embedded_target_count == 1
    assert report.not_applicable_target_count == 2
    assert report.not_applicable_reason_counts == (
        ("etn_not_applicable", 1),
        ("private_fund_not_applicable", 1),
    )
    assert report.excluded_not_applicable_member_count == 1
    assert report.excluded_not_applicable_member_reason_counts == (
        ("private_fund_not_applicable", 1),
    )
    assert report.failed_targets == (
        ("public_fund:missing-public", "document_not_found"),
    )


@pytest.mark.asyncio
async def test_default_inventory_load_skips_recovery_state_query(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        def mappings(self) -> Result:
            return self

        def one_or_none(self) -> dict[str, object]:
            return {
                "cutoff_date": date(2026, 8, 24),
                "status": "building",
            }

    class Connection:
        async def scalar(self, _statement: object) -> str:
            return "150000"

        async def execute(self, _statement: object) -> Result:
            return Result()

    class ConnectionContext:
        async def __aenter__(self) -> Connection:
            return Connection()

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Engine:
        def connect(self) -> ConnectionContext:
            return ConnectionContext()

        async def dispose(self) -> None:
            return None

    async def list_rows(*_args: object) -> tuple[object, ...]:
        return ()

    async def list_identifiers(*_args: object) -> dict[str, object]:
        return {}

    async def unexpected_recovery_states(*_args: object) -> tuple[object, ...]:
        raise AssertionError("default run must not load recovery state")

    monkeypatch.setattr(
        "financial_agent.ingestion.cli.create_database_engine",
        lambda _config: Engine(),
    )
    monkeypatch.setattr(
        "financial_agent.ingestion.cli.DocumentTargetRepository.list_organizer_dart_rows",
        list_rows,
    )
    monkeypatch.setattr(
        "financial_agent.ingestion.cli.DocumentTargetRepository.list_identifiers",
        list_identifiers,
    )
    monkeypatch.setattr(
        "financial_agent.ingestion.cli.DocumentTargetRepository.list_dart_recovery_states",
        unexpected_recovery_states,
    )

    engine, inventory, identifiers, recovery_states = (
        await _load_dart_corpus_inventory(
            _DartCorpusConfiguration(
                database_url="postgresql+psycopg://unused",
                dataset_version="documents-building-v1",
                dart_api_key="secret",
                temp_root=tmp_path / "run",
                publisher_aliases={},
                report_path=tmp_path / "report.json",
                limit=None,
                target_key=None,
            )
        )
    )

    assert inventory.targets == ()
    assert identifiers == {}
    assert recovery_states == ()
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_key",
    ("public_fund:complete", "domestic_etf:etn"),
)
async def test_missing_only_target_key_fails_closed_after_recovery_filtering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_key: str,
) -> None:
    completed = OrganizerDartTarget(
        target_key="public_fund:complete",
        product_family="public_fund",
        representative_entity_id="complete",
        canonical_name="Complete",
        member_entity_ids=("complete",),
        identifiers=(("complete", "ISIN", "complete"),),
        manager_bindings=(),
    )
    etn = OrganizerDartTarget(
        target_key="domestic_etf:etn",
        product_family="domestic_etf",
        representative_entity_id="etn",
        canonical_name="ETN",
        member_entity_ids=("etn",),
        identifiers=(("etn", "ISIN", "etn"),),
        manager_bindings=(),
    )
    inventory = OrganizerDartInventory(
        dataset_version="documents-building-v1",
        cutoff_date=date(2026, 8, 24),
        product_count=2,
        targets=(completed, etn),
        inventory_hash="a" * 64,
    )
    states = (
        DartRecoveryProductState("complete", "fund_prospectus", True),
        DartRecoveryProductState("etn", "etn_not_applicable", False),
    )

    class Engine:
        async def dispose(self) -> None:
            return None

    async def load(_configuration: object):
        return Engine(), inventory, {}, states

    monkeypatch.setattr(
        "financial_agent.ingestion.cli._load_dart_corpus_inventory", load
    )
    configuration = _DartCorpusConfiguration(
        database_url="postgresql+psycopg://unused",
        dataset_version="documents-building-v1",
        dart_api_key="secret",
        temp_root=tmp_path / "run",
        publisher_aliases={},
        report_path=tmp_path / "report.json",
        limit=None,
        target_key=target_key,
        missing_only=True,
    )

    with pytest.raises(IngestionArgumentError):
        await _run_dart_corpus(configuration)


@pytest.mark.asyncio
async def test_missing_only_empty_selection_reports_counts_without_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = OrganizerDartTarget(
        target_key="public_fund:complete",
        product_family="public_fund",
        representative_entity_id="complete",
        canonical_name="Complete",
        member_entity_ids=("complete",),
        identifiers=(("complete", "ISIN", "complete"),),
        manager_bindings=(),
    )
    private_fund = OrganizerDartTarget(
        target_key="public_fund:private",
        product_family="public_fund",
        representative_entity_id="private",
        canonical_name="Private",
        member_entity_ids=("private",),
        identifiers=(("private", "ISIN", "private"),),
        manager_bindings=(),
    )
    inventory = OrganizerDartInventory(
        dataset_version="documents-building-v1",
        cutoff_date=date(2026, 8, 24),
        product_count=2,
        targets=(completed, private_fund),
        inventory_hash="a" * 64,
    )
    states = (
        DartRecoveryProductState("complete", "fund_prospectus", True),
        DartRecoveryProductState(
            "private", "private_fund_not_applicable", False
        ),
    )

    class Engine:
        async def dispose(self) -> None:
            return None

    async def load(_configuration: object):
        return Engine(), inventory, {}, states

    def unexpected_request(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("empty recovery selection must make no request")

    monkeypatch.setattr(
        "financial_agent.ingestion.cli._load_dart_corpus_inventory", load
    )
    monkeypatch.setattr(
        "financial_agent.ingestion.cli.fetch_dart_corporation_codes",
        unexpected_request,
    )
    report = await _run_dart_corpus(
        _DartCorpusConfiguration(
            database_url="postgresql+psycopg://unused",
            dataset_version="documents-building-v1",
            dart_api_key="secret",
            temp_root=tmp_path / "run",
            publisher_aliases={},
            report_path=tmp_path / "report.json",
            limit=None,
            target_key=None,
            missing_only=True,
        )
    )

    assert report.selected_target_count == 0
    assert report.requested_publisher_count == 0
    assert report.failed_targets == ()
    assert report.already_embedded_target_count == 1
    assert report.not_applicable_target_count == 1
    assert report.not_applicable_reason_counts == (
        ("private_fund_not_applicable", 1),
    )


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
        already_embedded_target_count=1,
        not_applicable_target_count=2,
        not_applicable_reason_counts=(
            ("etn_not_applicable", 1),
            ("private_fund_not_applicable", 1),
        ),
        excluded_not_applicable_member_count=3,
        excluded_not_applicable_member_reason_counts=(
            ("private_fund_not_applicable", 3),
        ),
    )

    report_hash = _write_dart_corpus_report(report, destination)
    payload = destination.read_text(encoding="utf-8")

    assert len(report_hash) == 64
    assert "SYNTHETIC-SECRET" not in payload
    assert "추종지수의 변동" not in payload
    written = json.loads(payload)
    assert written["inventory_hash"] == "a" * 64
    assert written["already_embedded_target_count"] == 1
    assert written["not_applicable_target_count"] == 2
    assert written["not_applicable_reason_counts"] == [
        ["etn_not_applicable", 1],
        ["private_fund_not_applicable", 1],
    ]
    assert written["excluded_not_applicable_member_count"] == 3
    assert written["excluded_not_applicable_member_reason_counts"] == [
        ["private_fund_not_applicable", 3],
    ]


def test_failed_pdf_records_identity_then_is_deleted(tmp_path: Path) -> None:
    receipt = "20260716000161"
    pdf = tmp_path / f"dart-{receipt}" / "source.pdf"
    pdf.parent.mkdir()
    content = b"%PDF-1.4\nfailed\n%%EOF\n"
    pdf.write_bytes(content)

    record = _discard_failed_dart_pdf(
        tmp_path,
        receipt,
        "approved_section_not_found",
    )

    assert record is not None
    assert record[:3] == (
        receipt,
        "approved_section_not_found",
        len(content),
    )
    assert len(record[3]) == 64
    assert not pdf.exists()
