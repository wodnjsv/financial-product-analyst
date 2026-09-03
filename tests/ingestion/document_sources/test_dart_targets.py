from __future__ import annotations

from datetime import date

import pytest

from financial_agent.ingestion.document_sources.dart_targets import (
    DartRecoveryProductState,
    OrganizerDartProductRow,
    build_organizer_dart_inventory,
    select_dart_recovery_targets,
)


CUTOFF = date(2026, 8, 24)


def _row(
    entity_id: str,
    *,
    family: str,
    identifier_scheme: str,
    identifier_value: str,
    representative_entity_id: str | None = None,
    representative_name: str | None = None,
    manager_entity_id: str | None = "manager-one",
    manager_name: str | None = "Manager One",
    document_collection_block_reason: str | None = None,
) -> OrganizerDartProductRow:
    return OrganizerDartProductRow(
        entity_id=entity_id,
        canonical_name=f"Canonical {entity_id}",
        product_family=family,
        identifier_scheme=identifier_scheme,
        identifier_value=identifier_value,
        representative_entity_id=representative_entity_id,
        representative_name=representative_name,
        manager_entity_id=manager_entity_id,
        manager_name=manager_name,
        document_collection_block_reason=document_collection_block_reason,
    )


def test_inventory_groups_only_exact_public_fund_relations_and_is_deterministic() -> None:
    rows = (
        _row(
            "fund-class-b",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-B",
            representative_entity_id="fund-representative",
            representative_name="Representative Fund",
        ),
        _row(
            "etf-one",
            family="domestic_etf",
            identifier_scheme="ISIN",
            identifier_value="KR7000000001",
        ),
        _row(
            "fund-class-a",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-A",
            representative_entity_id="fund-representative",
            representative_name="Representative Fund",
        ),
        _row(
            "fund-unrelated",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-C",
        ),
    )

    first = build_organizer_dart_inventory(
        "organizer-2026-08-24-v1", CUTOFF, rows
    )
    second = build_organizer_dart_inventory(
        "organizer-2026-08-24-v1", CUTOFF, tuple(reversed(rows))
    )

    assert first == second
    assert first.product_count == 4
    assert len(first.targets) == 3
    grouped = next(
        target
        for target in first.targets
        if target.representative_entity_id == "fund-representative"
    )
    assert grouped.member_entity_ids == ("fund-class-a", "fund-class-b")
    assert grouped.member_names == (
        "Canonical fund-class-a",
        "Canonical fund-class-b",
    )
    assert grouped.canonical_name == "Representative Fund"
    unrelated = next(
        target
        for target in first.targets
        if target.representative_entity_id == "fund-unrelated"
    )
    assert unrelated.member_entity_ids == ("fund-unrelated",)
    assert len(first.inventory_hash) == 64


def test_inventory_keeps_missing_and_ambiguous_managers_for_bounded_disposition() -> None:
    rows = (
        _row(
            "fund-one",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-1",
            manager_entity_id=None,
            manager_name=None,
        ),
        _row(
            "fund-one",
            family="public_fund",
            identifier_scheme="FSS_FUND",
            identifier_value="FSS-1",
            manager_entity_id="manager-a",
            manager_name="Manager A",
        ),
        _row(
            "fund-one",
            family="public_fund",
            identifier_scheme="FSS_FUND",
            identifier_value="FSS-1",
            manager_entity_id="manager-b",
            manager_name="Manager B",
        ),
    )

    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)

    assert inventory.targets[0].manager_bindings == (
        ("manager-a", "Manager A"),
        ("manager-b", "Manager B"),
    )


def test_inventory_preserves_an_evidence_derived_collection_block() -> None:
    row = _row(
        "fund-with-placeholder",
        family="public_fund",
        identifier_scheme="PRFD_ITM_NO",
        identifier_value="PF-W",
        document_collection_block_reason=(
            "representative_identifier_unavailable"
        ),
    )

    inventory = build_organizer_dart_inventory(
        "organizer-v1",
        CUTOFF,
        (row,),
    )

    assert inventory.targets[0].document_collection_block_reason == (
        "representative_identifier_unavailable"
    )


@pytest.mark.parametrize(
    "rows",
    (
        (
            _row(
                "product-one",
                family="domestic_bond",
                identifier_scheme="ISIN",
                identifier_value="KR7000000001",
            ),
        ),
        (
            _row(
                "product-one",
                family="domestic_etf",
                identifier_scheme="ISIN",
                identifier_value="KR7000000001",
                representative_entity_id="unexpected-group",
                representative_name="Unexpected",
            ),
        ),
    ),
)
def test_inventory_rejects_rows_outside_the_organizer_dart_contract(
    rows: tuple[OrganizerDartProductRow, ...],
) -> None:
    with pytest.raises(ValueError):
        build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)


def test_inventory_rejects_one_product_assigned_to_multiple_exact_groups() -> None:
    rows = (
        _row(
            "fund-one",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-1",
            representative_entity_id="representative-a",
            representative_name="Representative A",
        ),
        _row(
            "fund-one",
            family="public_fund",
            identifier_scheme="FSS_FUND",
            identifier_value="FSS-1",
            representative_entity_id="representative-b",
            representative_name="Representative B",
        ),
    )

    with pytest.raises(ValueError, match="multiple representative"):
        build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)


def test_inventory_rejects_one_identifier_assigned_to_multiple_products() -> None:
    rows = (
        _row(
            "fund-one",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-1",
        ),
        _row(
            "fund-two",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-1",
        ),
    )

    with pytest.raises(ValueError, match="identifier assigned"):
        build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)


