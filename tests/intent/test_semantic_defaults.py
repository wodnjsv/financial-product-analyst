from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from financial_agent.intent.semantic_defaults import (
    DatasetSemanticDefaultsV1,
    SemanticAsOfDefaultV1,
    load_semantic_default_policy_registry,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_registry_contains_only_the_pinned_active_dataset_aum_policy() -> None:
    registry = load_semantic_default_policy_registry(PROJECT_ROOT)

    assert registry.registry_version == "semantic-default-policy-registry.v1"
    assert tuple(registry.policies_by_id) == ("active-dataset-as-of.v1",)
    policy = registry.policies_by_id["active-dataset-as-of.v1"]
    assert policy.kind == "default"
    assert policy.eligible_semantic_ids == ("aum",)
    assert policy.eligible_product_family_ids == (
        "domestic_etf",
        "overseas_etf",
        "public_fund",
    )


def test_dataset_semantic_defaults_are_strict_immutable_runtime_records() -> None:
    defaults = DatasetSemanticDefaultsV1(
        dataset_version="dataset-v1",
        manifest_hash="0" * 64,
        defaults=(
            SemanticAsOfDefaultV1(
                default_record_id="dataset-v1-overseas-etf-aum",
                product_family_id="overseas_etf",
                semantic_id="aum",
                as_of_date=date(2026, 8, 21),
            ),
        ),
    )

    assert defaults.schema_version == "1.0"
    with pytest.raises(ValidationError, match="Instance is frozen"):
        defaults.dataset_version = "dataset-v2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        DatasetSemanticDefaultsV1.model_validate(
            {
                **defaults.model_dump(mode="json"),
                "runtime_date": "2026-08-21",
            }
        )


def test_dataset_semantic_defaults_reject_duplicate_record_ids() -> None:
    record = SemanticAsOfDefaultV1(
        default_record_id="dataset-v1-overseas-etf-aum",
        product_family_id="overseas_etf",
        semantic_id="aum",
        as_of_date=date(2026, 8, 21),
    )

    with pytest.raises(ValidationError, match="DUPLICATE_SEMANTIC_DEFAULT_RECORD_ID"):
        DatasetSemanticDefaultsV1(
            dataset_version="dataset-v1",
            manifest_hash="0" * 64,
            defaults=(record, record),
        )
