from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo

from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    APPROVED_RDF_TYPES,
    RELATION_METRIC_PROPERTY_BY_ID,
    GraphProjectionBatch,
)


_SEOUL = ZoneInfo("Asia/Seoul")
_DOMAIN_RANGE: Mapping[str, tuple[frozenset[str], frozenset[str]]] = {
    "managedBy": (frozenset({"FinancialProduct"}), frozenset({"AssetManager"})),
    "issuedBy": (
        frozenset({"FinancialProduct", "Security"}),
        frozenset({"Issuer"}),
    ),
    "tracksIndex": (
        frozenset({"ExchangeTradedProduct", "PublicFund"}),
        frozenset({"Index"}),
    ),
    "holdsSecurity": (frozenset({"ETF", "PublicFund"}), frozenset({"Security"})),
    "containsSecurity": (frozenset({"Index"}), frozenset({"Security"})),
    "securityOfCompany": (frozenset({"EquitySecurity"}), frozenset({"Company"})),
    "controlsCompany": (frozenset({"Company"}), frozenset({"Company"})),
    "listedOn": (frozenset({"Security"}), frozenset({"Market"})),
    "classifiedAsIndustry": (
        frozenset({"Company", "Security"}),
        frozenset({"Industry"}),
    ),
    "associatedWithTheme": (
        frozenset({"FinancialProduct", "Index", "Company"}),
        frozenset({"Theme"}),
    ),
    "hasShareClass": (
        frozenset({"RepresentativeFund"}),
        frozenset({"FundShareClass"}),
    ),
    "documentedBy": (
        frozenset({"FinancialProduct", "Organization", "PolicyProgram"}),
        frozenset({"OfficialDocument"}),
    ),
    "hasRiskFactor": (
        frozenset({"FinancialProduct"}),
        frozenset({"RiskFactor"}),
    ),
}


@dataclass(frozen=True, slots=True)
class GraphPreflightResult:
    conforms: bool
    counts: Mapping[str, int]
    violation_codes: tuple[str, ...]
    report_bytes: bytes
    report_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "counts",
            MappingProxyType(dict(sorted(self.counts.items()))),
        )


def _duplicates(values: list[str]) -> bool:
    return len(values) != len(set(values))


def _after_cutoff(value: date | datetime | None, cutoff: date) -> bool:
    if value is None:
        return False
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return True
        cutoff_end = datetime.combine(cutoff + timedelta(days=1), time.min, _SEOUL)
        return value.astimezone(_SEOUL) >= cutoff_end
    return value > cutoff


