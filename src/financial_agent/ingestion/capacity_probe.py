from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import canonical_sha256
from financial_agent.db.schema.catalog import identifier, product
from financial_agent.db.schema.operations import active_dataset, dataset_version
from financial_agent.db.schema.evidence import (
    evidence_document_origin,
    evidence_observation_origin,
    evidence_record,
    evidence_relation_origin,
    source_record,
)
from financial_agent.db.schema.observation import observation_record
from financial_agent.db.schema.relation import relation_record
from financial_agent.ingestion.models import BuildReport


_GIB = 1024**3
_STORAGE_INCREMENT_GIB = 10
_CURRENT_CUTOFF = date(2026, 8, 24)
_CURRENT_ORGANIZER_ROWS = 53_375
_CURRENT_EXACT_REUSED_IDENTITIES = 217
_CURRENT_AMBIGUOUS_OVERSEAS_PAIRS = 63
_ORGANIZER_SOURCE_CODES = (
    "PRBD01N001",
    "PREF01N001",
    "PREF02N001",
    "PRFD01N001",
)
_ORGANIZER_SOURCE_TITLES = {
    "PREF01N001": "PREF01N001 organizer product master",
    "PREF02N001": "PREF02N001 organizer product master",
    "PRFD01N001": "PRFD01N001 organizer product master",
}
_AMBIGUOUS_IDENTIFIER_COLUMNS = {
    "pd_isin_cd": "ISIN",
    "pd_lipper_id": "LIPPER",
}
_CURRENT_APPROVED_STAGE03_SOURCES = frozenset(
    _ORGANIZER_SOURCE_CODES
    + (
        "ECOS_731Y001",
        "KRX_ETF_PDF",
        "KRX_KOSDAQ_BASIC",
        "KRX_KOSPI_BASIC",
        "SEC_NPORT_2026Q2",
        "SEC_SERIES_CLASS_20260601",
    )
)
_REPRESENTATIVE_QUERY_KEYS = frozenset(
    {
        "public_fund_holding_coverage",
        "samsung_domestic_etf_aum_top5",
        "sec_bounded_holding_products",
    }
)
_SAMSUNG_ELECTRONICS_STANDARD_ISSUE_CODE = "KR7005930003"
_FORBIDDEN_EXTERNAL_PRODUCT_METRICS = frozenset(
    {
        "krx_etf_market_close_krw",
        "krx_etf_nav_per_share_krw",
    }
)


class CapacityProbeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _tagged_string_value(tagged_value: object) -> str | None:
    if (
        not isinstance(tagged_value, dict)
        or tagged_value.get("type") != "string"
    ):
        return None
    value = str(tagged_value.get("value", "")).strip().upper()
    return value or None


def _canonical_rowset_sha256(rows: list[dict[str, object]]) -> str:
    return canonical_sha256({"rows": rows})


@dataclass(frozen=True, slots=True)
class CapacityEstimate:
    base_bytes: int
    sampled_nport_bytes: int
    sampled_holding_count: int
    full_holding_count: int
    projected_nport_bytes: int
    projected_total_bytes: int
    safety_adjusted_bytes: int
    required_storage_gib: int
    recommended_storage_gib: int
    additional_storage_gib: int


@dataclass(frozen=True, slots=True)
class CapacityProbeReport:
    sample_product_count: int
    sample_holding_count: int
    storage_before_bytes: int
    base_bytes: int
    sampled_nport_bytes: int
    dataset_status: str
    active: bool
    estimate: CapacityEstimate


