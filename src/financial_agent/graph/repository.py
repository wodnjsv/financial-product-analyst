from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from financial_agent.db.schema.catalog import entity, identifier, institution, product, security
from financial_agent.db.schema.evidence import (
    evidence_record,
    evidence_relation_origin,
    source_record,
)
from financial_agent.db.schema.observation import metric_definition, observation_record
from financial_agent.db.schema.operations import dataset_version as dataset_version_table
from financial_agent.db.schema.relation import relation_record
from financial_agent.graph.contract import (
    APPROVED_PREDICATES,
    ENTITY_CLASS_BY_TYPE,
    ETP_CLASSES_BY_FAMILY_AND_TYPE,
    PRODUCT_BASE_CLASSES_BY_FAMILY,
    RELATION_METRIC_PROPERTY_BY_ID,
    EntityProjection,
    EvidenceProjection,
    GraphProjectionBatch,
    RelationMetricProjection,
    RelationProjection,
    SourceProjection,
)


_INSTITUTION_CLASS_BY_KIND = {
    "asset_manager": "AssetManager",
    "issuer": "Issuer",
    "exchange": "Market",
}
_SECURITY_CLASS_BY_KIND = {"listed_equity": "EquitySecurity"}
_RELATION_DOMAIN_RANGE: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "managedBy": (frozenset({"FinancialProduct"}), frozenset({"AssetManager"})),
    "issuedBy": (
        frozenset({"FinancialProduct", "Security"}),
        frozenset({"Issuer"}),
    ),
    "tracksIndex": (frozenset({"ETF", "PublicFund"}), frozenset({"Index"})),
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


class GraphProjectionLoadError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _fail(code: str, detail: str) -> None:
    raise GraphProjectionLoadError(code, detail)


class GraphProjectionRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load(self, dataset_version: str) -> GraphProjectionBatch:
        async with self._engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(
                    sa.text(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                )
                batch = await self._load(connection, dataset_version)
            finally:
                if transaction.is_active:
                    await transaction.rollback()
        return batch

    async def _load(
        self,
        connection: AsyncConnection,
        dataset_version: str,
    ) -> GraphProjectionBatch:
        cutoff_date = (
            await connection.execute(
                sa.select(dataset_version_table.c.cutoff_date).where(
                    dataset_version_table.c.dataset_version == dataset_version
                )
            )
        ).scalar_one_or_none()
        if cutoff_date is None:
            _fail("dataset_version_not_found", dataset_version)

        entity_rows = (
            await connection.execute(
                sa.select(
                    entity.c.entity_id,
                    entity.c.entity_type,
                    product.c.product_family,
                    security.c.security_kind,
                    institution.c.institution_kind,
                )
                .select_from(
                    entity.outerjoin(
                        product,
                        sa.and_(
                            product.c.dataset_version == entity.c.dataset_version,
                            product.c.entity_id == entity.c.entity_id,
                        ),
                    )
                    .outerjoin(
                        security,
                        sa.and_(
                            security.c.dataset_version == entity.c.dataset_version,
                            security.c.entity_id == entity.c.entity_id,
                        ),
                    )
                    .outerjoin(
                        institution,
                        sa.and_(
                            institution.c.dataset_version == entity.c.dataset_version,
                            institution.c.entity_id == entity.c.entity_id,
                        ),
                    )
                )
                .where(entity.c.dataset_version == dataset_version)
                .order_by(entity.c.entity_id)
            )
        ).all()
        identifier_rows = (
            await connection.execute(
                sa.select(identifier.c.entity_id, identifier.c.scheme)
                .where(
                    identifier.c.dataset_version == dataset_version,
                    identifier.c.scheme == "PRFD_ITM_NO",
                )
                .order_by(identifier.c.entity_id, identifier.c.identifier_id)
            )
        ).all()
        product_type_rows = (
            await connection.execute(
                sa.select(
                    observation_record.c.entity_id,
                    observation_record.c.value_status,
                    observation_record.c.text_value,
                    metric_definition.c.value_kind,
                )
                .select_from(
                    observation_record.join(
                        metric_definition,
                        sa.and_(
                            metric_definition.c.metric_id == observation_record.c.metric_id,
                            metric_definition.c.definition_version
                            == observation_record.c.metric_definition_version,
                        ),
                    )
                )
                .where(
                    observation_record.c.dataset_version == dataset_version,
                    observation_record.c.entity_id.is_not(None),
                    observation_record.c.metric_id == "product_type",
                )
                .order_by(
                    observation_record.c.entity_id,
                    observation_record.c.observation_id,
                )
            )
        ).all()
        relation_rows = (
            await connection.execute(
                sa.select(
                    relation_record.c.relation_id,
                    relation_record.c.subject_id,
                    relation_record.c.predicate_id,
                    relation_record.c.object_id,
                    relation_record.c.valid_from,
                    relation_record.c.valid_to,
                )
                .where(relation_record.c.dataset_version == dataset_version)
                .order_by(relation_record.c.relation_id)
            )
        ).all()
        evidence_rows = (
            await connection.execute(
                sa.select(
                    evidence_relation_origin.c.relation_id,
                    evidence_record.c.evidence_id,
                    evidence_record.c.source_id,
                    evidence_record.c.applicable_date,
                    evidence_record.c.valid_from,
                    evidence_record.c.valid_to,
                    evidence_record.c.published_at,
                    evidence_record.c.available_at,
                    evidence_record.c.cutoff_status,
                    source_record.c.publisher,
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
                        source_record,
                        sa.and_(
                            source_record.c.dataset_version == evidence_record.c.dataset_version,
                            source_record.c.source_id == evidence_record.c.source_id,
                        ),
                    )
                )
                .where(evidence_relation_origin.c.dataset_version == dataset_version)
                .order_by(
                    evidence_relation_origin.c.relation_id,
                    evidence_record.c.evidence_id,
                )
            )
        ).all()
        metric_rows = (
            await connection.execute(
                sa.select(
                    observation_record.c.observation_id,
                    observation_record.c.relation_id,
                    observation_record.c.metric_id,
                    observation_record.c.value_status,
                    observation_record.c.numeric_value,
                    observation_record.c.unit,
                    observation_record.c.applicable_date,
                    metric_definition.c.value_kind,
                )
                .select_from(
                    observation_record.join(
                        metric_definition,
                        sa.and_(
                            metric_definition.c.metric_id == observation_record.c.metric_id,
                            metric_definition.c.definition_version
                            == observation_record.c.metric_definition_version,
                        ),
                    )
                )
                .where(
                    observation_record.c.dataset_version == dataset_version,
                    observation_record.c.relation_id.is_not(None),
                    observation_record.c.metric_id.in_(
                        tuple(RELATION_METRIC_PROPERTY_BY_ID)
                    ),
                )
                .order_by(
                    observation_record.c.relation_id,
                    observation_record.c.metric_id,
                    observation_record.c.observation_id,
                )
            )
        ).all()
        return _build_batch(
            dataset_version=dataset_version,
            cutoff_date=cutoff_date,
            entity_rows=entity_rows,
            identifier_rows=identifier_rows,
            product_type_rows=product_type_rows,
            relation_rows=relation_rows,
            evidence_rows=evidence_rows,
            metric_rows=metric_rows,
        )


