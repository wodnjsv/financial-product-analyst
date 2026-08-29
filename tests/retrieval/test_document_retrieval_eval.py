from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.db.config import DatabaseConfig
from financial_agent.db.engine import create_database_engine
from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import DocumentCandidateHit, DocumentCandidateRepository, DocumentSearchRequest
from scripts.verify_document_retrieval_pipeline import (
    AuthoritativeHitAudit,
    EvaluationCorpus,
    EvaluationConfigurationError,
    GoldCatalogError,
    LedgerCounts,
    NEGATIVE_PROBES,
    NegativeMetadataAudit,
    OutputPolicyError,
    PostgresSafetyAuditor,
    _has_eligible_superseder,
    _run,
    evaluate_cases,
    load_gold_catalog,
    main,
    report_exit_code,
    validate_output_path,
    write_report_atomically,
)
from tests.fixtures.document_corpus import DATASET_VERSION, insert_document_search_corpus


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = PROJECT_ROOT / "tests/gold/document_retrieval_cases.json"
EXPECTED_CASE_IDS = ("DOC-FUND-001-structure", "REL-CORP-001-risk", "REL-THEME-001-history")
EXPECTED_NEGATIVE_GATES = {
    "wrong_product": "entity",
    "wrong_claim_authority": "claim_authority",
    "source_ineligible": "source_eligibility",
    "after_seoul_cutoff": "temporal",
    "stale_effective_version": "version",
    "name_only_wrong_entity": "entity",
    "generic_commentary": "section",
    "performance_table": "section",
    "generated_summary": "section",
}


def _hit(
    chunk_id: str,
    *,
    entity_id: str,
    section_type: SectionType,
    dataset_version: str = DATASET_VERSION,
    keyword_rank: int | None = None,
    vector_rank: int | None = None,
    publisher_approved: bool = True,
) -> DocumentCandidateHit:
    return DocumentCandidateHit(
        dataset_version=dataset_version,
        entity_id=entity_id,
        document_id=f"document-{chunk_id}",
        chunk_id=chunk_id,
        section_type=section_type,
        exact_text=f"Synthetic exact text for {chunk_id}.",
        source_id="source-approved",
        source_locator=f"synthetic/source#{chunk_id}",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=datetime(2026, 8, 2, tzinfo=UTC),
        effective_from=date(2026, 8, 1),
        effective_to=None,
        document_version="2026-08-01",
        cutoff_eligible=True,
        publisher_approved=publisher_approved,
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
        fused_score=None,
        evidence_id=None,
    )


class _QueryResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def one_or_none(self):
        assert len(self._rows) <= 1
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _ScriptedConnection:
    def __init__(self, *results: _QueryResult) -> None:
        self._results = iter(results)

    async def execute(self, statement):
        del statement
        return next(self._results)


def _authoritative_row(chunk_id: str, document_id: str) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "section_type": "risk_factor",
        "source_id": "source-approved",
        "document_type": "full_prospectus",
        "published_at": datetime(2026, 8, 1, tzinfo=UTC),
        "available_at": datetime(2026, 8, 2, tzinfo=UTC),
        "document_version": "2026-08-01",
        "publisher_role": "regulator_disclosure",
        "effective_from": date(2026, 8, 1),
        "effective_to": None,
        "cutoff_eligible": True,
        "eligible_for_claim": True,
        "dataset_status": "building",
        "dataset_cutoff": date(2026, 8, 24),
    }


_GOLD = {
    "policy-fund-one": ("policy-structure", SectionType.LEGAL_STRUCTURE),
    "aerospace-index-one": ("aerospace-change", SectionType.CHANGE_HISTORY),
    "selected-etf": ("selected-etf-risk", SectionType.RISK_FACTOR),
}


