#!/usr/bin/env python3
"""Verify deterministic Phase 0 document retrieval without creating records."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
from typing import Protocol
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.config import DatabaseConfig
from financial_agent.db.engine import create_database_engine
from financial_agent.db.schema.document import document_chunk
from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import (
    DocumentCandidateHit,
    DocumentCandidateRepository,
    DocumentSearchRequest,
    reciprocal_rank_fusion,
)


SCHEMA_VERSION = 1
DATASET_PREFIX = "document-search-v1"
MODEL_ID = "synthetic-embedding"
MODEL_VERSION = "1"
CUTOFF_DATE = date(2026, 8, 24)
TOP_K = 5
EVALUATION_NOTE = (
    "Deterministic fixture vectors validate retrieval pipeline safety; "
    "they do not measure or approve production embedding-model quality."
)
_SEOUL = ZoneInfo("Asia/Seoul")
_EXPECTED_CASES = {
    "DOC-FUND-001-structure": {
        "entity_ids": ("policy-fund-one",),
        "claim_type": "structure",
        "section_types": (SectionType.LEGAL_STRUCTURE,),
        "gold_chunk_ids": ("policy-structure",),
        "query_text": "policy fund structure",
        "query_embedding": (0.0, 0.0, 1.0),
    },
    "REL-CORP-001-risk": {
        "entity_ids": ("selected-etf",),
        "claim_type": "product_risk_factor",
        "section_types": (SectionType.RISK_FACTOR,),
        "gold_chunk_ids": ("selected-etf-risk",),
        "query_text": "selected etf product risk factor",
        "query_embedding": (1.0, 0.0, 0.0),
    },
    "REL-THEME-001-history": {
        "entity_ids": ("aerospace-index-one",),
        "claim_type": "theme_relation_evidence_span",
        "section_types": (SectionType.THEME_DEFINITION, SectionType.CHANGE_HISTORY),
        "gold_chunk_ids": ("aerospace-change",),
        "query_text": "aerospace theme change",
        "query_embedding": (0.0, 1.0, 0.0),
    },
}
_NEGATIVE_FIXTURES = {
    "wrong_product": frozenset({"wrong-near"}),
    "wrong_or_unofficial_authority": frozenset(
        {"wrong-authority-near", "unofficial-near"}
    ),
    "after_cutoff": frozenset({"late-near"}),
    "stale_version": frozenset({"expired-near"}),
    "name_only_theme_match": frozenset({"theme-name-only"}),
    "generic_commentary": frozenset({"generic-commentary"}),
    "performance_table": frozenset({"performance-near"}),
    "generated_summary": frozenset({"generated-summary"}),
}
_NEGATIVE_FIXTURE_CHUNK_IDS = frozenset(
    chunk_id for chunk_ids in _NEGATIVE_FIXTURES.values() for chunk_id in chunk_ids
)
_CASE_KEYS = frozenset(
    {"id", "entity_ids", "claim_type", "section_types", "gold_chunk_ids"}
)


class GoldCatalogError(ValueError):
    pass


class OutputPolicyError(ValueError):
    pass


class EvaluationConfigurationError(RuntimeError):
    pass


class CandidateRepository(Protocol):
    async def search_keyword(
        self, request: DocumentSearchRequest, query_text: str
    ) -> tuple[DocumentCandidateHit, ...]: ...

    async def search_vector(
        self, request: DocumentSearchRequest
    ) -> tuple[DocumentCandidateHit, ...]: ...


@dataclass(frozen=True, slots=True)
class GoldCase:
    id: str
    entity_ids: tuple[str, ...]
    claim_type: str
    section_types: tuple[SectionType, ...]
    gold_chunk_ids: tuple[str, ...]
    query_text: str
    query_embedding: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class GoldCatalog:
    schema_version: int
    cases: tuple[GoldCase, ...]


@dataclass(frozen=True, slots=True)
class EvaluationCorpus:
    repository: CandidateRepository
    dataset_version: str
    available_chunk_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class EvaluationRow:
    case_id: str
    mode: str
    top_5_chunk_ids: tuple[str, ...]
    gold_rank: int | None
    entity_violation_count: int
    source_violation_count: int
    temporal_violation_count: int
    version_violation_count: int


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    schema_version: int
    dataset_version: str
    evaluation_note: str
    case_count: int
    gold_in_top5_count: int
    entity_violation_count: int
    source_violation_count: int
    temporal_violation_count: int
    version_violation_count: int
    relationships_created: int
    corpus_coverage_counts: dict[str, int]
    rows: tuple[EvaluationRow, ...]

    def as_json_object(self) -> dict[str, object]:
        value = asdict(self)
        value["rows"] = [
            {
                **asdict(row),
                "top_5_chunk_ids": list(row.top_5_chunk_ids),
            }
            for row in self.rows
        ]
        return value


def load_gold_catalog(path: Path) -> GoldCatalog:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GoldCatalogError("gold catalog is not readable JSON") from error
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "cases"}:
        raise GoldCatalogError("gold catalog has invalid schema keys")
    if (
        type(raw["schema_version"]) is not int
        or raw["schema_version"] != SCHEMA_VERSION
    ):
        raise GoldCatalogError("schema_version must be 1")
    if not isinstance(raw["cases"], list):
        raise GoldCatalogError("cases must be a list")

    case_ids: list[str] = []
    parsed: list[GoldCase] = []
    for raw_case in raw["cases"]:
        if not isinstance(raw_case, dict) or set(raw_case) != _CASE_KEYS:
            raise GoldCatalogError("case has invalid schema keys")
        case_id = raw_case["id"]
        if not isinstance(case_id, str) or case_id not in _EXPECTED_CASES:
            raise GoldCatalogError("case id is not canonical")
        if case_id in case_ids:
            raise GoldCatalogError("duplicate case id")
        case_ids.append(case_id)
        expected = _EXPECTED_CASES[case_id]
        entity_ids = _string_tuple(raw_case["entity_ids"], "entity_ids")
        section_values = _string_tuple(raw_case["section_types"], "section_types")
        gold_chunk_ids = _string_tuple(raw_case["gold_chunk_ids"], "gold_chunk_ids")
        try:
            section_types = tuple(SectionType(value) for value in section_values)
        except ValueError as error:
            raise GoldCatalogError("section_types contain an unknown value") from error
        claim_type = raw_case["claim_type"]
        if not isinstance(claim_type, str) or not claim_type.strip():
            raise GoldCatalogError("claim_type must be a nonblank string")
        if (
            entity_ids != expected["entity_ids"]
            or claim_type != expected["claim_type"]
            or section_types != expected["section_types"]
            or gold_chunk_ids != expected["gold_chunk_ids"]
        ):
            raise GoldCatalogError(f"canonical case contract differs for {case_id}")
        parsed.append(
            GoldCase(
                id=case_id,
                entity_ids=entity_ids,
                claim_type=claim_type,
                section_types=section_types,
                gold_chunk_ids=gold_chunk_ids,
                query_text=expected["query_text"],
                query_embedding=expected["query_embedding"],
            )
        )
    if set(case_ids) != set(_EXPECTED_CASES) or len(case_ids) != 3:
        raise GoldCatalogError("gold catalog must contain the three canonical cases")
    return GoldCatalog(SCHEMA_VERSION, tuple(sorted(parsed, key=lambda case: case.id)))


async def evaluate_cases(
    corpus: EvaluationCorpus, catalog: GoldCatalog
) -> EvaluationReport:
    rows: list[EvaluationRow] = []
    passed_cases = 0
    for case in catalog.cases:
        request = DocumentSearchRequest(
            dataset_version=corpus.dataset_version,
            entity_ids=case.entity_ids,
            claim_type=case.claim_type,
            section_types=case.section_types,
            cutoff_date=CUTOFF_DATE,
            top_k=TOP_K,
            query_embedding=case.query_embedding,
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
        )
        keyword_hits = await corpus.repository.search_keyword(request, case.query_text)
        vector_hits = await corpus.repository.search_vector(request)
        fused_hits = reciprocal_rank_fusion(keyword_hits, vector_hits, top_k=TOP_K)
        case_rows = tuple(
            _evaluate_row(case, mode, hits, request)
            for mode, hits in (
                ("keyword", keyword_hits),
                ("vector", vector_hits),
                ("fused", fused_hits),
            )
        )
        rows.extend(case_rows)
        if all(row.gold_rank is not None for row in case_rows):
            passed_cases += 1

    ordered_rows = tuple(sorted(rows, key=lambda row: (row.case_id, row.mode)))
    expected_gold_chunk_ids = frozenset(
        chunk_id for case in catalog.cases for chunk_id in case.gold_chunk_ids
    )
    missing_gold_count = len(expected_gold_chunk_ids - corpus.available_chunk_ids)
    missing_negative_count = len(_NEGATIVE_FIXTURE_CHUNK_IDS - corpus.available_chunk_ids)
    covered_negative_category_count = sum(
        chunk_ids <= corpus.available_chunk_ids
        for chunk_ids in _NEGATIVE_FIXTURES.values()
    )
    return EvaluationReport(
        schema_version=SCHEMA_VERSION,
        dataset_version=corpus.dataset_version,
        evaluation_note=EVALUATION_NOTE,
        case_count=len(catalog.cases),
        gold_in_top5_count=passed_cases,
        entity_violation_count=sum(row.entity_violation_count for row in ordered_rows),
        source_violation_count=sum(row.source_violation_count for row in ordered_rows),
        temporal_violation_count=sum(
            row.temporal_violation_count for row in ordered_rows
        ),
        version_violation_count=sum(row.version_violation_count for row in ordered_rows),
        relationships_created=0,
        corpus_coverage_counts={
            "corpus_chunk_count": len(corpus.available_chunk_ids),
            "expected_gold_fixture_count": len(expected_gold_chunk_ids),
            "present_gold_fixture_count": len(expected_gold_chunk_ids)
            - missing_gold_count,
            "missing_gold_fixture_count": missing_gold_count,
            "expected_negative_fixture_count": len(_NEGATIVE_FIXTURE_CHUNK_IDS),
            "present_negative_fixture_count": len(_NEGATIVE_FIXTURE_CHUNK_IDS)
            - missing_negative_count,
            "missing_negative_fixture_count": missing_negative_count,
            "expected_negative_category_count": len(_NEGATIVE_FIXTURES),
            "covered_negative_category_count": covered_negative_category_count,
            "missing_negative_category_count": len(_NEGATIVE_FIXTURES)
            - covered_negative_category_count,
        },
        rows=ordered_rows,
    )


def report_exit_code(report: EvaluationReport) -> int:
    safety_violations = (
        report.entity_violation_count
        + report.source_violation_count
        + report.temporal_violation_count
        + report.version_violation_count
        + report.corpus_coverage_counts["missing_gold_fixture_count"]
        + report.corpus_coverage_counts["missing_negative_fixture_count"]
        + report.corpus_coverage_counts["missing_negative_category_count"]
    )
    if report.gold_in_top5_count != report.case_count or safety_violations:
        return 1
    return 0


def validate_output_path(output: Path, project_root: Path) -> Path:
    root = project_root.resolve()
    resolved = output.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise OutputPolicyError("output must remain inside the Git working tree") from error
    if _git_status(root, "ls-files", "--error-unmatch", "--", str(relative)) == 0:
        raise OutputPolicyError("output path is tracked by Git")
    if _git_status(root, "check-ignore", "-q", "--", str(relative)) != 0:
        raise OutputPolicyError("output path must be ignored by Git")
    return resolved


async def _run(database_url: str, gold_path: Path) -> EvaluationReport:
    engine = create_database_engine(
        DatabaseConfig(
            url=database_url,
            application_name="document-retrieval-verifier",
        )
    )
    try:
        dataset_version, chunk_ids = await _select_synthetic_corpus(engine)
        return await evaluate_cases(
            EvaluationCorpus(
                repository=DocumentCandidateRepository(engine),
                dataset_version=dataset_version,
                available_chunk_ids=chunk_ids,
            ),
            load_gold_catalog(gold_path),
        )
    finally:
        await engine.dispose()


async def _select_synthetic_corpus(engine: AsyncEngine) -> tuple[str, frozenset[str]]:
    required = _NEGATIVE_FIXTURE_CHUNK_IDS | frozenset(
        chunk_id
        for expected in _EXPECTED_CASES.values()
        for chunk_id in expected["gold_chunk_ids"]
    )
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                sa.select(
                    document_chunk.c.dataset_version,
                    document_chunk.c.chunk_id,
                ).where(document_chunk.c.dataset_version.startswith(DATASET_PREFIX))
            )
        ).all()
    by_dataset: dict[str, set[str]] = {}
    for dataset_version, chunk_id in rows:
        by_dataset.setdefault(dataset_version, set()).add(chunk_id)
    complete = sorted(
        dataset_version
        for dataset_version, chunk_ids in by_dataset.items()
        if required <= chunk_ids
    )
    if not complete:
        raise EvaluationConfigurationError("synthetic evaluation corpus is not loaded")
    selected = complete[-1]
    return selected, frozenset(by_dataset[selected])


def _evaluate_row(
    case: GoldCase,
    mode: str,
    hits: tuple[DocumentCandidateHit, ...],
    request: DocumentSearchRequest,
) -> EvaluationRow:
    top_hits = hits[:TOP_K]
    top_ids = tuple(hit.chunk_id for hit in top_hits)
    gold_rank = next(
        (
            rank
            for rank, chunk_id in enumerate(top_ids, start=1)
            if chunk_id in case.gold_chunk_ids
        ),
        None,
    )
    return EvaluationRow(
        case_id=case.id,
        mode=mode,
        top_5_chunk_ids=top_ids,
        gold_rank=gold_rank,
        entity_violation_count=sum(
            hit.entity_id not in request.entity_ids for hit in top_hits
        ),
        source_violation_count=sum(not hit.publisher_approved for hit in top_hits),
        temporal_violation_count=sum(
            _temporal_violation(hit, request.cutoff_date) for hit in top_hits
        ),
        version_violation_count=sum(
            _version_violation(hit, request.cutoff_date) for hit in top_hits
        ),
    )


def _temporal_violation(hit: DocumentCandidateHit, cutoff: date) -> bool:
    return (
        hit.published_at.astimezone(_SEOUL).date() > cutoff
        or hit.available_at.astimezone(_SEOUL).date() > cutoff
        or hit.effective_from > cutoff
        or (hit.effective_to is not None and hit.effective_to < cutoff)
        or not hit.cutoff_eligible
    )


def _version_violation(hit: DocumentCandidateHit, cutoff: date) -> bool:
    return (
        not hit.document_version.strip()
        or not hit.cutoff_eligible
        or (hit.effective_to is not None and hit.effective_to < cutoff)
    )


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise GoldCatalogError(f"{field_name} must be a nonempty string list")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise GoldCatalogError(f"{field_name} must not contain duplicates")
    return result


def _git_status(root: Path, *arguments: str) -> int:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    try:
        output = validate_output_path(arguments.output, project_root)
        report = asyncio.run(_run(arguments.database_url, arguments.gold.resolve()))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                report.as_json_object(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except OutputPolicyError:
        print("DOCUMENT_RETRIEVAL_OUTPUT_POLICY_ERROR", file=sys.stderr)
        return 2
    except (GoldCatalogError, EvaluationConfigurationError):
        print("DOCUMENT_RETRIEVAL_CONFIGURATION_ERROR", file=sys.stderr)
        return 2
    except Exception:
        print("DOCUMENT_RETRIEVAL_VERIFICATION_ERROR", file=sys.stderr)
        return 2
    return report_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