@dataclass(frozen=True, slots=True)
class DatabaseAcceptanceReport:
    dataset_version: str
    cutoff_date: date
    dataset_manifest_hash: str
    dataset_status: str
    active: bool
    build_passed: bool
    source_counts: Mapping[str, Mapping[str, int]]
    table_counts: Mapping[str, int]
    issue_counts: Mapping[str, int]
    component_hashes: Mapping[str, str]
    canonical_product_count: int
    observation_count: int
    identifier_counts_by_scheme: Mapping[str, int]
    relation_counts_by_predicate: Mapping[str, int]
    evidence_origin_counts: Mapping[str, int]
    exact_reused_identity_count: int
    ambiguous_identifier_counts_by_scheme: Mapping[str, int]
    aligned_ambiguous_pair_count: int
    approved_source_codes: tuple[str, ...]
    organizer_nonvalue_observation_count: int
    organizer_missing_external_substitute_count: int
    organizer_zero_observation_count: int
    representative_query_counts: Mapping[str, int]
    representative_query_hashes: Mapping[str, str]

    def to_reproducibility_mapping(self) -> dict[str, object]:
        return {
            "active": self.active,
            "aligned_ambiguous_pair_count": self.aligned_ambiguous_pair_count,
            "approved_source_codes": list(self.approved_source_codes),
            "ambiguous_identifier_counts_by_scheme": dict(
                sorted(self.ambiguous_identifier_counts_by_scheme.items())
            ),
            "build_passed": self.build_passed,
            "canonical_product_count": self.canonical_product_count,
            "component_hashes": dict(sorted(self.component_hashes.items())),
            "cutoff_date": self.cutoff_date.isoformat(),
            "dataset_manifest_hash": self.dataset_manifest_hash,
            "dataset_status": self.dataset_status,
            "evidence_origin_counts": dict(
                sorted(self.evidence_origin_counts.items())
            ),
            "exact_reused_identity_count": self.exact_reused_identity_count,
            "identifier_counts_by_scheme": dict(
                sorted(self.identifier_counts_by_scheme.items())
            ),
            "issue_counts": dict(sorted(self.issue_counts.items())),
            "observation_count": self.observation_count,
            "organizer_nonvalue_observation_count": (
                self.organizer_nonvalue_observation_count
            ),
            "organizer_missing_external_substitute_count": (
                self.organizer_missing_external_substitute_count
            ),
            "organizer_zero_observation_count": (
                self.organizer_zero_observation_count
            ),
            "representative_query_counts": dict(
                sorted(self.representative_query_counts.items())
            ),
            "representative_query_hashes": dict(
                sorted(self.representative_query_hashes.items())
            ),
            "relation_counts_by_predicate": dict(
                sorted(self.relation_counts_by_predicate.items())
            ),
            "source_counts": {
                source: dict(sorted(counts.items()))
                for source, counts in sorted(self.source_counts.items())
            },
            "table_counts": dict(sorted(self.table_counts.items())),
        }

    @property
    def reproducibility_hash(self) -> str:
        return canonical_sha256(self.to_reproducibility_mapping())

    def to_json_mapping(self) -> dict[str, object]:
        return {
            "dataset_version": self.dataset_version,
            "reproducibility_hash": self.reproducibility_hash,
            **self.to_reproducibility_mapping(),
        }