class _ComparisonRepository:
    def __init__(self, *, return_negative: str | None = None) -> None:
        self.return_negative = return_negative

    async def search_keyword(self, request: DocumentSearchRequest, query_text: str) -> tuple[DocumentCandidateHit, ...]:
        probe = next((item for item in NEGATIVE_PROBES if item.query_text == query_text), None)
        if probe is not None:
            if probe.chunk_id == self.return_negative:
                return (_hit(probe.chunk_id, entity_id=probe.entity_ids[0], section_type=probe.section_types[0], keyword_rank=1),)
            return ()
        return (_hit(f"keyword-decoy-{request.entity_ids[0]}", entity_id=request.entity_ids[0], section_type=request.section_types[0], keyword_rank=1),)

    async def search_vector(self, request: DocumentSearchRequest) -> tuple[DocumentCandidateHit, ...]:
        probe = next(
            (
                item for item in NEGATIVE_PROBES
                if item.entity_ids == request.entity_ids
                and item.claim_type == request.claim_type
                and item.section_types == request.section_types
                and item.query_embedding == request.query_embedding
            ),
            None,
        )
        if probe is not None:
            if probe.chunk_id == self.return_negative:
                return (_hit(probe.chunk_id, entity_id=probe.entity_ids[0], section_type=probe.section_types[0], vector_rank=1),)
            return ()
        chunk_id, section_type = _GOLD[request.entity_ids[0]]
        return (_hit(chunk_id, entity_id=request.entity_ids[0], section_type=section_type, vector_rank=1),)


def _safe_audit(hit: DocumentCandidateHit) -> AuthoritativeHitAudit:
    return AuthoritativeHitAudit(
        chunk_id=hit.chunk_id,
        dataset_violation=False,
        identity_violation=False,
        entity_violation=False,
        coverage_violation=False,
        authority_violation=False,
        source_violation=False,
        temporal_violation=False,
        version_violation=False,
        section_violation=False,
    )


class _AuditRepository:
    def __init__(
        self,
        *,
        unsafe_chunk: str | None = None,
        ledger_counts: tuple[LedgerCounts, LedgerCounts] = (LedgerCounts(0, 0), LedgerCounts(0, 0)),
        wrong_negative_gate: str | None = None,
        read_only_enforced: bool = True,
    ) -> None:
        self.unsafe_chunk = unsafe_chunk
        self._ledger_counts = iter(ledger_counts)
        self.wrong_negative_gate = wrong_negative_gate
        self.read_only_enforced = read_only_enforced

    async def verify_read_only(self) -> bool:
        return self.read_only_enforced

    async def count_ledgers(self, dataset_version: str) -> LedgerCounts:
        assert dataset_version == DATASET_VERSION
        return next(self._ledger_counts)

    async def audit_hits(self, request: DocumentSearchRequest, hits: tuple[DocumentCandidateHit, ...]) -> tuple[AuthoritativeHitAudit, ...]:
        del request
        return tuple(
            replace(_safe_audit(hit), source_violation=(hit.chunk_id == self.unsafe_chunk))
            for hit in hits
        )

    async def audit_negative(self, dataset: str, probe) -> NegativeMetadataAudit:
        assert dataset == DATASET_VERSION
        return NegativeMetadataAudit(
            chunk_id=probe.chunk_id,
            observed_failing_gates=(self.wrong_negative_gate or probe.expected_failing_gate,),
        )


def _corpus(*, repository=None, auditor=None) -> EvaluationCorpus:
    return EvaluationCorpus(
        repository=repository or _ComparisonRepository(),
        auditor=auditor or _AuditRepository(),
        dataset_version=DATASET_VERSION,
    )