def validate_projection_batch(batch: GraphProjectionBatch) -> GraphPreflightResult:
    violations: set[str] = set()
    entities = {item.entity_id: item for item in batch.entities}
    sources = {item.source_id: item for item in batch.sources}
    evidences = {item.evidence_id: item for item in batch.evidences}
    metrics = [metric for relation in batch.relations for metric in relation.metrics]

    id_groups = (
        ("DUPLICATE_ENTITY_ID", [item.entity_id for item in batch.entities]),
        ("DUPLICATE_SOURCE_ID", [item.source_id for item in batch.sources]),
        ("DUPLICATE_EVIDENCE_ID", [item.evidence_id for item in batch.evidences]),
        ("DUPLICATE_RELATION_ID", [item.relation_id for item in batch.relations]),
        ("DUPLICATE_OBSERVATION_ID", [item.observation_id for item in metrics]),
    )
    for code, values in id_groups:
        if _duplicates(values):
            violations.add(code)

    records = (*batch.entities, *batch.sources, *batch.evidences, *batch.relations, *metrics)
    if any(item.dataset_version != batch.dataset_version for item in records):
        violations.add("DATASET_VERSION_MISMATCH")

    for item in batch.entities:
        if not item.rdf_types or not set(item.rdf_types) <= APPROVED_RDF_TYPES:
            violations.add("INVALID_RDF_TYPE")
    for item in batch.sources:
        if item.publisher_id not in entities:
            violations.add("MISSING_PUBLISHER")
    for item in batch.evidences:
        if item.source_id not in sources:
            violations.add("MISSING_SOURCE")
        if item.cutoff_status != "eligible":
            violations.add("INELIGIBLE_EVIDENCE")
        if any(
            _after_cutoff(value, batch.cutoff_date)
            for value in (
                item.applicable_date,
                item.valid_from,
                item.valid_to,
                item.published_at,
                item.available_at,
            )
        ):
            violations.add("AFTER_CUTOFF")
        if (
            item.valid_from is not None
            and item.valid_to is not None
            and item.valid_from > item.valid_to
        ):
            violations.add("INVALID_DATE_ORDER")

    for relation_item in batch.relations:
        if relation_item.predicate_id not in APPROVED_PREDICATES:
            violations.add("UNKNOWN_PREDICATE")
        subject = entities.get(relation_item.subject_id)
        object_ = entities.get(relation_item.object_id)
        if subject is None:
            violations.add("MISSING_SUBJECT")
        if object_ is None:
            violations.add("MISSING_OBJECT")
        expected = _DOMAIN_RANGE.get(relation_item.predicate_id)
        if expected is not None and subject is not None:
            if not set(subject.rdf_types) & expected[0]:
                violations.add("INVALID_RELATION_DOMAIN")
        if expected is not None and object_ is not None:
            if not set(object_.rdf_types) & expected[1]:
                violations.add("INVALID_RELATION_RANGE")
        if not relation_item.evidence_ids or not set(
            relation_item.evidence_ids
        ) <= evidences.keys():
            violations.add("MISSING_EVIDENCE")
        if (
            relation_item.valid_from is not None
            and relation_item.valid_to is not None
            and relation_item.valid_from > relation_item.valid_to
        ):
            violations.add("INVALID_DATE_ORDER")
        if _after_cutoff(relation_item.valid_from, batch.cutoff_date) or _after_cutoff(
            relation_item.valid_to, batch.cutoff_date
        ):
            violations.add("AFTER_CUTOFF")

        if relation_item.predicate_id == "holdsSecurity" and not relation_item.metrics:
            violations.add("MISSING_HOLDING_WEIGHT")
        if relation_item.predicate_id != "holdsSecurity" and relation_item.metrics:
            violations.add("INVALID_RELATION_METRIC")
        metric_dates: set[date] = set()
        for metric in relation_item.metrics:
            if metric.relation_id != relation_item.relation_id:
                violations.add("RELATION_METRIC_MISMATCH")
            if metric.metric_id not in RELATION_METRIC_PROPERTY_BY_ID:
                violations.add("UNKNOWN_RELATION_METRIC")
            if (
                not isinstance(metric.numeric_value, Decimal)
                or not metric.numeric_value.is_finite()
                or metric.numeric_value < 0
                or metric.numeric_value > 100
                or metric.unit != "percentage_point"
            ):
                violations.add("INVALID_HOLDING_WEIGHT")
            if metric.applicable_date is None:
                violations.add("MISSING_HOLDING_DATE")
            elif metric.applicable_date in metric_dates:
                violations.add("DUPLICATE_HOLDING_DATE")
            else:
                metric_dates.add(metric.applicable_date)
            if _after_cutoff(metric.applicable_date, batch.cutoff_date):
                violations.add("AFTER_CUTOFF")

    counts = {
        "entities": len(batch.entities),
        "evidences": len(batch.evidences),
        "holding_observations": len(metrics),
        "relations": len(batch.relations),
        "sources": len(batch.sources),
    }
    codes = tuple(sorted(violations))
    report_bytes = json.dumps(
        {
            "conforms": not codes,
            "counts": counts,
            "dataset_version": batch.dataset_version,
            "schema_version": "1",
            "violation_codes": list(codes),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return GraphPreflightResult(
        conforms=not codes,
        counts=counts,
        violation_codes=codes,
        report_bytes=report_bytes,
        report_hash=sha256(report_bytes).hexdigest(),
    )
