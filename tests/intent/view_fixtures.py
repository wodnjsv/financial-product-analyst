"""Complete ResolverView v2 values for focused unit-test fixtures."""

from financial_agent.contracts.enums import IntentType, ProductFamily
from financial_agent.intent.view import AxisDefinition


ENTITY_TYPE_IDS = (
    "AssetManager",
    "Company",
    "CreditGrade",
    "ETF",
    "EquitySecurity",
    "FinancialProduct",
    "FundShareClass",
    "Index",
    "Industry",
    "Issuer",
    "Market",
    "OfficialDocument",
    "Organization",
    "PolicyProgram",
    "ProductRiskGrade",
    "PublicFund",
    "RepresentativeFund",
    "RiskFactor",
    "Security",
    "Theme",
)


def complete_entity_type_ids() -> tuple[str, ...]:
    return ENTITY_TYPE_IDS


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
