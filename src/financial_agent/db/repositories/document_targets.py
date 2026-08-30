from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from financial_agent.db.schema.catalog import entity, identifier, product
from financial_agent.db.schema.relation import relation_record
from financial_agent.documents import DocumentRole, DocumentSourceTarget


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