def write_database_acceptance_report(
    report: DatabaseAcceptanceReport,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report.to_json_mapping(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def estimate_stage03b_capacity(
    *,
    base_bytes: int,
    sampled_nport_bytes: int,
    sampled_holding_count: int,
    full_holding_count: int,
    current_storage_gib: int,
) -> CapacityEstimate:
    projected_nport_bytes = _ceil_div(
        sampled_nport_bytes * full_holding_count,
        sampled_holding_count,
    )
    projected_total_bytes = base_bytes + projected_nport_bytes
    safety_adjusted_bytes = _ceil_div(projected_total_bytes * 13, 10)
    required_storage_gib = (
        _ceil_div(
            safety_adjusted_bytes,
            _STORAGE_INCREMENT_GIB * _GIB,
        )
        * _STORAGE_INCREMENT_GIB
    )
    recommended_storage_gib = max(current_storage_gib, required_storage_gib)
    return CapacityEstimate(
        base_bytes=base_bytes,
        sampled_nport_bytes=sampled_nport_bytes,
        sampled_holding_count=sampled_holding_count,
        full_holding_count=full_holding_count,
        projected_nport_bytes=projected_nport_bytes,
        projected_total_bytes=projected_total_bytes,
        safety_adjusted_bytes=safety_adjusted_bytes,
        required_storage_gib=required_storage_gib,
        recommended_storage_gib=recommended_storage_gib,
        additional_storage_gib=(
            recommended_storage_gib - current_storage_gib
        ),
    )


async def measure_application_storage_bytes(engine: AsyncEngine) -> int:
    statement = sa.text(
        """
        SELECT COALESCE(SUM(pg_total_relation_size(class.oid)), 0)
        FROM pg_catalog.pg_class AS class
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = class.relnamespace
        WHERE namespace.nspname IN (
          'catalog', 'document', 'evidence', 'observation',
          'operations', 'relation', 'search'
        )
          AND class.relkind IN ('r', 'm')
        """
    )
    async with engine.connect() as connection:
        value = await connection.scalar(statement)
    return int(value or 0)


async def require_capacity_probe_dataset_absent(
    engine: AsyncEngine,
    dataset_version_value: str,
) -> None:
    async with engine.connect() as connection:
        existing = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(dataset_version)
            .where(
                dataset_version.c.dataset_version == dataset_version_value
            )
        )
    if int(existing or 0) != 0:
        raise CapacityProbeError("CAPACITY_PROBE_DATASET_EXISTS") from None


async def count_nport_holding_relations(
    engine: AsyncEngine,
    dataset_version_value: str,
) -> int:
    async with engine.connect() as connection:
        count = await connection.scalar(
            sa.select(
                sa.func.count(
                    sa.distinct(evidence_relation_origin.c.relation_id)
                )
            )
            .select_from(
                evidence_relation_origin.join(
                    evidence_record,
                    sa.and_(
                        evidence_record.c.dataset_version
                        == evidence_relation_origin.c.dataset_version,
                        evidence_record.c.evidence_id
                        == evidence_relation_origin.c.evidence_id,
                    ),
                ).join(
                    relation_record,
                    sa.and_(
                        relation_record.c.dataset_version
                        == evidence_relation_origin.c.dataset_version,
                        relation_record.c.relation_id
                        == evidence_relation_origin.c.relation_id,
                    ),
                )
            )
            .where(
                relation_record.c.dataset_version == dataset_version_value,
                relation_record.c.predicate_id == "holdsSecurity",
                evidence_record.c.locator_section
                == "FUND_REPORTED_HOLDING.tsv",
            )
        )
    return int(count or 0)


async def capacity_probe_dataset_state(
    engine: AsyncEngine,
    dataset_version_value: str,
) -> tuple[str, bool]:
    async with engine.connect() as connection:
        status = await connection.scalar(
            sa.select(dataset_version.c.status).where(
                dataset_version.c.dataset_version == dataset_version_value
            )
        )
        active = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(active_dataset)
            .where(active_dataset.c.dataset_version == dataset_version_value)
        )
    return str(status or ""), bool(active)