def test_recovery_selection_keeps_only_missing_applicable_targets() -> None:
    rows = (
        _row(
            "complete",
            family="domestic_etf",
            identifier_scheme="ISIN",
            identifier_value="KR7000000001",
        ),
        _row(
            "missing",
            family="domestic_etf",
            identifier_scheme="ISIN",
            identifier_value="KR7000000002",
        ),
        _row(
            "etn",
            family="domestic_etf",
            identifier_scheme="ISIN",
            identifier_value="KR7000000003",
        ),
        _row(
            "private",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-private",
        ),
        _row(
            "public",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-public",
        ),
    )
    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)
    states = (
        DartRecoveryProductState("complete", "fund_prospectus", True),
        DartRecoveryProductState("missing", "fund_prospectus", False),
        DartRecoveryProductState("etn", "etn_not_applicable", True),
        DartRecoveryProductState("private", "private_fund_not_applicable", True),
        DartRecoveryProductState("public", "fund_prospectus", False),
    )

    selection = select_dart_recovery_targets(inventory, states)

    assert selection.already_embedded_target_ids == ("domestic_etf:complete",)
    assert selection.not_applicable_targets == (
        ("domestic_etf:etn", "etn_not_applicable"),
        ("public_fund:private", "private_fund_not_applicable"),
    )
    assert tuple(
        target.target_key for target in selection.actionable_inventory.targets
    ) == ("domestic_etf:missing", "public_fund:public")
    assert selection.actionable_inventory.product_count == inventory.product_count
    assert selection.actionable_inventory.inventory_hash == inventory.inventory_hash


def test_multi_class_public_fund_is_actionable_until_every_member_is_embedded() -> None:
    rows = (
        _row(
            "class-a",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-A",
            representative_entity_id="representative",
            representative_name="Representative",
        ),
        _row(
            "class-b",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-B",
            representative_entity_id="representative",
            representative_name="Representative",
        ),
    )
    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)

    partial = select_dart_recovery_targets(
        inventory,
        (
            DartRecoveryProductState("class-a", "fund_prospectus", True),
            DartRecoveryProductState("class-b", "fund_prospectus", False),
        ),
    )
    assert tuple(
        target.target_key for target in partial.actionable_inventory.targets
    ) == ("public_fund:representative",)
    assert partial.already_embedded_target_ids == ()

    complete = select_dart_recovery_targets(
        inventory,
        (
            DartRecoveryProductState("class-a", "fund_prospectus", True),
            DartRecoveryProductState("class-b", "fund_prospectus", True),
        ),
    )
    assert complete.already_embedded_target_ids == (
        "public_fund:representative",
    )
    assert complete.actionable_inventory.targets == ()


def test_recovery_selection_filters_private_members_from_mixed_public_target() -> None:
    rows = (
        _row(
            "class-a",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-A",
            representative_entity_id="representative",
            representative_name="Representative",
        ),
        _row(
            "class-b",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-B",
            representative_entity_id="representative",
            representative_name="Representative",
        ),
    )
    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)

    selection = select_dart_recovery_targets(
        inventory,
        (
            DartRecoveryProductState("class-a", "fund_prospectus", False),
            DartRecoveryProductState(
                "class-b", "private_fund_not_applicable", True
            ),
        ),
    )

    selected = selection.actionable_inventory.targets
    assert len(selected) == 1
    assert selected[0].product_family == "public_fund"
    assert selected[0].member_entity_ids == ("class-a",)
    assert selected[0].member_entity_names == (
        ("class-a", "Canonical class-a"),
    )
    assert selected[0].identifiers == (("class-a", "PRFD_ITM_NO", "PF-A"),)
    assert selected[0].manager_bindings == (("manager-one", "Manager One"),)
    assert selection.not_applicable_member_reason_counts == (
        ("private_fund_not_applicable", 1),
    )


def test_mixed_public_target_completion_uses_only_retained_public_members() -> None:
    rows = (
        _row(
            "class-a",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-A",
            representative_entity_id="representative",
            representative_name="Representative",
        ),
        _row(
            "class-b",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-B",
            representative_entity_id="representative",
            representative_name="Representative",
        ),
    )
    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)

    selection = select_dart_recovery_targets(
        inventory,
        (
            DartRecoveryProductState("class-a", "fund_prospectus", True),
            DartRecoveryProductState(
                "class-b", "private_fund_not_applicable", False
            ),
        ),
    )

    assert selection.actionable_inventory.targets == ()
    assert selection.already_embedded_target_ids == (
        "public_fund:representative",
    )
    assert selection.not_applicable_member_reason_counts == (
        ("private_fund_not_applicable", 1),
    )


def test_recovery_selection_rejects_unsupported_mixed_scopes() -> None:
    rows = (
        _row(
            "class-a",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-A",
            representative_entity_id="representative",
            representative_name="Representative",
        ),
        _row(
            "class-b",
            family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-B",
            representative_entity_id="representative",
            representative_name="Representative",
        ),
    )
    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)

    with pytest.raises(ValueError, match="mixed DART recovery scope"):
        select_dart_recovery_targets(
            inventory,
            (
                DartRecoveryProductState("class-a", "fund_prospectus", True),
                DartRecoveryProductState("class-b", "etn_not_applicable", True),
            ),
        )


def test_recovery_selection_requires_exactly_one_state_per_member() -> None:
    row = _row(
        "product",
        family="domestic_etf",
        identifier_scheme="ISIN",
        identifier_value="KR7000000001",
    )
    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, (row,))

    with pytest.raises(ValueError, match="DART recovery state mismatch"):
        select_dart_recovery_targets(inventory, ())

    with pytest.raises(ValueError, match="DART recovery state mismatch"):
        select_dart_recovery_targets(
            inventory,
            (
                DartRecoveryProductState("product", "fund_prospectus", False),
                DartRecoveryProductState("product", "fund_prospectus", False),
            ),
        )
