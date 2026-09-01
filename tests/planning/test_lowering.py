from pathlib import Path

import pytest

from financial_agent.contracts.values import decode_contract_value
from financial_agent.contracts.enums import IntentType
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.resolution import ValidatedSlotMutation
from financial_agent.intent.types import (
    ContextLinkType,
    SemanticTag,
    Selector,
    SlotKind,
    SlotMutationKind,
)
from financial_agent.planning.compiler import QueryPlanCompiler
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.registry import load_planning_registry

from .fixtures import frame, resolution, slot, view


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def compiler() -> QueryPlanCompiler:
    return QueryPlanCompiler(
        catalog=load_catalog(PROJECT_ROOT),
        registry=load_planning_registry(PROJECT_ROOT),
    )


@pytest.mark.parametrize("link_type", tuple(ContextLinkType))
def test_every_context_link_type_is_preserved_as_an_operation_parameter(
    link_type: ContextLinkType,
) -> None:
    source = resolution(context=True)
    link = source.context_links[0].model_copy(update={"link_type": link_type})
    linked = source.model_copy(update={"context_links": (link,)})

    result = compiler().compile(linked, view(context=True))

    assert result.query_plan is not None
    consumer = result.query_plan.operations[-1]
    assert f"link:{link_type.value}" in consumer.parameter_ids


@pytest.mark.parametrize("selector", tuple(Selector))
def test_every_selector_is_preserved_and_literal_selectors_are_decoded(
    selector: Selector,
) -> None:
    source = resolution(context=True)
    literal_id = (
        ("literal-limit-1",)
        if selector in {Selector.RANK_POSITION, Selector.TOP_N}
        else ()
    )
    link = source.context_links[0].model_copy(
        update={
            "selector": (selector,),
            "selector_literal_candidate_id": literal_id,
        }
    )
    linked = source.model_copy(update={"context_links": (link,)})

    result = compiler().compile(linked, view(context=True))

    assert result.query_plan is not None
    consumer = result.query_plan.operations[-1]
    assert f"selector:{selector.value}" in consumer.parameter_ids
    if literal_id:
        selector_filter = next(
            item
            for item in result.query_plan.filters
            if item.field_id == "selector_value:link-1"
        )
        assert decode_contract_value(selector_filter.value) == 1
        assert selector_filter.field_id in consumer.parameter_ids


def test_carryover_clones_the_source_value_without_duplicate_provenance() -> None:
    source = resolution(context=True)
    second = source.canonical_frames[1]
    assignments = tuple(
        item
        for item in second.slot_assignments
        if item.slot_kind is not SlotKind.SORT_KEY
    )
    carryover = ValidatedSlotMutation(
        slot_mutation_id="mutation-carry-sort",
        consumer_frame_id="frame-2",
        slot_kind=SlotKind.SORT_KEY,
        mutation_kind=SlotMutationKind.CARRYOVER,
        source_frame_id=("frame-1",),
    )
    carried_frame = second.model_copy(
        update={
            "slot_assignments": assignments,
            "slot_mutations": (carryover,),
        }
    )
    carried = source.model_copy(
        update={"canonical_frames": (source.canonical_frames[0], carried_frame)}
    )

    result = compiler().compile(carried, view(context=True))

    assert result.route is CompilationRoute.FAST
    assert result.query_plan is not None
    consumer = result.query_plan.operations[-1]
    assert "slot:sort_key:aum" in consumer.parameter_ids
    assert len({item.source_id for item in result.lowering_records}) == len(
        result.lowering_records
    )


@pytest.mark.parametrize(
    "mutation_kind",
    (SlotMutationKind.DELETE, SlotMutationKind.DONTCARE),
)
def test_removing_a_required_slot_abstains_instead_of_inventing_a_default(
    mutation_kind: SlotMutationKind,
) -> None:
    source = resolution()
    mutation = ValidatedSlotMutation(
        slot_mutation_id=f"mutation-{mutation_kind.value}",
        consumer_frame_id="frame-1",
        slot_kind=SlotKind.RESULT_LIMIT,
        mutation_kind=mutation_kind,
        source_frame_id=(),
    )
    frame = source.canonical_frames[0].model_copy(
        update={"slot_mutations": (mutation,)}
    )
    mutated = source.model_copy(update={"canonical_frames": (frame,)})

    result = compiler().compile(mutated, view())

    assert result.route is CompilationRoute.ABSTAIN
    assert result.blocking_issues[0].code == "REQUIRED_SLOT_MISSING"


def test_relation_screen_composes_graph_traversal_without_fake_filter_value() -> None:
    source = resolution(tags=(SemanticTag.RELATIONSHIP_REQUIRED,))
    relation_frame = frame(
        "frame-1",
        0,
        metric_id="aum",
        limit_id="literal-limit-5",
        action=IntentType.SCREEN,
        assignments=(slot("slot-relation", SlotKind.RELATION, ("managedBy",)),),
    )
    related = source.model_copy(update={"canonical_frames": (relation_frame,)})

    result = compiler().compile(related, view())

    assert result.route is CompilationRoute.COMPOSE
    assert result.query_plan is not None
    assert result.primitive_ids == ("lookup-products", "traverse-relations")
    assert "slot:relation:managedBy" in (
        result.query_plan.operations[-1].parameter_ids
    )
