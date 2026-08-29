from __future__ import annotations

from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.db.preflight import normalize_psycopg_url
from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import (
    DocumentCandidateHit,
    DocumentCandidateRepository,
    DocumentSearchRequest,
)
from scripts.verify_document_retrieval_pipeline import (
    EvaluationCorpus,
    GoldCatalogError,
    OutputPolicyError,
    evaluate_cases,
    load_gold_catalog,
    main,
    report_exit_code,
    validate_output_path,
)
from tests.fixtures.document_corpus import (
    DATASET_VERSION,
    insert_document_search_corpus,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = PROJECT_ROOT / "tests/gold/document_retrieval_cases.json"
EXPECTED_CASE_IDS = (
    "DOC-FUND-001-structure",
    "REL-CORP-001-risk",
    "REL-THEME-001-history",
)
EXPECTED_NEGATIVE_CHUNK_IDS = frozenset(
    {
        "wrong-near",
        "wrong-authority-near",
        "unofficial-near",
        "late-near",
        "expired-near",
        "theme-name-only",
        "generic-commentary",
        "performance-near",
        "generated-summary",
    }
)
EXPECTED_GOLD_CHUNK_IDS = frozenset(
    {"policy-structure", "aerospace-change", "selected-etf-risk"}
)
EXPECTED_CORPUS_CHUNK_IDS = EXPECTED_NEGATIVE_CHUNK_IDS | EXPECTED_GOLD_CHUNK_IDS


def _hit(
    chunk_id: str,
    *,
    entity_id: str,
    section_type: SectionType,
    keyword_rank: int | None = None,
    vector_rank: int | None = None,
    publisher_approved: bool = True,
    available_at: datetime = datetime(2026, 8, 2, tzinfo=UTC),
    effective_to: date | None = None,
    cutoff_eligible: bool = True,
) -> DocumentCandidateHit:
    return DocumentCandidateHit(
        dataset_version=DATASET_VERSION,
        entity_id=entity_id,
        document_id=f"document-{chunk_id}",
        chunk_id=chunk_id,
        section_type=section_type,
        exact_text=f"Synthetic exact text for {chunk_id}.",
        source_id="source-approved",
        source_locator=f"synthetic/source#{chunk_id}",
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        available_at=available_at,
        effective_from=date(2026, 8, 1),
        effective_to=effective_to,
        document_version="2026-08-01",
        cutoff_eligible=cutoff_eligible,
        publisher_approved=publisher_approved,
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
        fused_score=None,
        evidence_id=None,
    )


class _DeterministicRepository:
    async def search_keyword(
        self, request: DocumentSearchRequest, query_text: str
    ) -> tuple[DocumentCandidateHit, ...]:
        del query_text
        return self._hits(request, "keyword")

    async def search_vector(
        self, request: DocumentSearchRequest
    ) -> tuple[DocumentCandidateHit, ...]:
        return self._hits(request, "vector")

    def _hits(
        self, request: DocumentSearchRequest, mode: str
    ) -> tuple[DocumentCandidateHit, ...]:
        gold = {
            "policy-fund-one": ("policy-structure", SectionType.LEGAL_STRUCTURE),
            "aerospace-index-one": ("aerospace-change", SectionType.CHANGE_HISTORY),
            "selected-etf": ("selected-etf-risk", SectionType.RISK_FACTOR),
        }
        chunk_id, section_type = gold[request.entity_ids[0]]
        rank = {"keyword_rank": 1} if mode == "keyword" else {"vector_rank": 1}
        return (_hit(chunk_id, entity_id=request.entity_ids[0], section_type=section_type, **rank),)


class _UnsafeRepository(_DeterministicRepository):
    def _hits(
        self, request: DocumentSearchRequest, mode: str
    ) -> tuple[DocumentCandidateHit, ...]:
        rank = {"keyword_rank": 1} if mode == "keyword" else {"vector_rank": 1}
        if request.entity_ids == ("selected-etf",):
            return (
                _hit(
                    "wrong-product",
                    entity_id="other-etf",
                    section_type=SectionType.RISK_FACTOR,
                    publisher_approved=False,
                    available_at=datetime(2026, 8, 25, tzinfo=UTC),
                    effective_to=date(2026, 8, 23),
                    cutoff_eligible=False,
                    **rank,
                ),
            )
        return super()._hits(request, mode)


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
    assert len(catalog.cases) == 3


@pytest.mark.parametrize(
    "mutation, message",
    (
        (lambda value: value.update(schema_version=2), "schema_version"),
        (lambda value: value.update(schema_version=True), "schema_version"),
        (lambda value: value["cases"][0].update(id="UNKNOWN"), "case id"),
        (lambda value: value["cases"][0].update(entity_ids="policy-fund-one"), "entity_ids"),
        (lambda value: value["cases"][0].update(section_types=["unknown"]), "section_types"),
        (lambda value: value["cases"][0].update(gold_chunk_ids=[]), "gold_chunk_ids"),
        (lambda value: value["cases"].append(dict(value["cases"][0])), "duplicate"),
    ),
)
def test_gold_catalog_rejects_invalid_schema_ids_types_and_duplicates(
    tmp_path: Path, mutation, message: str
) -> None:
    payload = _catalog_payload()
    mutation(payload)

    with pytest.raises(GoldCatalogError, match=message):
        load_gold_catalog(_write_catalog(tmp_path, payload))


def test_gold_catalog_normalizes_case_order_deterministically(tmp_path: Path) -> None:
    payload = _catalog_payload()
    payload["cases"] = list(reversed(payload["cases"]))

    catalog = load_gold_catalog(_write_catalog(tmp_path, payload))

    assert tuple(case.id for case in catalog.cases) == EXPECTED_CASE_IDS


@pytest.mark.asyncio
async def test_report_is_sorted_and_requires_gold_in_each_modes_top5() -> None:
    catalog = load_gold_catalog(GOLD_PATH)
    report = await evaluate_cases(
        EvaluationCorpus(
            repository=_DeterministicRepository(),
            dataset_version=DATASET_VERSION,
            available_chunk_ids=EXPECTED_CORPUS_CHUNK_IDS,
        ),
        catalog,
    )

    assert report.case_count == 3
    assert report.gold_in_top5_count == 3
    assert [(row.case_id, row.mode) for row in report.rows] == sorted(
        (row.case_id, row.mode) for row in report.rows
    )
    assert {row.mode for row in report.rows} == {"keyword", "vector", "fused"}
    assert all(row.gold_rank == 1 for row in report.rows)
    assert report.relationships_created == 0
    assert report.corpus_coverage_counts == {
        "corpus_chunk_count": 12,
        "expected_gold_fixture_count": 3,
        "present_gold_fixture_count": 3,
        "missing_gold_fixture_count": 0,
        "expected_negative_fixture_count": 9,
        "present_negative_fixture_count": 9,
        "missing_negative_fixture_count": 0,
        "expected_negative_category_count": 8,
        "covered_negative_category_count": 8,
        "missing_negative_category_count": 0,
    }
    assert report_exit_code(report) == 0


@pytest.mark.asyncio
async def test_absent_gold_has_null_rank_and_fails_the_gate() -> None:
    report = await evaluate_cases(
        EvaluationCorpus(
            repository=_UnsafeRepository(),
            dataset_version=DATASET_VERSION,
            available_chunk_ids=EXPECTED_CORPUS_CHUNK_IDS,
        ),
        load_gold_catalog(GOLD_PATH),
    )
    risk_rows = [row for row in report.rows if row.case_id == "REL-CORP-001-risk"]

    assert all(row.gold_rank is None for row in risk_rows)
    assert report.gold_in_top5_count == 2
    assert report.entity_violation_count == 3
    assert report.source_violation_count == 3
    assert report.temporal_violation_count == 3
    assert report.version_violation_count == 3
    assert report_exit_code(report) != 0


@pytest.mark.asyncio
async def test_missing_negative_fixture_coverage_fails_without_using_search_miss() -> None:
    report = await evaluate_cases(
        EvaluationCorpus(
            repository=_DeterministicRepository(),
            dataset_version=DATASET_VERSION,
            available_chunk_ids=EXPECTED_CORPUS_CHUNK_IDS - {"generated-summary"},
        ),
        load_gold_catalog(GOLD_PATH),
    )

    assert report.corpus_coverage_counts["missing_negative_fixture_count"] == 1
    assert report_exit_code(report) != 0


def test_output_policy_refuses_tracked_and_nonignored_paths(tmp_path: Path) -> None:
    with pytest.raises(OutputPolicyError, match="tracked"):
        validate_output_path(PROJECT_ROOT / "docs/planning/STATUS.md", PROJECT_ROOT)
    with pytest.raises(OutputPolicyError, match="ignored"):
        validate_output_path(PROJECT_ROOT / "untracked-report.json", PROJECT_ROOT)
    with pytest.raises(OutputPolicyError, match="working tree"):
        validate_output_path(tmp_path / "outside.json", PROJECT_ROOT)


def test_output_policy_accepts_only_ignored_report_path() -> None:
    output = PROJECT_ROOT / "tmp/document-retrieval-report.json"

    assert validate_output_path(output, PROJECT_ROOT) == output.resolve()


def test_cli_refuses_tracked_output_without_disclosing_database_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "raw-password-must-not-appear"

    exit_code = main(
        [
            "--database-url",
            f"postgresql+psycopg://user:{secret}@db.invalid/financial_agent",
            "--gold",
            str(GOLD_PATH),
            "--output",
            str(PROJECT_ROOT / "docs/planning/STATUS.md"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code != 0
    assert captured.out == ""
    assert captured.err.strip() == "DOCUMENT_RETRIEVAL_OUTPUT_POLICY_ERROR"
    assert secret not in captured.err


@pytest.mark.asyncio
async def test_report_serialization_states_fixture_vector_quality_boundary() -> None:
    report = await evaluate_cases(
        EvaluationCorpus(
            repository=_DeterministicRepository(),
            dataset_version=DATASET_VERSION,
            available_chunk_ids=EXPECTED_CORPUS_CHUNK_IDS,
        ),
        load_gold_catalog(GOLD_PATH),
    )
    payload = report.as_json_object()

    assert payload["evaluation_note"] == (
        "Deterministic fixture vectors validate retrieval pipeline safety; "
        "they do not measure or approve production embedding-model quality."
    )
    assert "database_url" not in payload


@pytest.fixture(scope="session")
def postgres_database_url() -> str:
    database_url = os.getenv("FINANCIAL_AGENT_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail(
            "FINANCIAL_AGENT_TEST_DATABASE_URL is required for @pytest.mark.postgres "
            "tests. Provide a dedicated non-production PostgreSQL 15 database URL."
        )
    return database_url


@pytest.fixture(scope="session")
def migrated_database_url(postgres_database_url: str) -> str:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_database_url)
    command.upgrade(config, "head")
    return postgres_database_url


@pytest_asyncio.fixture
async def loaded_document_corpus(
    migrated_database_url: str,
) -> EvaluationCorpus:
    dataset_version = f"{DATASET_VERSION}-eval-{uuid4().hex}"
    with psycopg.connect(normalize_psycopg_url(migrated_database_url)) as connection:
        insert_document_search_corpus(
            connection,
            dataset_version=dataset_version,
            include_evaluation_fixtures=True,
        )
        available_chunk_ids = frozenset(
            row[0]
            for row in connection.execute(
                "SELECT chunk_id FROM document.document_chunk WHERE dataset_version = %s",
                (dataset_version,),
            ).fetchall()
        )
    engine = create_async_engine(migrated_database_url, pool_size=5, max_overflow=0)
    yield EvaluationCorpus(
        repository=DocumentCandidateRepository(engine),
        dataset_version=dataset_version,
        available_chunk_ids=available_chunk_ids,
    )
    await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_phase0_document_cases_pass_top5_and_safety_gates(
    loaded_document_corpus: EvaluationCorpus,
) -> None:
    report = await evaluate_cases(loaded_document_corpus, load_gold_catalog(GOLD_PATH))

    assert report.case_count == 3
    assert report.gold_in_top5_count == 3
    assert report.entity_violation_count == 0
    assert report.source_violation_count == 0
    assert report.temporal_violation_count == 0
    assert report.version_violation_count == 0
    assert report.relationships_created == 0
    assert report.corpus_coverage_counts["missing_negative_fixture_count"] == 0