async def measure_database_acceptance(
    engine: AsyncEngine,
    build_report: BuildReport,
) -> DatabaseAcceptanceReport:
    dataset = build_report.dataset_version
    status, active = await capacity_probe_dataset_state(engine, dataset)
    if not status:
        raise CapacityProbeError("DATABASE_ACCEPTANCE_DATASET_MISSING") from None

    async with engine.connect() as connection:
        canonical_product_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(product)
                .where(product.c.dataset_version == dataset)
            )
            or 0
        )
        observation_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(observation_record)
                .where(observation_record.c.dataset_version == dataset)
            )
            or 0
        )
        identifier_counts = {
            str(row.scheme): int(row.count)
            for row in (
                await connection.execute(
                    sa.select(
                        identifier.c.scheme,
                        sa.func.count().label("count"),
                    )
                    .where(identifier.c.dataset_version == dataset)
                    .group_by(identifier.c.scheme)
                    .order_by(identifier.c.scheme)
                )
            )
        }
        relation_counts = {
            str(row.predicate_id): int(row.count)
            for row in (
                await connection.execute(
                    sa.select(
                        relation_record.c.predicate_id,
                        sa.func.count().label("count"),
                    )
                    .where(relation_record.c.dataset_version == dataset)
                    .group_by(relation_record.c.predicate_id)
                    .order_by(relation_record.c.predicate_id)
                )
            )
        }
        evidence_origin_counts = {
            "document": int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(evidence_document_origin)
                    .where(evidence_document_origin.c.dataset_version == dataset)
                )
                or 0
            ),
            "observation": int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(evidence_observation_origin)
                    .where(
                        evidence_observation_origin.c.dataset_version == dataset
                    )
                )
                or 0
            ),
            "relation": int(
                await connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(evidence_relation_origin)
                    .where(evidence_relation_origin.c.dataset_version == dataset)
                )
                or 0
            ),
        }

        evidence_sources = evidence_record.join(
            source_record,
            sa.and_(
                source_record.c.dataset_version
                == evidence_record.c.dataset_version,
                source_record.c.source_id == evidence_record.c.source_id,
            ),
        )
        overlap_subjects = (
            sa.select(evidence_record.c.subject_id)
            .select_from(
                evidence_sources.join(
                    product,
                    sa.and_(
                        product.c.dataset_version
                        == evidence_record.c.dataset_version,
                        product.c.entity_id == evidence_record.c.subject_id,
                    ),
                )
            )
            .where(
                evidence_record.c.dataset_version == dataset,
                source_record.c.source_title.in_(
                    (
                        _ORGANIZER_SOURCE_TITLES["PREF01N001"],
                        _ORGANIZER_SOURCE_TITLES["PRFD01N001"],
                    )
                ),
            )
            .group_by(evidence_record.c.subject_id)
            .having(sa.func.count(sa.distinct(source_record.c.source_title)) == 2)
            .subquery()
        )
        exact_reused_identity_count = int(
            await connection.scalar(
                sa.select(sa.func.count()).select_from(overlap_subjects)
            )
            or 0
        )
        ambiguous_rows = (
            await connection.execute(
                sa.select(
                    evidence_record.c.locator_column,
                    evidence_record.c.normalized_value,
                    evidence_record.c.subject_id,
                )
                .select_from(evidence_sources)
                .where(
                    evidence_record.c.dataset_version == dataset,
                    source_record.c.source_title
                    == _ORGANIZER_SOURCE_TITLES["PREF02N001"],
                    evidence_record.c.locator_column.in_(
                        tuple(_AMBIGUOUS_IDENTIFIER_COLUMNS)
                    ),
                    evidence_record.c.subject_id.is_not(None),
                )
            )
        ).all()

        organizer_zero_observation_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(observation_record)
                .where(
                    observation_record.c.dataset_version == dataset,
                    observation_record.c.metric_id.like("organizer.%"),
                    observation_record.c.value_status == "zero",
                )
            )
            or 0
        )
        organizer_nonvalue_observation_count = int(
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(observation_record)
                .where(
                    observation_record.c.dataset_version == dataset,
                    observation_record.c.metric_id.like("organizer.%"),
                    observation_record.c.value_status.in_(
                        (
                            "missing",
                            "placeholder",
                            "unavailable",
                            "unknown",
                        )
                    ),
                )
            )
            or 0
        )
        external_product_observations = observation_record.join(
            product,
            sa.and_(
                product.c.dataset_version
                == observation_record.c.dataset_version,
                product.c.entity_id == observation_record.c.entity_id,
            ),
        )
        organizer_missing_external_substitute_count = int(
            await connection.scalar(
                sa.select(
                    sa.func.count(
                        sa.distinct(observation_record.c.observation_id)
                    )
                )
                .select_from(external_product_observations)
                .where(
                    observation_record.c.dataset_version == dataset,
                    observation_record.c.metric_id.in_(
                        _FORBIDDEN_EXTERNAL_PRODUCT_METRICS
                    ),
                )
            )
            or 0
        )

        samsung_rows = (
            await connection.execute(
                sa.text(
                    """
                    SELECT
                        product.entity_id,
                        aum.numeric_value::text AS aum_value,
                        holding_evidence.source_id AS holding_source_id,
                        aum_evidence.source_id AS aum_source_id,
                        holding_evidence.applicable_date::text AS holding_date,
                        aum_evidence.locator_uri_or_object_key AS aum_locator
                    FROM relation.relation_record AS holding
                    JOIN catalog.entity AS security
                      ON security.dataset_version = holding.dataset_version
                     AND security.entity_id = holding.object_id
                    JOIN catalog.entity AS product
                      ON product.dataset_version = holding.dataset_version
                     AND product.entity_id = holding.subject_id
                    JOIN catalog.identifier AS security_identifier
                      ON security_identifier.dataset_version =
                         security.dataset_version
                     AND security_identifier.entity_id = security.entity_id
                     AND security_identifier.scheme =
                         'KRX_STANDARD_ISSUE_CODE'
                     AND security_identifier.identifier_value =
                         :samsung_standard_issue_code
                    JOIN observation.observation_record AS aum
                      ON aum.dataset_version = holding.dataset_version
                     AND aum.entity_id = holding.subject_id
                     AND aum.metric_id = 'organizer.pref01n001.aum'
                     AND aum.value_status IN ('present', 'zero')
                    JOIN evidence.evidence_relation_origin AS holding_origin
                      ON holding_origin.dataset_version = holding.dataset_version
                     AND holding_origin.relation_id = holding.relation_id
                    JOIN evidence.evidence_record AS holding_evidence
                      ON holding_evidence.dataset_version = holding_origin.dataset_version
                     AND holding_evidence.evidence_id = holding_origin.evidence_id
                    JOIN evidence.evidence_observation_origin AS aum_origin
                      ON aum_origin.dataset_version = aum.dataset_version
                     AND aum_origin.observation_id = aum.observation_id
                    JOIN evidence.evidence_record AS aum_evidence
                      ON aum_evidence.dataset_version = aum_origin.dataset_version
                     AND aum_evidence.evidence_id = aum_origin.evidence_id
                    WHERE holding.dataset_version = :dataset_version
                      AND holding.predicate_id = 'holdsSecurity'
                    ORDER BY
                        aum.numeric_value DESC,
                        product.normalized_name,
                        product.entity_id
                    LIMIT 5
                    """
                ),
                {
                    "dataset_version": dataset,
                    "samsung_standard_issue_code": (
                        _SAMSUNG_ELECTRONICS_STANDARD_ISSUE_CODE
                    ),
                },
            )
        ).mappings().all()
        samsung_payload = [dict(row) for row in samsung_rows]

        sec_rows = (
            await connection.execute(
                sa.text(
                    """
                    SELECT
                        evidence.subject_id,
                        evidence.normalized_value ->> 'value' AS coverage_status,
                        evidence.scope_completeness,
                        evidence.applicable_date::text AS applicable_date
                    FROM evidence.evidence_record AS evidence
                    JOIN evidence.source_record AS source
                      ON source.dataset_version = evidence.dataset_version
                     AND source.source_id = evidence.source_id
                    WHERE evidence.dataset_version = :dataset_version
                      AND evidence.evidence_kind = 'query_scope'
                      AND evidence.predicate_id = 'holdsSecurityCoverage'
                      AND source.source_title =
                          'SEC Form N-PORT 2026 Q2 public data set'
                    ORDER BY evidence.subject_id
                    """
                ),
                {"dataset_version": dataset},
            )
        ).mappings().all()
        sec_payload = [dict(row) for row in sec_rows]
        representative_query_counts = {
            "public_fund_holding_coverage": 0,
            "samsung_domestic_etf_aum_top5": len(samsung_payload),
            "sec_bounded_holding_products": len(sec_payload),
        }
        representative_query_hashes = {
            "public_fund_holding_coverage": canonical_sha256(
                {"coverage_status": "requires_data"}
            ),
            "samsung_domestic_etf_aum_top5": _canonical_rowset_sha256(
                samsung_payload
            ),
            "sec_bounded_holding_products": _canonical_rowset_sha256(
                sec_payload
            ),
        }

    identifier_subjects: dict[
        str, dict[str, set[str]]
    ] = defaultdict(lambda: defaultdict(set))
    for column, tagged_value, subject_id in ambiguous_rows:
        value = _tagged_string_value(tagged_value)
        if value is None or value == "NULL":
            continue
        scheme = _AMBIGUOUS_IDENTIFIER_COLUMNS[str(column)]
        identifier_subjects[scheme][value].add(str(subject_id))

    ambiguous_subject_sets: dict[str, Counter[frozenset[str]]] = {}
    ambiguous_identifier_counts: dict[str, int] = {}
    for scheme in ("ISIN", "LIPPER"):
        groups = Counter(
            frozenset(subjects)
            for subjects in identifier_subjects[scheme].values()
            if len(subjects) > 1
        )
        ambiguous_subject_sets[scheme] = groups
        ambiguous_identifier_counts[scheme] = sum(groups.values())
    aligned_ambiguous_pair_count = sum(
        (
            ambiguous_subject_sets["ISIN"]
            & ambiguous_subject_sets["LIPPER"]
        ).values()
    )

    return DatabaseAcceptanceReport(
        dataset_version=dataset,
        cutoff_date=build_report.cutoff_date,
        dataset_manifest_hash=build_report.dataset_manifest_hash,
        dataset_status=status,
        active=active,
        build_passed=build_report.passed,
        source_counts=build_report.source_counts,
        table_counts=build_report.table_counts,
        issue_counts=build_report.issue_counts,
        component_hashes=build_report.component_hashes,
        canonical_product_count=canonical_product_count,
        observation_count=observation_count,
        identifier_counts_by_scheme=identifier_counts,
        relation_counts_by_predicate=relation_counts,
        evidence_origin_counts=evidence_origin_counts,
        exact_reused_identity_count=exact_reused_identity_count,
        ambiguous_identifier_counts_by_scheme=ambiguous_identifier_counts,
        aligned_ambiguous_pair_count=aligned_ambiguous_pair_count,
        approved_source_codes=tuple(sorted(build_report.source_counts)),
        organizer_nonvalue_observation_count=(
            organizer_nonvalue_observation_count
        ),
        organizer_missing_external_substitute_count=(
            organizer_missing_external_substitute_count
        ),
        organizer_zero_observation_count=organizer_zero_observation_count,
        representative_query_counts=representative_query_counts,
        representative_query_hashes=representative_query_hashes,
    )


