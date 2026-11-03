from __future__ import annotations

import pytest

from financial_agent.contracts.enums import Cardinality, ReferenceMentionType
from financial_agent.intent.context import validate_context_graph
from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.hybrid_assembler import _validate_reference_ordinals
from financial_agent.intent.proposal import ProposedContextLink, ProposedReference
from financial_agent.intent.types import ContextLinkType, ReferenceForm, ReferenceTargetKind, Selector, SourceRole

from .test_context import _frame, _link, _reference, _state
from .test_hybrid_assembler import _proposal


@pytest.mark.parametrize("producer,consumer", [(0, 0), (1, 0)])
def test_self_and_forward_context_link_report_bounded_backward_frame_rules(producer: int, consumer: int) -> None:
    proposal = _proposal("mention-cost")
    reference = ProposedReference(
        reference_id="source-reference", producer_frame_ordinals=(producer,),
        surface_presence=ReferenceMentionType.EXPLICIT, reference_form=ReferenceForm.DEMONSTRATIVE,
        grammatical_number=("plural",), expected_target_kind=(ReferenceTargetKind.RESULT_SET,),
        expected_cardinality=(Cardinality.MANY,), status="resolved", reason_code="explicit",
    )
    link = ProposedContextLink(
        reference_id=reference.reference_id, link_type=ContextLinkType.CONSUME_RESULT_SET,
        source_role=SourceRole.CANDIDATES, selector=(Selector.ALL,), selector_literal_candidate_id=(),
        producer_frame_ordinal=producer, consumer_frame_ordinal=consumer, target_slot_kind=(),
    )
    proposal = proposal.model_copy(update={
        "frames": (proposal.frames[0], proposal.frames[0]),
        "references": (reference,), "context_links": (link,),
    })

    with pytest.raises(ResolverContractError, match="MODEL_INVALID_FRAME_REFERENCE") as caught:
        _validate_reference_ordinals(proposal, {reference.reference_id})

    assert caught.value.validation_feedback == ({
        "path": "context_links.0",
        "rule": "context_link_requires_backward_declared_producer",
        "valid_frame_ordinals": [0, 1], "producer_before_consumer": True,
        "allowed_producer_frame_ordinals": [], "allowed_source_roles": ["candidates"],
    },)
    corrected_reference = reference.model_copy(update={"producer_frame_ordinals": (0,)})
    corrected_link = link.model_copy(update={"producer_frame_ordinal": 0, "consumer_frame_ordinal": 1})
    _validate_reference_ordinals(proposal.model_copy(update={
        "references": (corrected_reference,), "context_links": (corrected_link,),
    }), {reference.reference_id})


@pytest.mark.parametrize("selector,literal", [((Selector.FIRST,), ()), ((), ("private-unoffered-literal",))])
def test_singleton_source_selector_reports_empty_required_arrays_without_echo(selector: tuple[Selector, ...], literal: tuple[str, ...]) -> None:
    frames = (_frame("f1", 0, roles=(SourceRole.RELATION_TARGET,)), _frame("f2", 1))
    reference = _reference(number="singular", target_kind=ReferenceTargetKind.RELATED_ENTITY, cardinality=Cardinality.ONE)
    link = _link(link_type=ContextLinkType.DERIVE_ENTITY, role=SourceRole.RELATION_TARGET, selector=selector, selector_literal=literal)
    state = _state(frames=frames, references=(reference,), links=(link,))

    with pytest.raises(ResolverContractError, match="INVALID_CONTEXT_GRAPH") as caught:
        validate_context_graph(state)

    assert caught.value.validation_feedback == ({
        "path": "context_links", "rule": "singleton_source_disallows_selector",
        "source_role": "relation_target", "required_selector": [],
        "required_selector_literal_candidate_id": [],
    },)
    assert "private-unoffered-literal" not in str(caught.value.validation_feedback)
    corrected_link = link.model_copy(update={"selector": (), "selector_literal_candidate_id": ()})
    corrected = validate_context_graph(_state(frames=frames, references=(reference,), links=(corrected_link,)))
    assert len(corrected.context_links) == 1
