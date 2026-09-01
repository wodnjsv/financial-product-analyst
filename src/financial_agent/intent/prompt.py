"""Prompt serialization and HCX-compatible proposal response schemas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from financial_agent.contracts.enums import Cardinality, ReferenceMentionType
from financial_agent.contracts.request import RequestContext

from .types import (
    ChoiceState,
    ContextLinkType,
    ReferenceForm,
    ReferenceTargetKind,
    Selector,
    SemanticCoverageReason,
    SemanticCoverageState,
    SemanticTag,
    SlotKind,
    SlotMutationKind,
    SourceRole,
)
from .view import ResolverView


SYSTEM_MESSAGE = (
    "You are the financial-product intent resolver. Return only one JSON object "
    "that conforms to the supplied response schema. Use the supplied definitions "
    "and original text to select only offered identifiers and frame ordinals. "
    "Do not create identifiers, evidence, text, or offsets."
)

REASON_CODES = ("ambiguous", "explicit", "implicit", "policy_explicit", "unmapped")
_FRAME_ORDINAL = {"type": "integer", "minimum": 0, "maximum": 15}


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
    """Build the restricted HCX schema for IntentResolutionProposalV2 only."""
    evidence_ids = _evidence_ids(view)
    reference_ids = _reference_ids(view)
    entity_ids = _entity_ids(view)
    entity_mention_ids = _entity_mention_ids(view)
    segment_ids = _segment_ids(view)
    evidence_identifier = _restricted_identifier_array(evidence_ids)
    reason_code = _enum_strings(REASON_CODES)
    action_choice = _axis_choice(
        _enum_strings(tuple(view.action_ids)), evidence_identifier, reason_code
    )
    product_family_choice = _axis_choice(
        _enum_strings(tuple(view.product_family_ids)), evidence_identifier, reason_code
    )
    slot_assignment = _slot_assignment_schema(view, evidence_identifier, reason_code)
    entity_hint = _object(
        {
            "mention_id": _restricted_identifier_array(entity_mention_ids, max_items=1),
            "candidate_entity_ids": _restricted_identifier_array(entity_ids),
        }
    )
    frame = _object(
        {
            "segment_ids": _restricted_identifier_array(segment_ids),
            "action_choice": action_choice,
            "product_family_choice": product_family_choice,
            "semantic_coverage": _semantic_coverage_schema(evidence_identifier),
            "slot_assignments": _array(slot_assignment),
            "entity_hints": _array(entity_hint),
            "produced_result_hints": _array(_enum_members(SourceRole)),
        }
    )
    reference = _object(
        {
            "reference_id": _restricted_identifier(reference_ids),
            "producer_frame_ordinals": _array(_FRAME_ORDINAL),
            "surface_presence": _enum_members(ReferenceMentionType),
            "reference_form": _enum_members(ReferenceForm),
            "grammatical_number": _optional(
                _enum_strings(("singular", "plural", "unknown"))
            ),
            "expected_target_kind": _optional(_enum_members(ReferenceTargetKind)),
            "expected_cardinality": _optional(_enum_members(Cardinality)),
            "status": _enum_strings(("resolved", "ambiguous", "unresolved")),
            "reason_code": reason_code,
        }
    )
    context_link = _object(
        {
            "reference_id": _restricted_identifier(reference_ids),
            "link_type": _enum_members(ContextLinkType),
            "source_role": _enum_members(SourceRole),
            "selector": _optional(_enum_members(Selector)),
            "selector_literal_candidate_id": _restricted_identifier_array(
                _literal_ids(view), max_items=1
            ),
            "producer_frame_ordinal": _FRAME_ORDINAL,
            "consumer_frame_ordinal": _FRAME_ORDINAL,
            "target_slot_kind": _optional(_enum_members(SlotKind)),
        }
    )
    slot_mutation = _object(
        {
            "consumer_frame_ordinal": _FRAME_ORDINAL,
            "slot_kind": _enum_members(SlotKind),
            "mutation_kind": _enum_members(SlotMutationKind),
            "source_frame_ordinal": _optional(_FRAME_ORDINAL),
            "evidence_ids": evidence_identifier,
            "reason_code": reason_code,
        }
    )
    semantic_flag = _object(
        {
            "semantic_tag": _enum_members(SemanticTag),
            "evidence_ids": evidence_identifier,
            "reason_code": reason_code,
        }
    )
    return _object(
        {
            "proposal_schema_version": _enum_strings(("2.0",)),
            "frames": _array(frame, max_items=16),
            "references": _array(reference, max_items=0 if not reference_ids else None),
            "context_links": _array(
                context_link, max_items=0 if not reference_ids else None
            ),
            "slot_mutations": _array(slot_mutation),
            "semantic_flag_hints": _array(semantic_flag),
            "frame_limit_exceeded": {"type": "boolean"},
        }
    )


def _semantic_coverage_schema(evidence_identifier: dict[str, object]) -> dict[str, object]:
    return _object(
        {
            "state": _enum_members(SemanticCoverageState),
            "reason": _enum_members(SemanticCoverageReason),
            "evidence_ids": evidence_identifier,
        }
    )


def _literal_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.literal_id for item in view.literal_candidates))


def _evidence_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.evidence_id for item in view.evidence_candidates))


def _reference_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.reference_id for item in view.reference_candidates))


def _segment_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *(item.segment_id for item in view.evidence_candidates),
                *(item.segment_id for item in view.reference_candidates),
                *(item.segment_id for item in view.literal_candidates),
            }
        )
    )


def _entity_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(
        sorted(item.entity_id for group in view.entity_candidates for item in group.items)
    )


def _entity_mention_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(group.mention_id for group in view.entity_candidates))


def _slot_assignment_schema(
    view: ResolverView,
    evidence_identifier: dict[str, object],
    reason_code: dict[str, object],
) -> dict[str, object]:
    return {
        "anyOf": [
            _object(
                {
                    "slot_kind": _enum_strings((slot_kind.value,)),
                    "value_ids": _restricted_identifier_array(
                        _slot_value_ids(view, slot_kind)
                    ),
                    "evidence_ids": evidence_identifier,
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
    selected_ids: dict[str, object],
    evidence_identifier: dict[str, object],
    reason_code: dict[str, object],
) -> dict[str, object]:
    return _object(
        {
            "state": _enum_members(ChoiceState),
            "selected_ids": _array(selected_ids),
            "evidence_ids": evidence_identifier,
            "reason_code": reason_code,
        }
    )


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


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


def _restricted_identifier(values: tuple[str, ...]) -> dict[str, object]:
    if values:
        return _enum_strings(values)
    return _string()


def _string() -> dict[str, object]:
    return {"type": "string"}


def _enum_strings(values: tuple[str, ...]) -> dict[str, object]:
    return {"type": "string", "enum": list(values)}


def _enum_members(enum_type: type[Any]) -> dict[str, object]:
    return _enum_strings(tuple(member.value for member in enum_type))