def require_matching_database_acceptance(
    first: DatabaseAcceptanceReport,
    second: DatabaseAcceptanceReport,
) -> None:
    if (
        first.dataset_version == second.dataset_version
        or first.to_reproducibility_mapping()
        != second.to_reproducibility_mapping()
    ):
        raise CapacityProbeError("DATABASE_ACCEPTANCE_MISMATCH") from None


def require_stage03_local_acceptance(
    report: DatabaseAcceptanceReport,
) -> None:
    if set(report.approved_source_codes) != _CURRENT_APPROVED_STAGE03_SOURCES:
        raise CapacityProbeError("STAGE03_SOURCE_BOUNDARY_FAILED") from None
    if report.organizer_missing_external_substitute_count != 0:
        raise CapacityProbeError("STAGE03_ORGANIZER_AUTHORITY_FAILED") from None
    if report.organizer_nonvalue_observation_count <= 0:
        raise CapacityProbeError(
            "STAGE03_ORGANIZER_MISSINGNESS_PRESERVATION_FAILED"
        ) from None
    if report.organizer_zero_observation_count <= 0:
        raise CapacityProbeError(
            "STAGE03_ORGANIZER_ZERO_PRESERVATION_FAILED"
        ) from None
    if (
        report.dataset_status != "building"
        or report.active
        or not report.build_passed
    ):
        raise CapacityProbeError("STAGE03_INACTIVE_STATE_FAILED") from None
    if (
        set(report.representative_query_counts)
        != _REPRESENTATIVE_QUERY_KEYS
        or set(report.representative_query_hashes)
        != _REPRESENTATIVE_QUERY_KEYS
        or report.representative_query_counts[
            "samsung_domestic_etf_aum_top5"
        ]
        != 5
        or report.representative_query_counts[
            "sec_bounded_holding_products"
        ]
        <= 0
        or report.representative_query_counts[
            "public_fund_holding_coverage"
        ]
        != 0
    ):
        raise CapacityProbeError(
            "STAGE03_REPRESENTATIVE_QUERY_FAILED"
        ) from None
    require_current_rebaseline_acceptance(report)


