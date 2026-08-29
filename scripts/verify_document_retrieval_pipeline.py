#!/usr/bin/env python3
"""Verify deterministic Phase 0 document retrieval without creating records."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from financial_agent.db.config import DatabaseConfig
from financial_agent.db.engine import create_database_engine
from financial_agent.db.schema.document import (
    document_chunk,
    document_coverage,
    document_entity_binding,
    document_profile,
    document_record,
)
from financial_agent.db.schema.evidence import evidence_record, source_record
from financial_agent.db.schema.operations import dataset_version
from financial_agent.db.schema.relation import relation_record
from financial_agent.documents import (
    SectionType,
    binding_roles_for_document_role,
    document_types_for_role,
    publisher_roles_for_document_role,
)
from financial_agent.retrieval.documents import (
    DocumentCandidateHit,
    DocumentCandidateRepository,
    DocumentSearchRequest,
    claim_authority_rules,
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
_SEARCHABLE_DATASET_STATUSES = frozenset({"building", "validated", "active"})
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
_CASE_KEYS = frozenset(
    {"id", "entity_ids", "claim_type", "section_types", "gold_chunk_ids"}
)


class GoldCatalogError(ValueError):
    pass


class OutputPolicyError(ValueError):
    pass


class EvaluationConfigurationError(RuntimeError):
    pass


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
class NegativeProbe:
    category: str
    chunk_id: str
    entity_ids: tuple[str, ...]
    claim_type: str
    section_types: tuple[SectionType, ...]
    query_text: str
    query_embedding: tuple[float, ...]
    expected_failing_gate: str

    def request(self, dataset: str) -> DocumentSearchRequest:
        return DocumentSearchRequest(
            dataset_version=dataset,
            entity_ids=self.entity_ids,
            claim_type=self.claim_type,
            section_types=self.section_types,
            cutoff_date=CUTOFF_DATE,
            top_k=TOP_K,
            query_embedding=self.query_embedding,
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
        )


NEGATIVE_PROBES = (
    NegativeProbe("wrong_product", "wrong-near", ("selected-etf",), "product_risk_factor", (SectionType.RISK_FACTOR,), "identical risk", (0.97, 0.03, 0.0), "entity"),
    NegativeProbe("wrong_claim_authority", "wrong-authority-near", ("wrong-publisher-etf",), "product_risk_factor", (SectionType.RISK_FACTOR,), "wrong authority risk", (0.96, 0.04, 0.0), "claim_authority"),
    NegativeProbe("source_ineligible", "unofficial-near", ("unofficial-etf",), "product_risk_factor", (SectionType.RISK_FACTOR,), "unofficial risk", (0.95, 0.05, 0.0), "source_eligibility"),
    NegativeProbe("after_seoul_cutoff", "late-near", ("late-etf",), "product_risk_factor", (SectionType.RISK_FACTOR,), "late risk", (0.94, 0.06, 0.0), "temporal"),
    NegativeProbe("stale_effective_version", "expired-near", ("expired-etf",), "product_risk_factor", (SectionType.RISK_FACTOR,), "expired risk", (0.93, 0.07, 0.0), "version"),
    NegativeProbe("name_only_wrong_entity", "theme-name-only", ("aerospace-index-one",), "theme_relation_evidence_span", (SectionType.THEME_DEFINITION, SectionType.CHANGE_HISTORY), "aerospace name only theme match", (0.0, 0.97, 0.03), "entity"),
    NegativeProbe("generic_commentary", "generic-commentary", ("aerospace-index-one",), "theme_relation_evidence_span", (SectionType.THEME_DEFINITION, SectionType.CHANGE_HISTORY), "generic aerospace market commentary", (0.0, 0.96, 0.04), "section"),
    NegativeProbe("performance_table", "performance-near", ("selected-etf",), "product_risk_factor", (SectionType.RISK_FACTOR,), "performance risk", (0.92, 0.08, 0.0), "section"),
    NegativeProbe("generated_summary", "generated-summary", ("selected-etf",), "product_risk_factor", (SectionType.RISK_FACTOR,), "generated summary risk", (0.91, 0.09, 0.0), "section"),
)


@dataclass(frozen=True, slots=True)
class LedgerCounts:
    relationships: int
    evidence: int


@dataclass(frozen=True, slots=True)
class AuthoritativeHitAudit:
    chunk_id: str
    dataset_violation: bool
    identity_violation: bool
    entity_violation: bool
    coverage_violation: bool
    authority_violation: bool
    source_violation: bool
    temporal_violation: bool
    version_violation: bool
    section_violation: bool


@dataclass(frozen=True, slots=True)
class NegativeMetadataAudit:
    chunk_id: str
    observed_failing_gates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NegativeDisposition:
    category: str
    chunk_id: str
    expected_failing_gate: str
    observed_failing_gates: tuple[str, ...]
    keyword_absent: bool
    vector_absent: bool
    disposition: str
    reason: str


@dataclass(frozen=True, slots=True)
class EvaluationRow:
    case_id: str
    mode: str
    top_5_chunk_ids: tuple[str, ...]
    gold_rank: int | None
    dataset_violation_count: int
    identity_violation_count: int
    entity_violation_count: int
    coverage_violation_count: int
    authority_violation_count: int
    source_violation_count: int
    temporal_violation_count: int
    version_violation_count: int
    section_violation_count: int


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    schema_version: int
    dataset_version: str
    evaluation_note: str
    case_count: int
    gold_in_top5_count: int
    mode_gold_in_top5_counts: dict[str, int]
    dataset_violation_count: int
    identity_violation_count: int
    entity_violation_count: int
    coverage_violation_count: int
    authority_violation_count: int
    source_violation_count: int
    temporal_violation_count: int
    version_violation_count: int
    section_violation_count: int
    negative_gate_failure_count: int
    relationship_count_before: int
    relationship_count_after: int
    relationships_created: int
    evidence_count_before: int
    evidence_count_after: int
    evidence_created: int
    ledger_mutation_violation_count: int
    corpus_coverage_counts: dict[str, int]
    rows: tuple[EvaluationRow, ...]
    negative_dispositions: tuple[NegativeDisposition, ...]

    def as_json_object(self) -> dict[str, object]:
        return asdict(self)


class CandidateRepository(Protocol):
    async def search_keyword(self, request: DocumentSearchRequest, query_text: str) -> tuple[DocumentCandidateHit, ...]: ...
    async def search_vector(self, request: DocumentSearchRequest) -> tuple[DocumentCandidateHit, ...]: ...


class SafetyAuditor(Protocol):
    async def count_ledgers(self, dataset: str) -> LedgerCounts: ...
    async def audit_hits(self, request: DocumentSearchRequest, hits: tuple[DocumentCandidateHit, ...]) -> tuple[AuthoritativeHitAudit, ...]: ...
    async def audit_negative(self, dataset: str, probe: NegativeProbe) -> NegativeMetadataAudit: ...


@dataclass(frozen=True, slots=True)
class EvaluationCorpus:
    repository: CandidateRepository
    auditor: SafetyAuditor
    dataset_version: str


def load_gold_catalog(path: Path) -> GoldCatalog:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GoldCatalogError("gold catalog is not readable JSON") from error
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "cases"}:
        raise GoldCatalogError("gold catalog has invalid schema keys")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != SCHEMA_VERSION:
        raise GoldCatalogError("schema_version must be 1")
    if not isinstance(raw["cases"], list):
        raise GoldCatalogError("cases must be a list")
    parsed: list[GoldCase] = []
    seen: set[str] = set()
    for raw_case in raw["cases"]:
        if not isinstance(raw_case, dict) or set(raw_case) != _CASE_KEYS:
            raise GoldCatalogError("case has invalid schema keys")
        case_id = raw_case["id"]
        if not isinstance(case_id, str) or case_id not in _EXPECTED_CASES:
            raise GoldCatalogError("case id is not canonical")
        if case_id in seen:
            raise GoldCatalogError("duplicate case id")
        seen.add(case_id)
        expected = _EXPECTED_CASES[case_id]
        entity_ids = _string_tuple(raw_case["entity_ids"], "entity_ids")
        sections = _string_tuple(raw_case["section_types"], "section_types")
        gold = _string_tuple(raw_case["gold_chunk_ids"], "gold_chunk_ids")
        try:
            section_types = tuple(SectionType(value) for value in sections)
        except ValueError as error:
            raise GoldCatalogError("section_types contain an unknown value") from error
        if (
            entity_ids != expected["entity_ids"]
            or raw_case["claim_type"] != expected["claim_type"]
            or section_types != expected["section_types"]
            or gold != expected["gold_chunk_ids"]
        ):
            raise GoldCatalogError(f"canonical case contract differs for {case_id}")
        parsed.append(GoldCase(case_id, entity_ids, raw_case["claim_type"], section_types, gold, expected["query_text"], expected["query_embedding"]))
    if seen != set(_EXPECTED_CASES) or len(parsed) != 3:
        raise GoldCatalogError("gold catalog must contain the three canonical cases")
    return GoldCatalog(SCHEMA_VERSION, tuple(sorted(parsed, key=lambda case: case.id)))


async def evaluate_cases(corpus: EvaluationCorpus, catalog: GoldCatalog) -> EvaluationReport:
    before = await corpus.auditor.count_ledgers(corpus.dataset_version)
    rows: list[EvaluationRow] = []
    mode_counts = {"keyword": 0, "vector": 0, "fused": 0}
    for case in catalog.cases:
        request = _case_request(corpus.dataset_version, case)
        keyword = await corpus.repository.search_keyword(request, case.query_text)
        vector = await corpus.repository.search_vector(request)
        fused = reciprocal_rank_fusion(keyword, vector, top_k=TOP_K)
        for mode, hits in (("keyword", keyword), ("vector", vector), ("fused", fused)):
            audits = await corpus.auditor.audit_hits(request, hits[:TOP_K])
            row = _evaluation_row(case, mode, hits, audits)
            rows.append(row)
            if row.gold_rank is not None:
                mode_counts[mode] += 1

    negative_dispositions: list[NegativeDisposition] = []
    for probe in NEGATIVE_PROBES:
        request = probe.request(corpus.dataset_version)
        keyword = await corpus.repository.search_keyword(request, probe.query_text)
        vector = await corpus.repository.search_vector(request)
        metadata = await corpus.auditor.audit_negative(corpus.dataset_version, probe)
        keyword_absent = probe.chunk_id not in {hit.chunk_id for hit in keyword[:TOP_K]}
        vector_absent = probe.chunk_id not in {hit.chunk_id for hit in vector[:TOP_K]}
        reason_matches = metadata.observed_failing_gates == (probe.expected_failing_gate,)
        passed = keyword_absent and vector_absent and reason_matches
        reason = probe.expected_failing_gate if passed else ("unexpected_retrieval" if not keyword_absent or not vector_absent else "metadata_gate_mismatch")
        negative_dispositions.append(
            NegativeDisposition(probe.category, probe.chunk_id, probe.expected_failing_gate, metadata.observed_failing_gates, keyword_absent, vector_absent, "excluded" if passed else "failed", reason)
        )

    after = await corpus.auditor.count_ledgers(corpus.dataset_version)
    ordered_rows = tuple(sorted(rows, key=lambda row: (row.case_id, row.mode)))
    ordered_negatives = tuple(sorted(negative_dispositions, key=lambda item: item.category))
    relationship_delta = after.relationships - before.relationships
    evidence_delta = after.evidence - before.evidence
    return EvaluationReport(
        schema_version=SCHEMA_VERSION,
        dataset_version=corpus.dataset_version,
        evaluation_note=EVALUATION_NOTE,
        case_count=len(catalog.cases),
        gold_in_top5_count=mode_counts["fused"],
        mode_gold_in_top5_counts=dict(sorted(mode_counts.items())),
        dataset_violation_count=_sum_rows(ordered_rows, "dataset_violation_count"),
        identity_violation_count=_sum_rows(ordered_rows, "identity_violation_count"),
        entity_violation_count=_sum_rows(ordered_rows, "entity_violation_count"),
        coverage_violation_count=_sum_rows(ordered_rows, "coverage_violation_count"),
        authority_violation_count=_sum_rows(ordered_rows, "authority_violation_count"),
        source_violation_count=_sum_rows(ordered_rows, "source_violation_count"),
        temporal_violation_count=_sum_rows(ordered_rows, "temporal_violation_count"),
        version_violation_count=_sum_rows(ordered_rows, "version_violation_count"),
        section_violation_count=_sum_rows(ordered_rows, "section_violation_count"),
        negative_gate_failure_count=sum(item.disposition != "excluded" for item in ordered_negatives),
        relationship_count_before=before.relationships,
        relationship_count_after=after.relationships,
        relationships_created=max(0, relationship_delta),
        evidence_count_before=before.evidence,
        evidence_count_after=after.evidence,
        evidence_created=max(0, evidence_delta),
        ledger_mutation_violation_count=int(relationship_delta != 0) + int(evidence_delta != 0),
        corpus_coverage_counts={
            "expected_negative_probe_count": len(NEGATIVE_PROBES),
            "authoritative_metadata_present_count": sum("identity" not in item.observed_failing_gates for item in ordered_negatives),
            "passed_negative_probe_count": sum(item.disposition == "excluded" for item in ordered_negatives),
        },
        rows=ordered_rows,
        negative_dispositions=ordered_negatives,
    )


def report_exit_code(report: EvaluationReport) -> int:
    violations = sum(
        getattr(report, name)
        for name in (
            "dataset_violation_count", "identity_violation_count", "entity_violation_count",
            "coverage_violation_count", "authority_violation_count", "source_violation_count",
            "temporal_violation_count", "version_violation_count", "section_violation_count",
            "negative_gate_failure_count", "ledger_mutation_violation_count",
        )
    )
    return int(report.gold_in_top5_count != report.case_count or violations != 0)


class PostgresSafetyAuditor:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def count_ledgers(self, dataset: str) -> LedgerCounts:
        async with self._engine.connect() as connection:
            relationships = await connection.scalar(sa.select(sa.func.count()).select_from(relation_record).where(relation_record.c.dataset_version == dataset))
            evidence = await connection.scalar(sa.select(sa.func.count()).select_from(evidence_record).where(evidence_record.c.dataset_version == dataset))
        return LedgerCounts(int(relationships or 0), int(evidence or 0))

    async def audit_hits(self, request: DocumentSearchRequest, hits: tuple[DocumentCandidateHit, ...]) -> tuple[AuthoritativeHitAudit, ...]:
        async with self._engine.connect() as connection:
            return tuple([await self._audit_hit(connection, request, hit) for hit in hits])

    async def audit_negative(self, dataset: str, probe: NegativeProbe) -> NegativeMetadataAudit:
        async with self._engine.connect() as connection:
            gates = await self._metadata_gates(connection, probe.request(dataset), probe.chunk_id)
        return NegativeMetadataAudit(probe.chunk_id, gates)

    async def _audit_hit(self, connection: AsyncConnection, request: DocumentSearchRequest, hit: DocumentCandidateHit) -> AuthoritativeHitAudit:
        gates, identity = await self._metadata_gates_with_identity(connection, request, hit.chunk_id, hit)
        return AuthoritativeHitAudit(
            chunk_id=hit.chunk_id,
            dataset_violation="dataset" in gates,
            identity_violation=identity,
            entity_violation="entity" in gates,
            coverage_violation="coverage" in gates,
            authority_violation="claim_authority" in gates,
            source_violation="source_eligibility" in gates,
            temporal_violation="temporal" in gates,
            version_violation="version" in gates,
            section_violation="section" in gates,
        )

    async def _metadata_gates(self, connection: AsyncConnection, request: DocumentSearchRequest, chunk_id: str) -> tuple[str, ...]:
        gates, _ = await self._metadata_gates_with_identity(connection, request, chunk_id, None)
        return gates

    async def _metadata_gates_with_identity(self, connection: AsyncConnection, request: DocumentSearchRequest, chunk_id: str, hit: DocumentCandidateHit | None) -> tuple[tuple[str, ...], bool]:
        row = (await connection.execute(_chunk_metadata_statement(request.dataset_version, chunk_id))).mappings().one_or_none()
        if row is None:
            return ("identity",), True
        identity_violation = hit is not None and (
            hit.dataset_version != request.dataset_version
            or hit.document_id != row["document_id"]
            or hit.source_id != row["source_id"]
            or hit.chunk_id != row["chunk_id"]
        )
        bindings = (await connection.execute(sa.select(document_entity_binding.c.entity_id, document_entity_binding.c.binding_role).where(document_entity_binding.c.dataset_version == request.dataset_version, document_entity_binding.c.document_id == row["document_id"]))).all()
        coverages = (await connection.execute(sa.select(document_coverage.c.entity_id, document_coverage.c.required_document_role, document_coverage.c.coverage_status, document_coverage.c.document_id).where(document_coverage.c.dataset_version == request.dataset_version, document_coverage.c.document_id == row["document_id"]))).all()
        gates: set[str] = set()
        if row["dataset_status"] not in _SEARCHABLE_DATASET_STATUSES or row["dataset_cutoff"] != request.cutoff_date or (hit is not None and hit.dataset_version != request.dataset_version):
            gates.add("dataset")
        raw_entities = {binding.entity_id for binding in bindings}
        requested_entities = raw_entities.intersection(request.entity_ids)
        if not requested_entities or (
            hit is not None and hit.entity_id not in requested_entities
        ):
            gates.add("entity")
        if row["section_type"] not in {section.value for section in request.section_types}:
            gates.add("section")
        authority, coverage = _authority_and_coverage(row, bindings, coverages, request.claim_type)
        if not coverage:
            gates.add("coverage")
        if not authority:
            gates.add("claim_authority")
        if not row["eligible_for_claim"]:
            gates.add("source_eligibility")
        if _metadata_temporal_violation(row, request.cutoff_date):
            gates.add("temporal")
        if (
            not row["document_version"].strip()
            or (
                row["effective_to"] is not None
                and row["effective_to"] < request.cutoff_date
            )
            or await _has_eligible_superseder(
                connection, request, row["document_id"]
            )
        ):
            gates.add("version")
        return tuple(sorted(gates)), identity_violation


def validate_output_path(output: Path, project_root: Path, gold_path: Path) -> Path:
    root = project_root.resolve()
    raw = output if output.is_absolute() else root / output
    candidate = raw.parent.resolve() / raw.name
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise OutputPolicyError("output must remain inside the Git working tree") from error
    gold = gold_path.resolve()
    if candidate == gold:
        raise OutputPolicyError("output must not alias gold input")
    if candidate.is_symlink():
        raise OutputPolicyError("output must not be a symlink")
    if candidate.exists():
        if not candidate.is_file():
            raise OutputPolicyError("output must be a regular file")
        if os.path.samefile(candidate, gold):
            raise OutputPolicyError("output must not alias gold input")
        for tracked in _tracked_files(root):
            if tracked.is_file() and os.path.samefile(candidate, tracked):
                raise OutputPolicyError("output must not alias a tracked file")
    if _git_status(root, "ls-files", "--error-unmatch", "--", str(relative)) == 0:
        raise OutputPolicyError("output path is tracked by Git")
    if _git_status(root, "check-ignore", "-q", "--", str(relative)) != 0:
        raise OutputPolicyError("output path must be ignored by Git")
    return candidate


def write_report_atomically(
    output: Path,
    payload: dict[str, object],
    *,
    write_all: Callable[[int, bytes], None] | None = None,
    replace: Callable[[str | Path, str | Path], None] | None = None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    writer = write_all or _write_all_and_sync
    replacer = replace or os.replace
    try:
        writer(fd, data)
        if os.fstat(fd).st_size != len(data):
            raise OSError("incomplete report write")
        try:
            os.close(fd)
        except OSError:
            pass
        replacer(temporary, output)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


async def _run(database_url: str, catalog: GoldCatalog) -> EvaluationReport:
    engine = create_database_engine(DatabaseConfig(url=database_url, application_name="document-retrieval-verifier"))
    try:
        dataset = await _select_synthetic_corpus(engine)
        return await evaluate_cases(EvaluationCorpus(DocumentCandidateRepository(engine), PostgresSafetyAuditor(engine), dataset), catalog)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        gold_path = arguments.gold if arguments.gold.is_absolute() else root / arguments.gold
        catalog = load_gold_catalog(gold_path)
        output = validate_output_path(arguments.output, root, gold_path)
        report = asyncio.run(_run(arguments.database_url, catalog))
        write_report_atomically(output, report.as_json_object())
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


def _case_request(dataset: str, case: GoldCase) -> DocumentSearchRequest:
    return DocumentSearchRequest(dataset, case.entity_ids, case.claim_type, case.section_types, CUTOFF_DATE, TOP_K, case.query_embedding, MODEL_ID, MODEL_VERSION)


def _evaluation_row(case: GoldCase, mode: str, hits: tuple[DocumentCandidateHit, ...], audits: tuple[AuthoritativeHitAudit, ...]) -> EvaluationRow:
    top_ids = tuple(hit.chunk_id for hit in hits[:TOP_K])
    rank = next((index for index, chunk_id in enumerate(top_ids, 1) if chunk_id in case.gold_chunk_ids), None)
    return EvaluationRow(case.id, mode, top_ids, rank, *[sum(getattr(audit, field) for audit in audits) for field in (
        "dataset_violation", "identity_violation", "entity_violation", "coverage_violation",
        "authority_violation", "source_violation", "temporal_violation", "version_violation", "section_violation",
    )])


def _sum_rows(rows: tuple[EvaluationRow, ...], name: str) -> int:
    return sum(getattr(row, name) for row in rows)


def _chunk_metadata_statement(dataset: str, chunk_id: str) -> sa.Select:
    return sa.select(
        document_chunk.c.chunk_id, document_chunk.c.document_id, document_chunk.c.section_type,
        document_record.c.source_id, document_record.c.document_type, document_record.c.published_at, document_record.c.available_at,
        document_profile.c.document_version, document_profile.c.publisher_role, document_profile.c.effective_from, document_profile.c.effective_to, document_profile.c.cutoff_eligible,
        source_record.c.eligible_for_claim,
        dataset_version.c.status.label("dataset_status"), dataset_version.c.cutoff_date.label("dataset_cutoff"),
    ).select_from(
        document_chunk.join(document_record, sa.and_(document_chunk.c.dataset_version == document_record.c.dataset_version, document_chunk.c.document_id == document_record.c.document_id))
        .join(document_profile, sa.and_(document_record.c.dataset_version == document_profile.c.dataset_version, document_record.c.document_id == document_profile.c.document_id))
        .join(source_record, sa.and_(document_record.c.dataset_version == source_record.c.dataset_version, document_record.c.source_id == source_record.c.source_id))
        .join(dataset_version, document_record.c.dataset_version == dataset_version.c.dataset_version)
    ).where(document_chunk.c.dataset_version == dataset, document_chunk.c.chunk_id == chunk_id)


def _authority_and_coverage(row, bindings, coverages, claim_type: str) -> tuple[bool, bool]:
    coverage_ok = False
    authority_ok = False
    for rule in claim_authority_rules(claim_type):
        allowed_bindings = rule.binding_roles or binding_roles_for_document_role(rule.required_role)
        for binding in bindings:
            if binding.binding_role not in allowed_bindings:
                continue
            role_coverage = [
                coverage
                for coverage in coverages
                if coverage.entity_id == binding.entity_id
                and coverage.required_document_role == rule.required_role.value
                and coverage.coverage_status == "indexed"
                and coverage.document_id == row["document_id"]
            ]
            coverage_ok = coverage_ok or bool(role_coverage)
            publishers = {role.value for role in publisher_roles_for_document_role(rule.required_role, binding.binding_role)}
            if row["document_type"] in document_types_for_role(rule.required_role) and row["publisher_role"] in publishers and role_coverage:
                authority_ok = True
    return authority_ok, coverage_ok


def _metadata_temporal_violation(row, cutoff: date) -> bool:
    return (
        row["published_at"] is None or row["available_at"] is None
        or row["published_at"].astimezone(_SEOUL).date() > cutoff
        or row["available_at"].astimezone(_SEOUL).date() > cutoff
        or row["effective_from"] > cutoff
        or not row["cutoff_eligible"]
    )


async def _has_eligible_superseder(connection: AsyncConnection, request: DocumentSearchRequest, document_id: str) -> bool:
    rows = (await connection.execute(
        sa.select(
            document_profile.c.document_id,
            document_profile.c.document_version,
            document_profile.c.publisher_role,
            document_profile.c.effective_from,
            document_profile.c.effective_to,
            document_profile.c.cutoff_eligible,
            document_record.c.document_type,
            document_record.c.published_at,
            document_record.c.available_at,
            source_record.c.eligible_for_claim,
        )
        .select_from(document_profile.join(document_record, sa.and_(document_profile.c.dataset_version == document_record.c.dataset_version, document_profile.c.document_id == document_record.c.document_id)).join(source_record, sa.and_(document_record.c.dataset_version == source_record.c.dataset_version, document_record.c.source_id == source_record.c.source_id)))
        .where(document_profile.c.dataset_version == request.dataset_version, document_profile.c.amends_document_id == document_id)
    )).mappings().all()
    for row in rows:
        if not (
            row["eligible_for_claim"]
            and row["cutoff_eligible"]
            and bool(row["document_version"].strip())
            and row["effective_from"] <= request.cutoff_date
            and (row["effective_to"] is None or row["effective_to"] >= request.cutoff_date)
            and row["published_at"] is not None
            and row["available_at"] is not None
            and row["published_at"].astimezone(_SEOUL).date() <= request.cutoff_date
            and row["available_at"].astimezone(_SEOUL).date() <= request.cutoff_date
        ):
            continue
        bindings = (
            await connection.execute(
                sa.select(
                    document_entity_binding.c.entity_id,
                    document_entity_binding.c.binding_role,
                ).where(
                    document_entity_binding.c.dataset_version == request.dataset_version,
                    document_entity_binding.c.document_id == row["document_id"],
                )
            )
        ).all()
        if not {binding.entity_id for binding in bindings}.intersection(request.entity_ids):
            continue
        coverages = (
            await connection.execute(
                sa.select(
                    document_coverage.c.entity_id,
                    document_coverage.c.required_document_role,
                    document_coverage.c.coverage_status,
                    document_coverage.c.document_id,
                ).where(
                    document_coverage.c.dataset_version == request.dataset_version,
                    document_coverage.c.document_id == row["document_id"],
                )
            )
        ).all()
        authority, coverage = _authority_and_coverage(
            row, bindings, coverages, request.claim_type
        )
        if authority and coverage:
            return True
    return False


async def _select_synthetic_corpus(engine: AsyncEngine) -> str:
    required = {probe.chunk_id for probe in NEGATIVE_PROBES} | {chunk for case in _EXPECTED_CASES.values() for chunk in case["gold_chunk_ids"]}
    async with engine.connect() as connection:
        rows = (await connection.execute(sa.select(document_chunk.c.dataset_version, document_chunk.c.chunk_id).where(document_chunk.c.dataset_version.startswith(DATASET_PREFIX)))).all()
    by_dataset: dict[str, set[str]] = {}
    for dataset, chunk in rows:
        by_dataset.setdefault(dataset, set()).add(chunk)
    complete = sorted(dataset for dataset, chunks in by_dataset.items() if required <= chunks)
    if not complete:
        raise EvaluationConfigurationError("synthetic evaluation corpus is not loaded")
    return complete[-1]


def _write_all_and_sync(fd: int, data: bytes) -> None:
    with os.fdopen(fd, "wb", closefd=False) as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _tracked_files(root: Path) -> tuple[Path, ...]:
    result = subprocess.run(("git", "-C", str(root), "ls-files", "-z"), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        raise OutputPolicyError("Git tracked-file check failed")
    return tuple(root / value.decode() for value in result.stdout.split(b"\0") if value)


def _git_status(root: Path, *arguments: str) -> int:
    return subprocess.run(("git", "-C", str(root), *arguments), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise GoldCatalogError(f"{name} must be a nonempty string list")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise GoldCatalogError(f"{name} must not contain duplicates")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
