from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.schema.operations import active_dataset, dataset_version
from financial_agent.db.schema.evidence import (
    evidence_record,
    evidence_relation_origin,
)
from financial_agent.db.schema.relation import relation_record


_GIB = 1024**3
_STORAGE_INCREMENT_GIB = 10


class CapacityProbeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
