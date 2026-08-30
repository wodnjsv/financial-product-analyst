from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from financial_agent.db.schema.catalog import entity, identifier, product
from financial_agent.db.schema.relation import relation_record
from financial_agent.documents import DocumentRole, DocumentSourceTarget
from financial_agent.ingestion.document_sources.dart_targets import (
    OrganizerDartProductRow,
)


_CUTOFF_DATE = date(2026, 8, 24)
_PRODUCT_BINDINGS = {
    "domestic_bond": (DocumentRole.PRODUCT_SUMMARY, "subject_product"),
    "domestic_etf": (DocumentRole.PRODUCT_SUMMARY, "subject_product"),
    "overseas_etf": (DocumentRole.PRODUCT_SUMMARY, "subject_product"),
    "public_fund": (DocumentRole.PRODUCT_SUMMARY, "subject_product"),
}


class DocumentTargetRepository:
    """Read-only enumeration of entities requiring a document-source audit."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def list_targets(
        self,
        dataset_version: str,
        cutoff_date: date,
    ) -> tuple[DocumentSourceTarget, ...]:
        _validate_scope(dataset_version, cutoff_date)
        product_result = await self._connection.execute(
            _product_targets_statement(dataset_version)
        )
        index_result = await self._connection.execute(
            _index_targets_statement(dataset_version)
        )
        targets = [
            *_targets_from_rows(
                product_result.mappings().all(),
                product_targets=True,
                dataset_version=dataset_version,
                cutoff_date=cutoff_date,
            ),
            *_targets_from_rows(
                index_result.mappings().all(),
                product_targets=False,
                dataset_version=dataset_version,
                cutoff_date=cutoff_date,
            ),
        ]
        return tuple(
            sorted(
                targets,
                key=lambda target: (
                    target.entity_id,
                    target.required_role.value,
                ),
            )
        )

    @staticmethod
    def compiled_statements(dataset_version: str) -> tuple[sa.Select[object], ...]:
        _validate_dataset_version(dataset_version)
        return (
            _product_targets_statement(dataset_version),
            _index_targets_statement(dataset_version),
        )

    async def list_organizer_dart_rows(
        self,
        dataset_version: str,
        cutoff_date: date,
    ) -> tuple[OrganizerDartProductRow, ...]:
        _validate_scope(dataset_version, cutoff_date)
        result = await self._connection.execute(
            _organizer_dart_statement(dataset_version)
        )
        return tuple(
            OrganizerDartProductRow(
                entity_id=_required_row_text(row, "entity_id"),
                canonical_name=_required_row_text(row, "canonical_name"),
                product_family=_required_row_text(row, "product_family"),
                identifier_scheme=_required_row_text(row, "identifier_scheme"),
                identifier_value=_required_row_text(row, "identifier_value"),
                representative_entity_id=_optional_row_text(
                    row, "representative_entity_id"
                ),
                representative_name=_optional_row_text(
                    row, "representative_name"
                ),
                manager_entity_id=_optional_row_text(row, "manager_entity_id"),
                manager_name=_optional_row_text(row, "manager_name"),
            )
            for row in result.mappings().all()
        )

    @staticmethod
    def organizer_dart_statement(dataset_version: str) -> sa.Select[object]:
        _validate_dataset_version(dataset_version)
        return _organizer_dart_statement(dataset_version)


def _validate_scope(dataset_version: str, cutoff_date: date) -> None:
    _validate_dataset_version(dataset_version)
    if cutoff_date != _CUTOFF_DATE:
        raise ValueError("document source cutoff must be 2026-08-24")


def _validate_dataset_version(dataset_version: str) -> None:
    if not isinstance(dataset_version, str) or not dataset_version.strip():
        raise ValueError("dataset_version must not be blank")


def _product_targets_statement(dataset_version: str) -> sa.Select[object]:
    return (
        sa.select(
            entity.c.entity_id,
            entity.c.entity_type,
            entity.c.canonical_name,
            product.c.product_family,
            identifier.c.scheme,
            identifier.c.identifier_value,
        )
        .select_from(
            product.join(
                entity,
                sa.and_(
                    product.c.dataset_version == entity.c.dataset_version,
                    product.c.entity_id == entity.c.entity_id,
                ),
            ).outerjoin(
                identifier,
                sa.and_(
                    identifier.c.dataset_version == entity.c.dataset_version,
                    identifier.c.entity_id == entity.c.entity_id,
                ),
            )
        )
        .where(
            product.c.dataset_version == dataset_version,
            product.c.product_family.in_(_PRODUCT_BINDINGS),
        )
    )


def _index_targets_statement(dataset_version: str) -> sa.Select[object]:
    index_entity = entity.alias("index_entity")
    index_identifier = identifier.alias("index_identifier")
    return (
        sa.select(
            index_entity.c.entity_id,
            index_entity.c.entity_type,
            index_entity.c.canonical_name,
            index_identifier.c.scheme,
            index_identifier.c.identifier_value,
        )
        .select_from(
            relation_record.join(
                product,
                sa.and_(
                    relation_record.c.dataset_version == product.c.dataset_version,
                    relation_record.c.subject_id == product.c.entity_id,
                ),
            )
            .join(
                index_entity,
                sa.and_(
                    relation_record.c.dataset_version
                    == index_entity.c.dataset_version,
                    relation_record.c.object_id == index_entity.c.entity_id,
                ),
            )
            .outerjoin(
                index_identifier,
                sa.and_(
                    index_identifier.c.dataset_version
                    == index_entity.c.dataset_version,
                    index_identifier.c.entity_id == index_entity.c.entity_id,
                ),
            )
        )
        .where(
            relation_record.c.dataset_version == dataset_version,
            relation_record.c.predicate_id == "tracksIndex",
            product.c.product_family.in_(_PRODUCT_BINDINGS),
            index_entity.c.entity_type == "index",
        )
    )


def _organizer_dart_statement(dataset_version: str) -> sa.Select[object]:
    organizer_identifier = identifier.alias("organizer_identifier")
    marker_identifier = identifier.alias("organizer_row_marker")
    manager_relation = relation_record.alias("manager_relation")
    manager_entity = entity.alias("manager_entity")
    representative_relation = relation_record.alias("representative_relation")
    representative_entity = entity.alias("representative_entity")
    is_representative_product = sa.exists(
        sa.select(sa.literal(1)).where(
            relation_record.c.dataset_version == product.c.dataset_version,
            relation_record.c.subject_id == product.c.entity_id,
            relation_record.c.predicate_id == "hasShareClass",
        )
    )
    representative_entity_id = sa.case(
        (
            sa.and_(
                product.c.product_family == "public_fund",
                representative_entity.c.entity_id.is_not(None),
            ),
            representative_entity.c.entity_id,
        ),
        (
            sa.and_(
                product.c.product_family == "public_fund",
                is_representative_product,
            ),
            product.c.entity_id,
        ),
    )
    representative_name = sa.case(
        (
            sa.and_(
                product.c.product_family == "public_fund",
                representative_entity.c.entity_id.is_not(None),
            ),
            representative_entity.c.canonical_name,
        ),
        (
            sa.and_(
                product.c.product_family == "public_fund",
                is_representative_product,
            ),
            entity.c.canonical_name,
        ),
    )
    organizer_marker_exists = sa.exists(
        sa.select(sa.literal(1)).where(
            marker_identifier.c.dataset_version == product.c.dataset_version,
            marker_identifier.c.entity_id == product.c.entity_id,
            sa.or_(
                sa.and_(
                    product.c.product_family == "domestic_etf",
                    marker_identifier.c.scheme == "PREF01_PD_ITM_NO",
                ),
                sa.and_(
                    product.c.product_family == "public_fund",
                    marker_identifier.c.scheme == "PRFD_ITM_NO",
                ),
            ),
        )
    )
    return (
        sa.select(
            entity.c.entity_id,
            entity.c.canonical_name,
            product.c.product_family,
            organizer_identifier.c.scheme.label("identifier_scheme"),
            organizer_identifier.c.identifier_value,
            representative_entity_id.label("representative_entity_id"),
            representative_name.label("representative_name"),
            manager_entity.c.entity_id.label("manager_entity_id"),
            manager_entity.c.canonical_name.label("manager_name"),
        )
        .select_from(
            product.join(
                entity,
                sa.and_(
                    product.c.dataset_version == entity.c.dataset_version,
                    product.c.entity_id == entity.c.entity_id,
                ),
            )
            .join(
                organizer_identifier,
                sa.and_(
                    organizer_identifier.c.dataset_version
                    == product.c.dataset_version,
                    organizer_identifier.c.entity_id == product.c.entity_id,
                    sa.or_(
                        sa.and_(
                            product.c.product_family == "domestic_etf",
                            organizer_identifier.c.scheme.in_(
                                ("PREF01_PD_ITM_NO", "ISIN")
                            ),
                        ),
                        sa.and_(
                            product.c.product_family == "public_fund",
                            organizer_identifier.c.scheme.in_(
                                ("PRFD_ITM_NO", "KSD_PRODUCT", "ISIN")
                            ),
                        ),
                    ),
                ),
            )
            .outerjoin(
                manager_relation,
                sa.and_(
                    manager_relation.c.dataset_version
                    == product.c.dataset_version,
                    manager_relation.c.subject_id == product.c.entity_id,
                    manager_relation.c.predicate_id == "managedBy",
                ),
            )
            .outerjoin(
                manager_entity,
                sa.and_(
                    manager_entity.c.dataset_version
                    == manager_relation.c.dataset_version,
                    manager_entity.c.entity_id == manager_relation.c.object_id,
                    manager_entity.c.entity_type == "institution",
                ),
            )
            .outerjoin(
                representative_relation,
                sa.and_(
                    representative_relation.c.dataset_version
                    == product.c.dataset_version,
                    representative_relation.c.object_id == product.c.entity_id,
                    representative_relation.c.predicate_id == "hasShareClass",
                    product.c.product_family == "public_fund",
                ),
            )
            .outerjoin(
                representative_entity,
                sa.and_(
                    representative_entity.c.dataset_version
                    == representative_relation.c.dataset_version,
                    representative_entity.c.entity_id
                    == representative_relation.c.subject_id,
                ),
            )
        )
        .where(
            product.c.dataset_version == dataset_version,
            product.c.product_family.in_(("domestic_etf", "public_fund")),
            organizer_marker_exists,
        )
        .order_by(
            entity.c.entity_id,
            organizer_identifier.c.scheme,
            organizer_identifier.c.identifier_value,
            manager_entity.c.entity_id,
            representative_entity.c.entity_id,
        )
    )


def _targets_from_rows(
    rows: list[Mapping[str, object]],
    *,
    product_targets: bool,
    dataset_version: str,
    cutoff_date: date,
) -> tuple[DocumentSourceTarget, ...]:
    grouped: dict[tuple[str, str, str, str | None], set[tuple[str, str]]] = {}
    for row in rows:
        entity_id = _required_row_text(row, "entity_id")
        entity_type = _required_row_text(row, "entity_type")
        canonical_name = _required_row_text(row, "canonical_name")
        product_family = (
            _required_row_text(row, "product_family") if product_targets else None
        )
        key = (entity_id, entity_type, canonical_name, product_family)
        identifiers = grouped.setdefault(key, set())
        scheme = row.get("scheme")
        identifier_value = row.get("identifier_value")
        if scheme is not None or identifier_value is not None:
            identifiers.add(
                (
                    _required_row_text(row, "scheme"),
                    _required_row_text(row, "identifier_value"),
                )
            )

    return tuple(
        DocumentSourceTarget(
            dataset_version=dataset_version,
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_name=canonical_name,
            product_family=product_family,
            required_role=(
                _PRODUCT_BINDINGS[product_family][0]
                if product_targets and product_family is not None
                else DocumentRole.INDEX_METHODOLOGY
            ),
            binding_role=(
                _PRODUCT_BINDINGS[product_family][1]
                if product_targets and product_family is not None
                else "subject_index"
            ),
            identifiers=tuple(sorted(identifiers)),
            cutoff_date=cutoff_date,
        )
        for (entity_id, entity_type, canonical_name, product_family), identifiers in sorted(
            grouped.items()
        )
    )


def _required_row_text(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _optional_row_text(
    row: Mapping[str, object], field_name: str
) -> str | None:
    value = row.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value
