"""Prompt serialization and HCX-compatible response-schema construction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from financial_agent.contracts.request import RequestContext
from financial_agent.contracts.enums import Cardinality, ReferenceMentionType

from .types import (
    ChoiceState,
    ContextLinkType,
    ReferenceForm,
    ReferenceTargetKind,
    Selector,
    SemanticTag,
    SlotKind,
    SlotMutationKind,
    SourceRole,
)
from .view import ResolverView


SYSTEM_MESSAGE = (
    "You are the financial-product intent resolver. Return only one JSON object "
    "that conforms to the supplied response schema. Select only offered identifiers; "
    "do not guess. Every selected conclusion must be supported by exact original-text "
    "evidence spans."
)


@dataclass(frozen=True, slots=True)
class ResolverPromptEnvelope:
    system_message: str
    user_message: str
    response_schema: dict[str, object]


def build_prompt(context: RequestContext, view: ResolverView) -> ResolverPromptEnvelope:
    """Serialize request-scoped untrusted input only into the user message."""
    return ResolverPromptEnvelope(
        system_message=SYSTEM_MESSAGE,
        user_message=json.dumps(
            {
                "context": context.model_dump(mode="json"),
                "view": view.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        response_schema=build_clova_response_schema(view),
    )


def build_clova_response_schema(view: ResolverView) -> dict[str, object]:
    """Build the restricted JSON Schema subset accepted by HCX Structured Outputs."""
    offered_ids = _offered_ids(view)
    entity_ids = _entity_ids(view)
    entity_type_ids = _entity_type_ids(view)

    identifier = _string()
    offered_identifier = _restricted_identifier_array(offered_ids)
    entity_identifier = _restricted_identifier_array(entity_ids)
    entity_type_identifier = _restricted_identifier_array(entity_type_ids)
    evidence_span = _object(
        {
            "span_id": identifier,
            "segment_id": identifier,
            "start_char": _integer(minimum=0),
            "end_char": _integer(minimum=0),
            "text": _string(),
        }
    )
    action_choice = _axis_choice(_enum_strings(tuple(view.action_ids)))
    product_family_choice = _axis_choice(_enum_strings(tuple(view.product_family_ids)))
    slot_assignment = _object(
        {
            "slot_assignment_id": identifier,
            "slot_kind": _enum_members(SlotKind),
            "value_ids": offered_identifier,
            "evidence_span_ids": _array(identifier),
            "reason_code": identifier,
        }
    )
    entity_hint = _object(
        {
            "entity_hint_id": identifier,
            "mention_id": _optional(identifier),
            "evidence_span_ids": _array(identifier),
            "expected_entity_type_ids": entity_type_identifier,
            "candidate_entity_ids": entity_identifier,
            "selected_candidate_ids": _restricted_identifier_array(entity_ids, max_items=1),
            "reason_code": identifier,
        }
    )
    reference_hint = _object(
        {
            "reference_id": identifier,
            "segment_id": identifier,
            "evidence_span_ids": _array(identifier),
            "surface_presence": _enum_members(ReferenceMentionType),
            "reference_form": _enum_members(ReferenceForm),
            "grammatical_number": _optional(_enum_strings(("singular", "plural", "unknown"))),
            "expected_target_kind": _optional(_enum_members(ReferenceTargetKind)),
            "expected_cardinality": _optional(_enum_members(Cardinality)),
            "candidate_target_frame_ids": _array(identifier),
            "candidate_target_mention_ids": _array(identifier),
            "status": _enum_strings(("resolved", "ambiguous", "unresolved")),
            "reason_code": identifier,
        }
    )
    context_link_hint = _object(
        {
            "context_link_id": identifier,
            "reference_id": identifier,
            "link_type": _enum_members(ContextLinkType),
            "source_role": _enum_members(SourceRole),
            "selector": _optional(_enum_members(Selector)),
            "selector_literal_candidate_id": _restricted_identifier_array(
                _literal_ids(view), max_items=1
            ),
            "producer_frame_id": identifier,
            "consumer_frame_id": identifier,
            "target_slot_kind": _optional(_enum_members(SlotKind)),
        }
    )
    slot_mutation = _object(
        {
            "slot_mutation_id": identifier,
            "consumer_frame_id": identifier,
            "slot_kind": _enum_members(SlotKind),
            "mutation_kind": _enum_members(SlotMutationKind),
            "source_frame_id": _optional(identifier),
            "evidence_span_ids": _array(identifier),
            "reason_code": identifier,
        }
    )
    semantic_flag_hint = _object(
        {
            "semantic_tag": _enum_members(SemanticTag),
            "evidence_span_ids": _array(identifier),
            "reason_code": identifier,
        }
    )
    intent_frame = _object(
        {
            "frame_id": identifier,
            "ordinal": _integer(minimum=0),
            "segment_ids": _array(identifier),
            "evidence_span_ids": _array(identifier),
            "normalized_intent_argument": _string(),
            "action_choice": action_choice,
            "product_family_choice": product_family_choice,
            "entity_type_ids": entity_type_identifier,
            "entity_hint_ids": _array(identifier),
            "slot_assignments": _array(slot_assignment),
            "produced_result_hints": _array(_enum_members(SourceRole)),
        }
    )
    return _object(
        {
            "evidence_spans": _array(evidence_span),
            "intent_frames": _array(intent_frame, max_items=16),
            "entity_hints": _array(entity_hint),
            "reference_hints": _array(reference_hint),
            "context_link_hints": _array(context_link_hint),
            "slot_mutations": _array(slot_mutation),
            "semantic_flag_hints": _array(semantic_flag_hint),
            "frame_limit_exceeded": {"type": "boolean"},
        }
    )


def _offered_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *view.product_family_ids,
                *view.action_ids,
                *_semantic_ids(view),
                *(item.concept_id for item in view.concept_definitions),
                *(item.relation_id for item in view.relation_definitions),
                *_literal_ids(view),
                *_entity_ids(view),
                *_entity_type_ids(view),
                *(item for concept in view.concept_definitions for item in concept.allowed_product_families),
                *(item for concept in view.concept_definitions for item in concept.allowed_ontology_types),
                *(item for concept in view.concept_definitions for item in concept.required_qualifiers),
                *(item for concept in view.concept_definitions for item in concept.allowed_operators),
                *(item for relation in view.relation_definitions for item in relation.subject_ontology_types),
                *(item for relation in view.relation_definitions for item in relation.object_ontology_types),
                *(item for relation in view.relation_definitions for item in relation.required_qualifiers),
            }
        )
    )


def _semantic_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.semantic_id
            for group in view.semantic_candidates
            for item in group.items
        )
    )


def _literal_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.literal_id for item in view.literal_candidates))


def _entity_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(
        sorted(item.entity_id for group in view.entity_candidates for item in group.items)
    )


def _entity_type_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *(
                    ontology_type_id
                    for group in view.entity_candidates
                    for item in group.items
                    for ontology_type_id in item.ontology_type_ids
                ),
                *(item for concept in view.concept_definitions for item in concept.allowed_ontology_types),
                *(item for relation in view.relation_definitions for item in relation.subject_ontology_types),
                *(item for relation in view.relation_definitions for item in relation.object_ontology_types),
            }
        )
    )


def _axis_choice(selected_ids: dict[str, object]) -> dict[str, object]:
    return _object(
        {
            "state": _enum_members(ChoiceState),
            "selected_ids": _array(selected_ids),
            "evidence_span_ids": _array(_string()),
            "reason_code": _string(),
        }
    )


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {"type": "object", "properties": properties, "required": list(properties)}


def _array(items: dict[str, object], *, max_items: int | None = None) -> dict[str, object]:
    schema: dict[str, object] = {"type": "array", "items": items}
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def _optional(items: dict[str, object]) -> dict[str, object]:
    return _array(items, max_items=1)


def _restricted_identifier_array(
    values: tuple[str, ...], *, max_items: int | None = None
) -> dict[str, object]:
    if values:
        return _array(_enum_strings(values), max_items=max_items)
    return _array(_string(), max_items=0)


def _string() -> dict[str, object]:
    return {"type": "string"}


def _integer(*, minimum: int) -> dict[str, object]:
    return {"type": "integer", "minimum": minimum}


def _enum_strings(values: tuple[str, ...]) -> dict[str, object]:
    return {"type": "string", "enum": list(values)}


def _enum_members(enum_type: type[Any]) -> dict[str, object]:
    return _enum_strings(tuple(member.value for member in enum_type))