def _build_batch(
    *,
    dataset_version: str,
    cutoff_date: date,
    entity_rows: list[Any],
    identifier_rows: list[Any],
    product_type_rows: list[Any],
    relation_rows: list[Any],
    evidence_rows: list[Any],
    metric_rows: list[Any],
) -> GraphProjectionBatch:
    types_by_entity: dict[str, set[str]] = {}
    family_by_entity: dict[str, str | None] = {}
    for row in entity_rows:
        base_type = ENTITY_CLASS_BY_TYPE.get(row.entity_type)
        if base_type is None:
            _fail("unsupported_entity_type", f"{row.entity_id}:{row.entity_type}")
        subtype_types = {
            subtype_type
            for subtype_type, subtype_value in (
                ("product", row.product_family),
                ("security", row.security_kind),
                ("institution", row.institution_kind),
            )
            if subtype_value is not None
        }
        if len(subtype_types) > 1 or (
            subtype_types and row.entity_type not in subtype_types
        ):
            _fail(
                "inconsistent_entity_subtype",
                f"{row.entity_id}:{row.entity_type}:{','.join(sorted(subtype_types))}",
            )
        rdf_types = {base_type}
        family_by_entity[row.entity_id] = row.product_family
        if row.product_family is not None:
            family_types = PRODUCT_BASE_CLASSES_BY_FAMILY.get(row.product_family)
            if family_types is None:
                _fail("unsupported_product_family", f"{row.entity_id}:{row.product_family}")
            rdf_types.update(family_types)
        if row.institution_kind in _INSTITUTION_CLASS_BY_KIND:
            rdf_types.add(_INSTITUTION_CLASS_BY_KIND[row.institution_kind])
        if row.security_kind in _SECURITY_CLASS_BY_KIND:
            rdf_types.add(_SECURITY_CLASS_BY_KIND[row.security_kind])
        types_by_entity[row.entity_id] = rdf_types

    for row in identifier_rows:
        rdf_types = types_by_entity.get(row.entity_id)
        if rdf_types is None or "FinancialProduct" not in rdf_types:
            _fail("invalid_share_class_type", row.entity_id)
        rdf_types.add("FundShareClass")

    product_types: dict[str, set[str]] = defaultdict(set)
    for row in product_type_rows:
        if (
            row.value_kind != "text"
            or row.value_status != "present"
            or row.text_value not in {"ETF", "ETN"}
        ):
            _fail("invalid_product_type_fact", str(row.entity_id))
        product_types[row.entity_id].add(row.text_value)
    for entity_id, values in product_types.items():
        if len(values) != 1:
            _fail("conflicting_product_type_facts", entity_id)
        product_type = next(iter(values))
        family = family_by_entity.get(entity_id)
        classes = ETP_CLASSES_BY_FAMILY_AND_TYPE.get((family, product_type))
        if classes is None:
            _fail("conflicting_product_type_fact", f"{entity_id}:{family}:{product_type}")
        types_by_entity[entity_id].update(classes)

    for row in relation_rows:
        if row.predicate_id == "hasShareClass":
            subject_types = types_by_entity.get(row.subject_id)
            object_types = types_by_entity.get(row.object_id)
            if subject_types is None or "PublicFund" not in subject_types:
                _fail("missing_relation_type", f"{row.relation_id}:subject")
            if object_types is None or "FinancialProduct" not in object_types:
                _fail("missing_relation_type", f"{row.relation_id}:object")
            subject_types.add("RepresentativeFund")
            object_types.add("FundShareClass")

    for rdf_types in types_by_entity.values():
        if {"ETF", "ETN"} <= rdf_types:
            _fail("conflicting_entity_types", "ETF and ETN")

    evidence_ids_by_relation: dict[str, list[str]] = defaultdict(list)
    evidence_by_id: dict[str, EvidenceProjection] = {}
    source_by_id: dict[str, SourceProjection] = {}
    for row in evidence_rows:
        evidence_ids_by_relation[row.relation_id].append(row.evidence_id)
        evidence_by_id[row.evidence_id] = EvidenceProjection(
            dataset_version=dataset_version,
            evidence_id=row.evidence_id,
            source_id=row.source_id,
            applicable_date=row.applicable_date,
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            published_at=row.published_at,
            available_at=row.available_at,
            cutoff_status=row.cutoff_status,
        )
        source_by_id[row.source_id] = SourceProjection(
            dataset_version=dataset_version,
            source_id=row.source_id,
            publisher_id=row.publisher,
        )

    relation_predicates = {
        row.relation_id: row.predicate_id for row in relation_rows
    }
    observation_ids: set[str] = set()
    metric_dates_by_relation: dict[str, set[date]] = defaultdict(set)
    metrics_by_relation: dict[str, list[RelationMetricProjection]] = defaultdict(list)
    for row in metric_rows:
        if row.observation_id in observation_ids:
            _fail("duplicate_metric_observation", row.observation_id)
        observation_ids.add(row.observation_id)
        if relation_predicates.get(row.relation_id) != "holdsSecurity":
            _fail("invalid_metric_relation", row.relation_id)
        if (
            row.value_kind != "numeric"
            or row.value_status not in {"present", "zero"}
            or not isinstance(row.numeric_value, Decimal)
            or not row.numeric_value.is_finite()
            or row.numeric_value < Decimal("0")
            or row.numeric_value > Decimal("100")
            or row.unit != "percentage_point"
        ):
            _fail("invalid_relation_metric", f"{row.relation_id}:{row.metric_id}")
        if row.applicable_date is None:
            _fail("missing_metric_date", row.observation_id)
        if row.applicable_date > cutoff_date:
            _fail("metric_after_cutoff", row.observation_id)
        if row.applicable_date in metric_dates_by_relation[row.relation_id]:
            _fail("ambiguous_metric_date", row.relation_id)
        metric_dates_by_relation[row.relation_id].add(row.applicable_date)
        metrics_by_relation[row.relation_id].append(
            RelationMetricProjection(
                dataset_version=dataset_version,
                observation_id=row.observation_id,
                relation_id=row.relation_id,
                metric_id=row.metric_id,
                numeric_value=row.numeric_value,
                unit=row.unit,
                applicable_date=row.applicable_date,
            )
        )

    relations: list[RelationProjection] = []
    for row in relation_rows:
        if row.predicate_id not in APPROVED_PREDICATES:
            _fail("unknown_predicate", row.predicate_id)
        subject_types = types_by_entity.get(row.subject_id, set())
        object_types = types_by_entity.get(row.object_id, set())
        domain, range_ = _RELATION_DOMAIN_RANGE[row.predicate_id]
        if not subject_types & domain:
            _fail("missing_relation_type", f"{row.relation_id}:subject")
        if not object_types & range_:
            _fail("missing_relation_type", f"{row.relation_id}:object")
        relation_evidence_ids = tuple(sorted(evidence_ids_by_relation[row.relation_id]))
        if not relation_evidence_ids:
            _fail("missing_relation_evidence", row.relation_id)
        relation_metrics = tuple(
            sorted(
                metrics_by_relation[row.relation_id],
                key=lambda metric: (
                    metric.metric_id,
                    metric.applicable_date,
                    metric.observation_id,
                ),
            )
        )
        if row.predicate_id == "holdsSecurity" and not relation_metrics:
            _fail("missing_holding_weight", row.relation_id)
        relations.append(
            RelationProjection(
                dataset_version=dataset_version,
                relation_id=row.relation_id,
                subject_id=row.subject_id,
                predicate_id=row.predicate_id,
                object_id=row.object_id,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                evidence_ids=relation_evidence_ids,
                metrics=relation_metrics,
            )
        )

    entities = tuple(
        EntityProjection(
            dataset_version=dataset_version,
            entity_id=entity_id,
            rdf_types=tuple(sorted(rdf_types)),
        )
        for entity_id, rdf_types in sorted(types_by_entity.items())
    )
    return GraphProjectionBatch(
        dataset_version=dataset_version,
        cutoff_date=cutoff_date,
        entities=entities,
        sources=tuple(source_by_id[key] for key in sorted(source_by_id)),
        evidences=tuple(evidence_by_id[key] for key in sorted(evidence_by_id)),
        relations=tuple(sorted(relations, key=lambda relation: relation.relation_id)),
    )