def _catalog_payload() -> dict[str, object]:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def _write_catalog(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_gold_catalog_has_exact_three_canonical_cases() -> None:
    catalog = load_gold_catalog(GOLD_PATH)
    assert catalog.schema_version == 1
    assert tuple(case.id for case in catalog.cases) == EXPECTED_CASE_IDS


@pytest.mark.parametrize(
    "mutation, message",
    (
        (lambda value: value.update(schema_version=True), "schema_version"),
        (lambda value: value["cases"][0].update(id="UNKNOWN"), "case id"),
        (lambda value: value["cases"][0].update(entity_ids="policy-fund-one"), "entity_ids"),
        (lambda value: value["cases"][0].update(section_types=["unknown"]), "section_types"),
        (lambda value: value["cases"][0].update(gold_chunk_ids=[]), "gold_chunk_ids"),
        (lambda value: value["cases"].append(dict(value["cases"][0])), "duplicate"),
    ),
)
def test_gold_catalog_rejects_invalid_schema_ids_types_and_duplicates(tmp_path: Path, mutation, message: str) -> None:
    payload = _catalog_payload()
    mutation(payload)
    with pytest.raises(GoldCatalogError, match=message):
        load_gold_catalog(_write_catalog(tmp_path, payload))


def test_negative_manifest_is_typed_immutable_and_covers_each_gate() -> None:
    assert {probe.category for probe in NEGATIVE_PROBES} == set(EXPECTED_NEGATIVE_GATES)
    assert {probe.category: probe.expected_failing_gate for probe in NEGATIVE_PROBES} == EXPECTED_NEGATIVE_GATES
    assert len({probe.chunk_id for probe in NEGATIVE_PROBES}) == 9
    assert all(probe.entity_ids and probe.section_types and probe.query_text and probe.query_embedding for probe in NEGATIVE_PROBES)
    with pytest.raises(FrozenInstanceError):
        NEGATIVE_PROBES[0].category = "changed"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_fused_is_the_acceptance_gate_and_modes_are_reported_separately() -> None:
    report = await evaluate_cases(_corpus(), load_gold_catalog(GOLD_PATH))
    assert report.database_read_only_enforced is True
    assert "ledger count deltas are diagnostics" in report.evaluation_note
    assert report.case_count == report.gold_in_top5_count == 3
    assert report.mode_gold_in_top5_counts == {"fused": 3, "keyword": 0, "vector": 3}
    assert [(row.case_id, row.mode) for row in report.rows] == sorted((row.case_id, row.mode) for row in report.rows)
    assert report_exit_code(report) == 0
    assert report_exit_code(
        replace(report, database_read_only_enforced=False)
    ) != 0


@pytest.mark.asyncio
async def test_evaluation_refuses_writable_database_boundary_before_search() -> None:
    with pytest.raises(EvaluationConfigurationError, match="read-only"):
        await evaluate_cases(
            _corpus(auditor=_AuditRepository(read_only_enforced=False)),
            load_gold_catalog(GOLD_PATH),
        )


@pytest.mark.asyncio
async def test_authoritative_audit_overrides_candidate_diagnostic_booleans() -> None:
    report = await evaluate_cases(
        _corpus(auditor=_AuditRepository(unsafe_chunk="aerospace-change")),
        load_gold_catalog(GOLD_PATH),
    )
    assert report.source_violation_count == 2
    assert report_exit_code(report) != 0

    self_reported_false = _hit("diagnostic-only", entity_id="selected-etf", section_type=SectionType.RISK_FACTOR, publisher_approved=False)
    audits = await _AuditRepository().audit_hits(
        DocumentSearchRequest(
            dataset_version=DATASET_VERSION,
            entity_ids=("selected-etf",),
            claim_type="product_risk_factor",
            section_types=(SectionType.RISK_FACTOR,),
            cutoff_date=date(2026, 8, 24),
        ),
        (self_reported_false,),
    )
    assert audits[0].source_violation is False


@pytest.mark.asyncio
async def test_returned_hit_cannot_borrow_authority_from_another_entity() -> None:
    chunk_id = "mixed-authority"
    document_id = f"document-{chunk_id}"
    connection = _ScriptedConnection(
        _QueryResult((_authoritative_row(chunk_id, document_id),)),
        _QueryResult(
            (
                SimpleNamespace(entity_id="selected-etf", binding_role="subject_index"),
                SimpleNamespace(entity_id="other-etf", binding_role="subject_product"),
            )
        ),
        _QueryResult(
            (
                SimpleNamespace(
                    entity_id="other-etf",
                    required_document_role="product_full",
                    coverage_status="indexed",
                    document_id=document_id,
                ),
            )
        ),
        _QueryResult(()),
    )
    request = DocumentSearchRequest(
        dataset_version=DATASET_VERSION,
        entity_ids=("selected-etf", "other-etf"),
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=date(2026, 8, 24),
    )
    candidate = _hit(
        chunk_id,
        entity_id="selected-etf",
        section_type=SectionType.RISK_FACTOR,
    )

    audit = await PostgresSafetyAuditor(None)._audit_hit(  # type: ignore[arg-type]
        connection, request, candidate
    )

    assert audit.entity_violation is False
    assert audit.coverage_violation is True
    assert audit.authority_violation is True


@pytest.mark.asyncio
async def test_wrong_entity_negative_keeps_isolated_diagnostic_authority() -> None:
    chunk_id = "wrong-entity-diagnostic"
    document_id = f"document-{chunk_id}"
    connection = _ScriptedConnection(
        _QueryResult((_authoritative_row(chunk_id, document_id),)),
        _QueryResult(
            (
                SimpleNamespace(entity_id="other-etf", binding_role="subject_product"),
            )
        ),
        _QueryResult(
            (
                SimpleNamespace(
                    entity_id="other-etf",
                    required_document_role="product_full",
                    coverage_status="indexed",
                    document_id=document_id,
                ),
            )
        ),
        _QueryResult(()),
    )
    request = DocumentSearchRequest(
        dataset_version=DATASET_VERSION,
        entity_ids=("selected-etf",),
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=date(2026, 8, 24),
    )

    gates = await PostgresSafetyAuditor(None)._metadata_gates(  # type: ignore[arg-type]
        connection, request, chunk_id
    )

    assert gates == ("entity",)


@pytest.mark.asyncio
async def test_authoritative_auditor_treats_whitespace_version_as_unknown() -> None:
    chunk_id = "whitespace-version"
    document_id = f"document-{chunk_id}"
    connection = _ScriptedConnection(
        _QueryResult(
            (
                {
                    **_authoritative_row(chunk_id, document_id),
                    "document_version": " \t ",
                },
            )
        ),
        _QueryResult(
            (
                SimpleNamespace(
                    entity_id="selected-etf",
                    binding_role="subject_product",
                ),
            )
        ),
        _QueryResult(
            (
                SimpleNamespace(
                    entity_id="selected-etf",
                    required_document_role="product_summary",
                    coverage_status="indexed",
                    document_id=document_id,
                ),
            )
        ),
        _QueryResult(()),
    )
    request = DocumentSearchRequest(
        dataset_version=DATASET_VERSION,
        entity_ids=("selected-etf",),
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=date(2026, 8, 24),
    )

    gates = await PostgresSafetyAuditor(None)._metadata_gates(  # type: ignore[arg-type]
        connection, request, chunk_id
    )

    assert gates == ("version",)


@pytest.mark.asyncio
async def test_superseder_cannot_borrow_authority_from_another_entity() -> None:
    superseder_id = "document-mixed-superseder"
    connection = _ScriptedConnection(
        _QueryResult(
            (
                {
                    **_authoritative_row("unused", superseder_id),
                    "document_id": superseder_id,
                },
            )
        ),
        _QueryResult(
            (
                SimpleNamespace(entity_id="selected-etf", binding_role="subject_index"),
                SimpleNamespace(entity_id="other-etf", binding_role="subject_product"),
            )
        ),
        _QueryResult(
            (
                SimpleNamespace(
                    entity_id="other-etf",
                    required_document_role="product_full",
                    coverage_status="indexed",
                    document_id=superseder_id,
                ),
            )
        ),
    )
    request = DocumentSearchRequest(
        dataset_version=DATASET_VERSION,
        entity_ids=("selected-etf", "other-etf"),
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=date(2026, 8, 24),
    )

    superseded = await _has_eligible_superseder(
        connection,
        request,
        "document-original",
        frozenset({"selected-etf"}),
    )

    assert superseded is False


@pytest.mark.asyncio
async def test_negative_probes_are_searched_and_have_exact_authoritative_reasons() -> None:
    report = await evaluate_cases(_corpus(), load_gold_catalog(GOLD_PATH))
    assert len(report.negative_dispositions) == 9
    assert report.negative_gate_failure_count == 0
    assert all(item.keyword_absent and item.vector_absent for item in report.negative_dispositions)
    assert {item.category: (item.disposition, item.reason, item.observed_failing_gates) for item in report.negative_dispositions} == {
        category: ("excluded", gate, (gate,)) for category, gate in EXPECTED_NEGATIVE_GATES.items()
    }


@pytest.mark.asyncio
async def test_negative_probe_fails_when_retrieved_or_metadata_reason_differs() -> None:
    retrieved = await evaluate_cases(
        _corpus(repository=_ComparisonRepository(return_negative="late-near")),
        load_gold_catalog(GOLD_PATH),
    )
    wrong_reason = await evaluate_cases(
        _corpus(auditor=_AuditRepository(wrong_negative_gate="identity")),
        load_gold_catalog(GOLD_PATH),
    )
    assert retrieved.negative_gate_failure_count >= 1
    assert wrong_reason.negative_gate_failure_count >= 1
    assert report_exit_code(retrieved) != 0
    assert report_exit_code(wrong_reason) != 0


@pytest.mark.asyncio
async def test_concurrent_ledger_deltas_are_diagnostic_and_do_not_fail() -> None:
    report = await evaluate_cases(
        _corpus(
            auditor=_AuditRepository(
                ledger_counts=(LedgerCounts(4, 7), LedgerCounts(5, 5))
            )
        ),
        load_gold_catalog(GOLD_PATH),
    )
    assert report.relationship_count_before == 4
    assert report.relationship_count_after == 5
    assert report.relationship_count_delta == 1
    assert report.relationships_created == 0
    assert report.evidence_count_before == 7
    assert report.evidence_count_after == 5
    assert report.evidence_count_delta == -2
    assert report.evidence_created == 0
    assert not hasattr(report, "ledger_mutation_violation_count")
    assert report_exit_code(report) == 0


@pytest.fixture
def ignored_output_dir() -> Path:
    path = PROJECT_ROOT / "tmp" / f"task7-output-{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path)


def test_output_policy_refuses_aliases_and_nonregular_targets(ignored_output_dir: Path) -> None:
    directory = ignored_output_dir / "directory.json"
    directory.mkdir()
    symlink = ignored_output_dir / "symlink.json"
    symlink.symlink_to(GOLD_PATH)
    hardlink = ignored_output_dir / "hardlink.json"
    os.link(GOLD_PATH, hardlink)
    tracked_hardlink = ignored_output_dir / "tracked-hardlink.md"
    os.link(PROJECT_ROOT / "docs/planning/STATUS.md", tracked_hardlink)
    for target in (GOLD_PATH, directory, symlink, hardlink, tracked_hardlink):
        with pytest.raises(OutputPolicyError):
            validate_output_path(target, PROJECT_ROOT, GOLD_PATH)


def test_output_policy_refuses_tracked_nonignored_and_outside_paths(tmp_path: Path) -> None:
    for target in (
        PROJECT_ROOT / "docs/planning/STATUS.md",
        PROJECT_ROOT / "untracked-report.json",
        tmp_path / "outside.json",
    ):
        with pytest.raises(OutputPolicyError):
            validate_output_path(target, PROJECT_ROOT, GOLD_PATH)


def test_atomic_report_write_is_deterministic(ignored_output_dir: Path) -> None:
    first = ignored_output_dir / "first.json"
    second = ignored_output_dir / "second.json"
    payload = {"z": [2, 1], "a": "value"}
    write_report_atomically(first, payload)
    write_report_atomically(second, payload)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8") == '{\n  "a": "value",\n  "z": [\n    2,\n    1\n  ]\n}\n'


def test_atomic_report_write_preserves_prior_file_on_write_and_replace_failure(ignored_output_dir: Path) -> None:
    output = ignored_output_dir / "report.json"
    output.write_text("prior\n", encoding="utf-8")

    def short_write(fd: int, data: bytes) -> None:
        os.write(fd, data[:3])

    def failed_replace(source, destination) -> None:
        raise OSError("replace failed")

    with pytest.raises(OSError):
        write_report_atomically(output, {"new": True}, write_all=short_write)
    assert output.read_text(encoding="utf-8") == "prior\n"
    assert not tuple(ignored_output_dir.glob(".report.json.*.tmp"))
    with pytest.raises(OSError):
        write_report_atomically(output, {"new": True}, replace=failed_replace)
    assert output.read_text(encoding="utf-8") == "prior\n"
    assert not tuple(ignored_output_dir.glob(".report.json.*.tmp"))


def test_cli_validates_gold_and_output_before_database_access(ignored_output_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    database_accessed = False

    async def forbidden_run(*args, **kwargs):
        nonlocal database_accessed
        database_accessed = True
        raise AssertionError("database must not be accessed")

    monkeypatch.setattr("scripts.verify_document_retrieval_pipeline._run", forbidden_run)
    invalid_gold = ignored_output_dir / "invalid-gold.json"
    invalid_gold.write_text("not json", encoding="utf-8")
    secret = "raw-password-must-not-appear"
    output = ignored_output_dir / "report.json"
    common = ["--database-url", f"postgresql+psycopg://user:{secret}@db.invalid/secret_db"]
    invalid_gold_exit = main([*common, "--gold", str(invalid_gold), "--output", str(output)])
    invalid_output_exit = main([*common, "--gold", str(GOLD_PATH), "--output", str(GOLD_PATH)])
    captured = capsys.readouterr()
    assert invalid_gold_exit == invalid_output_exit == 2
    assert database_accessed is False
    assert secret not in captured.err
    assert str(invalid_gold) not in captured.err
    assert str(GOLD_PATH) not in captured.err


@pytest.mark.asyncio
async def test_run_constructs_a_read_only_verifier_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def reject_engine_creation(config: DatabaseConfig, **kwargs: object):
        captured.update(config=config, **kwargs)
        raise RuntimeError("stop after engine construction contract")

    monkeypatch.setattr(
        "scripts.verify_document_retrieval_pipeline.create_database_engine",
        reject_engine_creation,
    )

    with pytest.raises(RuntimeError, match="engine construction contract"):
        await _run(
            "postgresql+psycopg://user:password@db.invalid/test",
            load_gold_catalog(GOLD_PATH),
        )

    assert captured["read_only"] is True


@pytest.fixture(scope="session")
def postgres_database_url() -> str:
    database_url = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail("FINANCIAL_AGENT_TEST_DATABASE_URL is required for @pytest.mark.postgres tests.")
    return database_url


@pytest.fixture(scope="session")
def migrated_database_url(postgres_database_url: str) -> str:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_database_url)
    command.upgrade(config, "head")
    return postgres_database_url


@pytest_asyncio.fixture
async def read_only_evaluation_engine(
    migrated_database_url: str,
) -> AsyncEngine:
    engine = create_database_engine(
        DatabaseConfig(
            url=migrated_database_url,
            application_name="document-retrieval-evaluation-test",
        ),
        read_only=True,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def loaded_document_corpus(
    migrated_database_url: str,
    read_only_evaluation_engine: AsyncEngine,
) -> EvaluationCorpus:
    dataset_version = f"{DATASET_VERSION}-eval-{uuid4().hex}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_document_search_corpus(connection, dataset_version=dataset_version, include_evaluation_fixtures=True)
    yield EvaluationCorpus(
        repository=DocumentCandidateRepository(read_only_evaluation_engine),
        auditor=PostgresSafetyAuditor(read_only_evaluation_engine),
        dataset_version=dataset_version,
    )


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    (
        "INSERT INTO relation.relation_record (dataset_version) VALUES ('read-only-probe')",
        "UPDATE relation.relation_record SET predicate_id = predicate_id WHERE FALSE",
        "DELETE FROM evidence.evidence_record WHERE FALSE",
    ),
)
async def test_evaluation_engine_rejects_insert_update_and_delete(
    read_only_evaluation_engine: AsyncEngine,
    statement: str,
) -> None:
    assert await PostgresSafetyAuditor(
        read_only_evaluation_engine
    ).verify_read_only()
    async with read_only_evaluation_engine.connect() as connection:
        with pytest.raises(sa.exc.DBAPIError) as caught:
            await connection.execute(sa.text(statement))

    assert getattr(caught.value.orig, "sqlstate", None) == "25006"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_phase0_document_cases_pass_top5_negative_and_no_write_gates(loaded_document_corpus: EvaluationCorpus) -> None:
    report = await evaluate_cases(loaded_document_corpus, load_gold_catalog(GOLD_PATH))
    assert report.database_read_only_enforced is True
    assert report.case_count == report.gold_in_top5_count == 3
    assert report.mode_gold_in_top5_counts["fused"] == 3
    assert report.entity_violation_count == 0
    assert report.source_violation_count == 0
    assert report.temporal_violation_count == 0
    assert report.version_violation_count == 0
    assert report.negative_gate_failure_count == 0
    assert len(report.negative_dispositions) == 9
    assert report.relationships_created == 0
    assert report.evidence_created == 0
    assert report.relationship_count_delta == 0
    assert report.evidence_count_delta == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_authoritative_auditor_rejects_eligible_superseded_document(
    loaded_document_corpus: EvaluationCorpus,
) -> None:
    request = DocumentSearchRequest(
        dataset_version=loaded_document_corpus.dataset_version,
        entity_ids=("superseded-etf",),
        claim_type="product_risk_factor",
        section_types=(SectionType.RISK_FACTOR,),
        cutoff_date=date(2026, 8, 24),
    )
    candidate = _hit(
        "superseded-risk",
        dataset_version=loaded_document_corpus.dataset_version,
        entity_id="superseded-etf",
        section_type=SectionType.RISK_FACTOR,
    )
    audits = await loaded_document_corpus.auditor.audit_hits(request, (candidate,))

    assert len(audits) == 1
    assert audits[0].version_violation is True
    assert sum(
        getattr(audits[0], name)
        for name in (
            "dataset_violation",
            "identity_violation",
            "entity_violation",
            "coverage_violation",
            "authority_violation",
            "source_violation",
            "temporal_violation",
            "section_violation",
        )
    ) == 0
