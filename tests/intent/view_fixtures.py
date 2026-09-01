"""Complete ResolverView v2 values for focused unit-test fixtures."""

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.view import AxisDefinition


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
