from __future__ import annotations

import json
from pathlib import Path

from financial_agent.intent.prompt import model_safe_view_payload
from financial_agent.ingestion.mapping import domestic_etp, overseas_etp, public_fund
from financial_agent.planning.physical_bindings import load_physical_binding_registry
from tests.planning.fixtures import view


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_registered_metric_ids_are_present_in_tracked_ingestion_definitions() -> None:
    registry = load_physical_binding_registry(PROJECT_ROOT)
    mapped_ids = {
        *(f"organizer.pref01n001.{spec[0]}" for spec in domestic_etp._METRIC_SPECS.values()),
        *(f"organizer.pref02n001.{spec[0]}" for spec in overseas_etp._METRIC_SPECS.values()),
        *(f"organizer.prfd01n001.{spec[0]}" for spec in public_fund._METRIC_SPECS.values()),
    }

    assert {
        metric_id
        for binding in registry.bindings_by_id.values()
        for metric_id in binding.approved_metric_ids
    } <= mapped_ids
    assert registry.binding_for("public_fund", "aum").approved_metric_ids == (
        "organizer.prfd01n001.net_assets",
    )


def test_public_fund_fee_binding_never_sums_component_fees() -> None:
    binding = load_physical_binding_registry(PROJECT_ROOT).binding_for(
        "public_fund", "fee_rate"
    )

    assert binding is not None
    assert binding.approved_metric_ids == ()
    serialized = binding.model_dump_json()
    assert "manager_fee_rate" not in serialized
    assert "administration_fee_rate" not in serialized
    assert "sales_fee_rate" not in serialized
    assert "trustee_fee_rate" not in serialized


def test_physical_metric_ids_never_enter_hcx_view_payload() -> None:
    registry = load_physical_binding_registry(PROJECT_ROOT)
    payload = json.dumps(model_safe_view_payload(view()), ensure_ascii=False)

    for binding in registry.bindings_by_id.values():
        for metric_id in binding.approved_metric_ids:
            assert metric_id not in payload
    assert "semantic-sql-bindings" not in payload