def require_current_rebaseline_acceptance(
    report: DatabaseAcceptanceReport,
) -> None:
    organizer_counts = {
        source: report.source_counts.get(source)
        for source in _ORGANIZER_SOURCE_CODES
    }
    organizer_rows = sum(
        int(counts.get("rows", -1)) if counts is not None else -1
        for counts in organizer_counts.values()
    )
    dispositions_match = all(
        int(counts.get("accepted", 0))
        + int(counts.get("limited", 0))
        + int(counts.get("quarantined", 0))
        == int(counts.get("rows", -1))
        for counts in report.source_counts.values()
    )
    if (
        report.cutoff_date != _CURRENT_CUTOFF
        or report.dataset_status != "building"
        or report.active
        or not report.build_passed
        or organizer_rows != _CURRENT_ORGANIZER_ROWS
        or not dispositions_match
        or report.exact_reused_identity_count
        != _CURRENT_EXACT_REUSED_IDENTITIES
        or dict(report.ambiguous_identifier_counts_by_scheme)
        != {
            "ISIN": _CURRENT_AMBIGUOUS_OVERSEAS_PAIRS,
            "LIPPER": _CURRENT_AMBIGUOUS_OVERSEAS_PAIRS,
        }
        or report.aligned_ambiguous_pair_count
        != _CURRENT_AMBIGUOUS_OVERSEAS_PAIRS
    ):
        raise CapacityProbeError("DATABASE_ACCEPTANCE_GATE_FAILED") from None
