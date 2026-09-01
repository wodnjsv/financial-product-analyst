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
    RELATION_METRIC_PROPERTY_BY_ID,
    EntityProjection,
    EvidenceProjection,
    GraphProjectionBatch,
    RelationMetricProjection,
    RelationProjection,
    SourceProjection,
)
from financial_agent.graph.entity_types import (
    EntityTypeProjectionError,
    ProductTypeFact,
    project_entity_ontology_type_ids,
)


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
    identifier_schemes_by_entity: dict[str, list[str]] = defaultdict(list)
    for row in identifier_rows:
        identifier_schemes_by_entity[row.entity_id].append(row.scheme)
    product_type_facts_by_entity: dict[str, list[ProductTypeFact]] = defaultdict(list)
    for row in product_type_rows:
        product_type_facts_by_entity[row.entity_id].append(
            ProductTypeFact(row.value_status, row.text_value, row.value_kind)
        )
    share_class_subject_ids = {
        row.subject_id for row in relation_rows if row.predicate_id == "hasShareClass"
    }
    share_class_object_ids = {
        row.object_id for row in relation_rows if row.predicate_id == "hasShareClass"
    }

    types_by_entity: dict[str, set[str]] = {}
    for row in entity_rows:
        try:
            types_by_entity[row.entity_id] = set(
                project_entity_ontology_type_ids(
                    entity_id=row.entity_id,
                    storage_entity_type=row.entity_type,
                    product_family=row.product_family,
                    security_kind=row.security_kind,
                    institution_kind=row.institution_kind,
                    identifier_schemes=tuple(
                        identifier_schemes_by_entity.get(row.entity_id, ())
                    ),
                    product_type_facts=tuple(
                        product_type_facts_by_entity.get(row.entity_id, ())
                    ),
                    is_share_class_subject=row.entity_id in share_class_subject_ids,
                    is_share_class_object=row.entity_id in share_class_object_ids,
                )
            )
        except EntityTypeProjectionError as error:
            _fail(error.code, error.detail)

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
