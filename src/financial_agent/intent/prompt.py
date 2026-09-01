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

REASON_CODES = ("ambiguous", "explicit", "implicit", "policy_explicit", "unmapped")


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
    entity_ids = _entity_ids(view)
    entity_mention_ids = _entity_mention_ids(view)
    target_mention_ids = _target_mention_ids(view)
    entity_type_ids = _entity_type_ids(view)

    identifier = _string()
    entity_identifier = _restricted_identifier_array(entity_ids)
    entity_type_identifier = _restricted_identifier_array(entity_type_ids)
    reason_code = _enum_strings(REASON_CODES)
    evidence_span = _object(
        {
            "span_id": identifier,
            "segment_id": identifier,
            "start_char": _integer(minimum=0),
            "end_char": _integer(minimum=0),
            "text": _string(),
        }
    )
    action_choice = _axis_choice(_enum_strings(tuple(view.action_ids)), reason_code)
    product_family_choice = _axis_choice(
        _enum_strings(tuple(view.product_family_ids)), reason_code
    )
    slot_assignment = _slot_assignment_schema(view, identifier, reason_code)
    entity_hint = _object(
        {
            "entity_hint_id": identifier,
            "mention_id": _restricted_identifier_array(entity_mention_ids, max_items=1),
            "evidence_span_ids": _array(identifier),
            "expected_entity_type_ids": entity_type_identifier,
            "candidate_entity_ids": entity_identifier,
            "selected_candidate_ids": _restricted_identifier_array(entity_ids, max_items=1),
            "reason_code": reason_code,
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
            "candidate_target_mention_ids": _restricted_identifier_array(target_mention_ids),
            "status": _enum_strings(("resolved", "ambiguous", "unresolved")),
            "reason_code": reason_code,
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
            "reason_code": reason_code,
        }
    )
    semantic_flag_hint = _object(
        {
            "semantic_tag": _enum_members(SemanticTag),
            "evidence_span_ids": _array(identifier),
            "reason_code": reason_code,
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


def _literal_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.literal_id for item in view.literal_candidates))


def _entity_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(
        sorted(item.entity_id for group in view.entity_candidates for item in group.items)
    )


def _entity_mention_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(group.mention_id for group in view.entity_candidates))


def _target_mention_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *(group.mention_id for group in view.semantic_candidates),
                *(group.mention_id for group in view.entity_candidates),
            }
        )
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


def _slot_assignment_schema(
    view: ResolverView,
    identifier: dict[str, object],
    reason_code: dict[str, object],
) -> dict[str, object]:
    return {
        "anyOf": [
            _object(
                {
                    "slot_assignment_id": identifier,
                    "slot_kind": _enum_strings((slot_kind.value,)),
                    "value_ids": _restricted_identifier_array(
                        _slot_value_ids(view, slot_kind)
                    ),
                    "evidence_span_ids": _array(identifier),
                    "reason_code": reason_code,
                }
            )
            for slot_kind in SlotKind
        ]
    }


def _slot_value_ids(view: ResolverView, slot_kind: SlotKind) -> tuple[str, ...]:
    if slot_kind is SlotKind.ENTITY:
        return _entity_ids(view)
    if slot_kind is SlotKind.RELATION:
        return tuple(sorted(item.relation_id for item in view.relation_definitions))
    if slot_kind is SlotKind.DOCUMENT_TOPIC:
        return _concept_ids(view, {"document_topic"})
    if slot_kind is SlotKind.METRIC:
        return _concept_ids(view, {"metric"})
    if slot_kind in {
        SlotKind.SORT_KEY,
        SlotKind.COMPARISON_BASIS,
        SlotKind.SIMILARITY_ANCHOR,
    }:
        return _concept_ids(view, {"attribute", "metric"})
    if slot_kind is SlotKind.FILTER_OPERATOR:
        return tuple(
            sorted(
                {
                    *(value for item in view.concept_definitions for value in item.allowed_operators),
                    *(value for item in view.concept_definitions for value in item.required_qualifiers),
                    *(value for item in view.relation_definitions for value in item.required_qualifiers),
                }
            )
        )
    literal_kinds = {
        SlotKind.FILTER_VALUE: {"number", "percentage", "money", "currency", "date", "period"},
        SlotKind.PERIOD: {"period"},
        SlotKind.CURRENCY: {"currency"},
        SlotKind.SORT_DIRECTION: {"sort_direction"},
        SlotKind.RESULT_LIMIT: {"result_limit"},
        SlotKind.DATE_SCOPE: {"date"},
    }.get(slot_kind)
    if literal_kinds is None:
        return ()
    return tuple(
        sorted(
            item.literal_id
            for item in view.literal_candidates
            if item.kind in literal_kinds
        )
    )


def _concept_ids(view: ResolverView, kinds: set[str]) -> tuple[str, ...]:
    return tuple(
        sorted(item.concept_id for item in view.concept_definitions if item.kind in kinds)
    )


def _axis_choice(
    selected_ids: dict[str, object], reason_code: dict[str, object]
) -> dict[str, object]:
    return _object(
        {
            "state": _enum_members(ChoiceState),
            "selected_ids": _array(selected_ids),
            "evidence_span_ids": _array(_string()),
            "reason_code": reason_code,
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
