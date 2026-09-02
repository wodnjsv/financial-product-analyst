from pathlib import Path

import pytest

from financial_agent.contracts.enums import IntentType
from financial_agent.intent.task_contracts import (
    load_task_contract_registry,
    resolve_task_contract,
)
from financial_agent.intent.types import SemanticTag, SlotKind


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_registry_covers_every_action_and_has_stable_hash() -> None:
    first = load_task_contract_registry(PROJECT_ROOT)
    second = load_task_contract_registry(PROJECT_ROOT)

    assert set(first.contracts_by_action) == set(IntentType)
    assert first.registry_hash == second.registry_hash
    assert len(first.registry_hash) == 64


def test_rank_contract_requires_sort_key_and_result_limit() -> None:
    registry = load_task_contract_registry(PROJECT_ROOT)

    contract = resolve_task_contract(
        registry,
        action=IntentType.RANK,
        tags=(),
        relation_required=False,
    )

    assert contract.contract_id == "rank.v1"
    assert contract.required_slot_kinds == (
        SlotKind.SORT_KEY,
        SlotKind.RESULT_LIMIT,
    )


def test_document_and_relation_requirements_are_server_resolved() -> None:
    registry = load_task_contract_registry(PROJECT_ROOT)

    contract = resolve_task_contract(
        registry,
        action=IntentType.EXPLAIN,
        tags=(SemanticTag.DOCUMENT_GROUNDED,),
        relation_required=True,
    )

    assert contract.required_slot_kinds == (
        SlotKind.RELATION,
        SlotKind.DOCUMENT_TOPIC,
    )


def test_registry_rejects_unknown_slot_kind(tmp_path: Path) -> None:
    path = tmp_path / "config" / "intent"
    path.mkdir(parents=True)
    (path / "task-input-contracts.v1.json").write_text(
        """
        {
          "registry_version": "bad.v1",
          "contracts": [
            {
              "contract_id": "lookup.v1",
              "action_id": "lookup",
              "required_slot_kinds": ["invented"],
              "optional_slot_kinds": [],
              "result_shape": "product_list"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid task contract registry"):
        load_task_contract_registry(tmp_path)
