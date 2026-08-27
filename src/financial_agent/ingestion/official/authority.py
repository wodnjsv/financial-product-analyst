from __future__ import annotations

from dataclasses import dataclass

from financial_agent.ingestion.models import MappedRow


class OfficialEnrichmentScopeError(RuntimeError):
    def __init__(self) -> None:
        self.code = "OFFICIAL_ENRICHMENT_SCOPE_VIOLATION"
        super().__init__("official enrichment exceeds the approved scope")


@dataclass(frozen=True, slots=True)
class _Scope:
    allowed_tables: frozenset[str]
    metric_prefixes: tuple[str, ...] = ()
    exact_metrics: frozenset[str] = frozenset()
    relation_predicates: frozenset[str] = frozenset()
    observations_require_relation: bool | None = None


_SOURCE_ONLY_TABLES = frozenset(
    {
        "catalog.entity",
        "catalog.institution",
        "catalog.identifier",
        "evidence.source_record",
    }
)
_SECURITY_FACT_TABLES = _SOURCE_ONLY_TABLES | {
    "catalog.security",
    "catalog.alias",
    "observation.metric_definition",
    "observation.observation_record",
    "evidence.evidence_record",
    "evidence.evidence_observation_origin",
}
_HOLDING_TABLES = _SOURCE_ONLY_TABLES | {
    "catalog.alias",
    "catalog.security",
    "relation.relation_record",
    "observation.metric_definition",
    "observation.observation_record",
    "evidence.evidence_record",
    "evidence.evidence_observation_origin",
    "evidence.evidence_relation_origin",
}
_FX_METRICS = frozenset(
    {
        "ecos_731y001_krw_per_usd",
        "ecos_731y001_krw_per_100_jpy",
        "ecos_731y001_krw_per_eur",
        "ecos_731y001_krw_per_cny",
    }
)
_SCOPES = {
    "KRX_KOSPI_BASIC": _Scope(
        allowed_tables=_SECURITY_FACT_TABLES,
        metric_prefixes=("official.krx.security.",),
        observations_require_relation=False,
    ),
    "KRX_KOSDAQ_BASIC": _Scope(
        allowed_tables=_SECURITY_FACT_TABLES,
        metric_prefixes=("official.krx.security.",),
        observations_require_relation=False,
    ),
    "KRX_ETF_PDF": _Scope(
        allowed_tables=_HOLDING_TABLES,
        metric_prefixes=("krx_etf_holding_",),
        relation_predicates=frozenset({"holdsSecurity"}),
        observations_require_relation=True,
    ),
    "ECOS_731Y001": _Scope(
        allowed_tables=_SOURCE_ONLY_TABLES
        | {
            "observation.metric_definition",
            "observation.observation_record",
            "evidence.evidence_record",
            "evidence.evidence_observation_origin",
        },
        exact_metrics=_FX_METRICS,
        observations_require_relation=False,
    ),
    "SEC_SERIES_CLASS_20260601": _Scope(
        allowed_tables=_SOURCE_ONLY_TABLES,
    ),
    "SEC_NPORT_2026Q2": _Scope(
        allowed_tables=_HOLDING_TABLES,
        metric_prefixes=("official_holding_",),
        relation_predicates=frozenset({"holdsSecurity"}),
        observations_require_relation=True,
    ),
}


def _fail() -> None:
    raise OfficialEnrichmentScopeError() from None


def _metric_is_allowed(scope: _Scope, metric_id: object) -> bool:
    if not isinstance(metric_id, str):
        return False
    return metric_id in scope.exact_metrics or any(
        metric_id.startswith(prefix) for prefix in scope.metric_prefixes
    )


def validate_official_enrichment_scope(
    source_code: str,
    row: MappedRow,
) -> None:
    scope = _SCOPES.get(source_code)
    if scope is None:
        _fail()

    for table, records in row.records_by_table.items():
        if records and table not in scope.allowed_tables:
            _fail()

    for entity in row.records_by_table.get("catalog.entity", ()):
        if entity.get("entity_type") == "product":
            _fail()

    for definition in row.records_by_table.get(
        "observation.metric_definition", ()
    ):
        if not _metric_is_allowed(scope, definition.get("metric_id")):
            _fail()

    for observation in row.records_by_table.get(
        "observation.observation_record", ()
    ):
        if not _metric_is_allowed(scope, observation.get("metric_id")):
            _fail()
        relation_id = observation.get("relation_id")
        entity_id = observation.get("entity_id")
        if scope.observations_require_relation is True and (
            relation_id is None or entity_id is not None
        ):
            _fail()
        if scope.observations_require_relation is False and (
            relation_id is not None or entity_id is None
        ):
            _fail()

    for relation in row.records_by_table.get(
        "relation.relation_record", ()
    ):
        if relation.get("predicate_id") not in scope.relation_predicates:
            _fail()

    for evidence in row.records_by_table.get("evidence.evidence_record", ()):
        kind = evidence.get("evidence_kind")
        predicate_id = evidence.get("predicate_id")
        if kind == "observation":
            if not _metric_is_allowed(scope, predicate_id):
                _fail()
        elif kind == "relation":
            if predicate_id not in scope.relation_predicates:
                _fail()
        elif kind == "query_scope":
            if (
                predicate_id != "holdsSecurityCoverage"
                or "holdsSecurity" not in scope.relation_predicates
            ):
                _fail()
        else:
            _fail()
