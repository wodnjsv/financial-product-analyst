from __future__ import annotations

import pytest

from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.hybrid_assembler import assemble_hybrid_proposal
from financial_agent.intent.proposal import ProposedAxisChoice
from financial_agent.intent.types import ChoiceState

from .test_hybrid_assembler import _choice, _inputs, _proposal


@pytest.mark.parametrize("state,selected", [
    (ChoiceState.AMBIGUOUS, ("domestic_etf", "overseas_etf")),
    (ChoiceState.UNMAPPED, ("domestic_etf",)),
    (ChoiceState.SELECTED, ()),
])
def test_invalid_family_choice_reports_offered_ids_and_exact_field(state: ChoiceState, selected: tuple[str, ...]) -> None:
    _, normalized, view, catalog, mention_id = _inputs()
    proposal = _proposal(mention_id)
    frame = proposal.frames[0].model_copy(update={
        "product_family_choice": ProposedAxisChoice(
            state=state, selected_ids=selected, evidence_ids=(), reason_code="ambiguous"
        ),
    })

    with pytest.raises(ResolverContractError, match="MODEL_SCHEMA_INVALID") as caught:
        assemble_hybrid_proposal(proposal.model_copy(update={"frames": (frame,)}), normalized, view, catalog)

    assert caught.value.validation_feedback == ({
        "path": "frames.0.product_family_choice.selected_ids",
        "rule": "axis_choice_state_cardinality",
        "selected_state_min_items": 1,
        "unselected_state_max_items": 0,
        "allowed_values": sorted(view.product_family_ids),
    },)


def test_invalid_action_choice_does_not_echo_unoffered_model_text() -> None:
    _, normalized, view, catalog, mention_id = _inputs()
    proposal = _proposal(mention_id)
    frame = proposal.frames[0].model_copy(update={
        "action_choice": ProposedAxisChoice(
            state=ChoiceState.AMBIGUOUS, selected_ids=("unoffered-private-model-text",),
            evidence_ids=(), reason_code="ambiguous",
        ),
    })

    with pytest.raises(ResolverContractError, match="MODEL_SCHEMA_INVALID") as caught:
        assemble_hybrid_proposal(proposal.model_copy(update={"frames": (frame,)}), normalized, view, catalog)

    feedback = caught.value.validation_feedback[0]
    assert feedback["path"] == "frames.0.action_choice.selected_ids"
    assert feedback["allowed_values"] == sorted(view.action_ids)
    assert "unoffered-private-model-text" not in str(caught.value.validation_feedback)


@pytest.mark.parametrize("relation_id,family", [("managedBy", "domestic_etf"), ("issuedBy", "domestic_bond")])
def test_missing_relation_subject_type_reports_registered_endpoint_types(relation_id: str, family: str) -> None:
    _, normalized, view, catalog, mention_id = _inputs()
    proposal = _proposal(mention_id, relation_id)
    frame = proposal.frames[0].model_copy(update={
        "product_family_choice": _choice(family), "entity_type_ids": (),
    })

    with pytest.raises(ResolverContractError, match="MODEL_INVALID_RELATION") as caught:
        assemble_hybrid_proposal(proposal.model_copy(update={"frames": (frame,)}), normalized, view, catalog)

    allowed_types = sorted(catalog.concepts_by_id[relation_id].subject_ontology_types)
    assert caught.value.validation_feedback == ({
        "path": "frames.0.entity_type_ids",
        "rule": "relation_subject_type_missing",
        "relation_subject_types": [{"relation_id": relation_id, "allowed_entity_type_ids": allowed_types}],
    },)
    assert set(allowed_types) <= set(view.entity_type_ids)
    corrected = frame.model_copy(update={"entity_type_ids": (allowed_types[0],)})
    draft = assemble_hybrid_proposal(proposal.model_copy(update={"frames": (corrected,)}), normalized, view, catalog)
    assert draft.intent_frames[0].entity_type_ids == (allowed_types[0],)
