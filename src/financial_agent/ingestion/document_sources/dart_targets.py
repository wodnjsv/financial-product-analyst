"""Organizer-authoritative target inventory for DART document collection."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
import hashlib
import json
from typing import Literal, cast


OrganizerDartFamily = Literal["domestic_etf", "public_fund"]
_CUTOFF = date(2026, 8, 24)


@dataclass(frozen=True, slots=True)
class OrganizerDartProductRow:
    entity_id: str
    canonical_name: str
    product_family: str
    identifier_scheme: str
    identifier_value: str
    representative_entity_id: str | None
    representative_name: str | None
    manager_entity_id: str | None
    manager_name: str | None
    document_collection_block_reason: str | None = None


@dataclass(frozen=True, slots=True)
class OrganizerDartTarget:
    target_key: str
    product_family: OrganizerDartFamily
    representative_entity_id: str
    canonical_name: str
    member_entity_ids: tuple[str, ...]
    identifiers: tuple[tuple[str, str, str], ...]
    manager_bindings: tuple[tuple[str, str], ...]
    member_entity_names: tuple[tuple[str, str], ...] = ()
    source_product_name: str | None = None
    document_collection_block_reason: str | None = None

    @property
    def member_names(self) -> tuple[str, ...]:
        return tuple(name for _, name in self.member_entity_names)


@dataclass(frozen=True, slots=True)
class OrganizerDartInventory:
    dataset_version: str
    cutoff_date: date
    product_count: int
    targets: tuple[OrganizerDartTarget, ...]
    inventory_hash: str


@dataclass(slots=True)
class _ProductAccumulator:
    canonical_name: str
    product_family: OrganizerDartFamily
    identifiers: set[tuple[str, str]] = field(default_factory=set)
    representatives: set[tuple[str, str]] = field(default_factory=set)
    managers: set[tuple[str, str]] = field(default_factory=set)
    document_collection_block_reasons: set[str] = field(default_factory=set)


def build_organizer_dart_inventory(
    dataset_version: str,
    cutoff_date: date,
    rows: tuple[OrganizerDartProductRow, ...],
) -> OrganizerDartInventory:
    if not dataset_version.strip():
        raise ValueError("dataset_version must not be blank")
    if cutoff_date != _CUTOFF:
        raise ValueError("organizer DART cutoff must be 2026-08-24")

    products: dict[str, _ProductAccumulator] = {}
    identifier_owners: dict[tuple[str, str], str] = {}
    manager_names: dict[str, str] = {}
    for row in rows:
        _validate_row(row)
        current = products.setdefault(
            row.entity_id,
            _ProductAccumulator(
                canonical_name=row.canonical_name,
                product_family=cast(OrganizerDartFamily, row.product_family),
            ),
        )
        if (
            current.canonical_name != row.canonical_name
            or current.product_family != row.product_family
        ):
            raise ValueError("inconsistent organizer product identity")
        identifier_key = (row.identifier_scheme, row.identifier_value)
        prior_owner = identifier_owners.setdefault(identifier_key, row.entity_id)
        if prior_owner != row.entity_id:
            raise ValueError("organizer identifier assigned to multiple products")
        current.identifiers.add(identifier_key)
        if row.representative_entity_id is not None:
            current.representatives.add(
                (row.representative_entity_id, row.representative_name)
            )
        if row.manager_entity_id is not None:
            prior_name = manager_names.setdefault(
                row.manager_entity_id, row.manager_name
            )
            if prior_name != row.manager_name:
                raise ValueError("inconsistent organizer manager identity")
            current.managers.add((row.manager_entity_id, row.manager_name))
        if row.document_collection_block_reason is not None:
            current.document_collection_block_reasons.add(
                row.document_collection_block_reason
            )

    groups: dict[tuple[str, str], list[tuple[str, _ProductAccumulator, str]]] = {}
    for entity_id, product_values in products.items():
        representatives = product_values.representatives
        if len(representatives) > 1:
            raise ValueError("product has multiple representative groups")
        product_family = product_values.product_family
        canonical_name = product_values.canonical_name
        if representatives:
            representative_id, representative_name = next(iter(representatives))
        else:
            representative_id = entity_id
            representative_name = canonical_name
        groups.setdefault((product_family, representative_id), []).append(
            (entity_id, product_values, representative_name)
        )

    targets: list[OrganizerDartTarget] = []
    accounted_entities: set[str] = set()
    for (product_family, representative_id), members in sorted(groups.items()):
        member_ids = tuple(sorted(entity_id for entity_id, _, _ in members))
        if accounted_entities.intersection(member_ids):
            raise ValueError("organizer product assigned to multiple targets")
        accounted_entities.update(member_ids)
        representative_names = {
            representative_name for _, _, representative_name in members
        }
        if len(representative_names) != 1:
            raise ValueError("inconsistent representative name")
        identifiers = tuple(
            sorted(
                (entity_id, scheme, value)
                for entity_id, values, _ in members
                for scheme, value in values.identifiers
            )
        )
        block_reasons = {
            reason
            for _, values, _ in members
            for reason in values.document_collection_block_reasons
        }
        if len(block_reasons) > 1:
            raise ValueError("target has multiple collection block reasons")
        manager_bindings = tuple(
            sorted(
                {
                    (manager_id, manager_name)
                    for _, values, _ in members
                    for manager_id, manager_name in values.managers
                }
            )
        )
        targets.append(
            OrganizerDartTarget(
                target_key=f"{product_family}:{representative_id}",
                product_family=product_family,
                representative_entity_id=representative_id,
                canonical_name=next(iter(representative_names)),
                member_entity_ids=member_ids,
                identifiers=identifiers,
                manager_bindings=manager_bindings,
                member_entity_names=tuple(
                    sorted(
                        (entity_id, values.canonical_name)
                        for entity_id, values, _ in members
                    )
                ),
                document_collection_block_reason=(
                    next(iter(block_reasons)) if block_reasons else None
                ),
            )
        )
    if accounted_entities != set(products):
        raise ValueError("unaccounted organizer product")
    target_tuple = tuple(targets)
    payload = {
        "dataset_version": dataset_version,
        "cutoff_date": cutoff_date.isoformat(),
        "product_count": len(products),
        "targets": [asdict(target) for target in target_tuple],
    }
    inventory_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return OrganizerDartInventory(
        dataset_version=dataset_version,
        cutoff_date=cutoff_date,
        product_count=len(products),
        targets=target_tuple,
        inventory_hash=inventory_hash,
    )


def _validate_row(row: OrganizerDartProductRow) -> None:
    for field_name, value in (
        ("entity_id", row.entity_id),
        ("canonical_name", row.canonical_name),
        ("identifier_scheme", row.identifier_scheme),
        ("identifier_value", row.identifier_value),
    ):
        if not value.strip():
            raise ValueError(f"{field_name} must not be blank")
    if row.product_family not in {"domestic_etf", "public_fund"}:
        raise ValueError("product family is outside organizer DART scope")
    if row.product_family == "domestic_etf" and (
        row.representative_entity_id is not None
        or row.representative_name is not None
    ):
        raise ValueError("domestic ETF cannot have a representative fund")
    if (row.representative_entity_id is None) != (
        row.representative_name is None
    ):
        raise ValueError("representative binding is incomplete")
    if (row.manager_entity_id is None) != (row.manager_name is None):
        raise ValueError("manager binding is incomplete")
    for field_name, value in (
        ("representative_entity_id", row.representative_entity_id),
        ("representative_name", row.representative_name),
        ("manager_entity_id", row.manager_entity_id),
        ("manager_name", row.manager_name),
    ):
        if value is not None and not value.strip():
            raise ValueError(f"{field_name} must not be blank")
    if row.document_collection_block_reason not in {
        None,
        "representative_identifier_unavailable",
    }:
        raise ValueError("unsupported document collection block reason")
