"""Catalog-backed ResolverView v2 values for focused unit-test fixtures."""

from functools import lru_cache
from pathlib import Path

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.view import AxisDefinition


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def complete_entity_type_ids() -> tuple[str, ...]:
    return tuple(sorted(load_catalog(PROJECT_ROOT).entity_type_ids))


def complete_axis_definitions() -> tuple[AxisDefinition, ...]:
    return tuple(
        AxisDefinition(
            axis_kind=axis_kind,
            axis_id=axis_id,
            preferred_label_ko="검증 축",
            definition_ko="검증용 축 정의",
            surface_forms=(),
        )
        for axis_kind, axis_id in (
            *(("product_family", item.value) for item in ProductFamily),
            *(("action", item.value) for item in IntentType),
        )
    )
