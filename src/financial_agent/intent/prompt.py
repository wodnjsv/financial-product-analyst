"""Prompt serialization and HCX-compatible proposal response schemas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from financial_agent.contracts.enums import Cardinality, ReferenceMentionType
from financial_agent.contracts.request import RequestContext

from .catalog import SemanticCatalogSnapshot
from .types import (
    ChoiceState,
    ContextLinkType,
    EntitySemanticRole,
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
from .view import ResolverView, validate_resolver_view_catalog


SYSTEM_MESSAGE = (
    "You are the financial-product intent resolver. Return only one JSON object "
    "that conforms to the supplied response schema. Use the supplied definitions "
    "and original text to select only offered identifiers and frame ordinals. "
    "Do not create identifiers, evidence, text, or offsets. "
    "실행 슬롯은 선택하지 말고 slot_assignments는 빈 배열로 반환한다. "
    "ProductFamily, Action, semantic tags, entity roles, context links, and "
    "semantic coverage만 판정한다. "
    "frame.entity_type_ids는 분석 대상 또는 관계 주체의 타입이다. "
    "entity_hints.semantic_role=relation_object이면 relation_id를 하나 선택하고, "
    "expected_entity_type_ids에는 그 관계의 객체 타입을 선택한다."
)

REASON_CODES = ("ambiguous", "explicit", "implicit", "policy_explicit", "unmapped")
_FRAME_ORDINAL = {"type": "integer", "minimum": 0, "maximum": 15}
_MODEL_SLOT_KINDS = tuple(
    item for item in SlotKind if item not in {SlotKind.UNIT, SlotKind.ENTITY}
)


@dataclass(frozen=True, slots=True)
class ResolverPromptEnvelope:
    system_message: str
    user_message: str
    response_schema: dict[str, object]


def build_prompt(
    context: RequestContext,
    view: ResolverView,
    catalog: SemanticCatalogSnapshot,
) -> ResolverPromptEnvelope:
    """Serialize request-scoped untrusted input only into the user message."""
    validate_resolver_view_catalog(view, catalog)
    return ResolverPromptEnvelope(
        system_message=SYSTEM_MESSAGE,
        user_message=json.dumps(
            {
                "context": context.model_dump(mode="json"),
                "view": view.model_dump(mode="json", exclude={"exact_semantic_locks"}),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        response_schema=build_clova_response_schema(view, catalog),
    )


def build_clova_response_schema(
    view: ResolverView, catalog: SemanticCatalogSnapshot
) -> dict[str, object]:
    """Build the restricted HCX schema for IntentResolutionProposalV2 only."""
    validate_resolver_view_catalog(view, catalog)
    evidence_ids = _evidence_ids(view)
    reference_ids = _reference_ids(view)
    entity_ids = _entity_ids(view)
    entity_mention_ids = _entity_mention_ids(view)
    segment_ids = _segment_ids(view)
    evidence_identifier = _restricted_identifier_array(evidence_ids)
    reason_code = _enum_strings(REASON_CODES)
    action_choice = _axis_choice(
        tuple(view.action_ids), evidence_identifier, reason_code, max_selected_items=1
    )
    product_family_choice = _axis_choice(
        tuple(view.product_family_ids), evidence_identifier, reason_code
    )
    entity_hint = _object(
        {
            "semantic_role": _enum_members(EntitySemanticRole),
            "relation_id": _restricted_identifier_array(
                _relation_ids(view), max_items=1
            ),
            "expected_entity_type_ids": _restricted_identifier_array(
                view.entity_type_ids, min_items=1
            ),
            "mention_id": _restricted_identifier_array(entity_mention_ids, max_items=1),
            "candidate_entity_ids": _restricted_identifier_array(entity_ids),
            "selected_candidate_ids": _restricted_identifier_array(
                entity_ids, max_items=1
            ),
        }
    )
    frame = _object(
        {
            "segment_ids": _restricted_identifier_array(segment_ids, min_items=1),
            "action_choice": action_choice,
            "product_family_choice": product_family_choice,
            "entity_type_ids": _restricted_identifier_array(
                view.entity_type_ids
            ),
            "semantic_coverage": _semantic_coverage_schema(evidence_identifier),
            "slot_assignments": _array(_string(), max_items=0),
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
            "target_slot_kind": _optional(
                _enum_strings(tuple(item.value for item in _MODEL_SLOT_KINDS))
            ),
        }
    )
    slot_mutation = _object(
        {
            "consumer_frame_ordinal": _FRAME_ORDINAL,
            "slot_kind": _enum_strings(
                tuple(item.value for item in _MODEL_SLOT_KINDS)
            ),
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
            "frames": _array(frame, min_items=1, max_items=16),
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
    uncovered_evidence = dict(evidence_identifier)
    uncovered_evidence["minItems"] = 1
    return {
        "anyOf": [
            _object(
                {
                    "state": _enum_strings((SemanticCoverageState.COVERED.value,)),
                    "reason": _enum_strings((SemanticCoverageReason.NONE.value,)),
                    "evidence_ids": _array(_string(), max_items=0),
                }
            ),
            _object(
                {
                    "state": _enum_strings(
                        (
                            SemanticCoverageState.PARTIAL.value,
                            SemanticCoverageState.UNMAPPED.value,
                        )
                    ),
                    "reason": _enum_strings(
                        tuple(
                            reason.value
                            for reason in SemanticCoverageReason
                            if reason is not SemanticCoverageReason.NONE
                        )
                    ),
                    "evidence_ids": uncovered_evidence,
                }
            ),
        ]
    }


def _literal_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.literal_id for item in view.literal_candidates))


def _evidence_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.evidence_id for item in view.evidence_candidates))


def _reference_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.reference_id for item in view.reference_candidates))


def _relation_ids(view: ResolverView) -> tuple[str, ...]:
    return tuple(sorted(item.relation_id for item in view.relation_definitions))


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


def _axis_choice(
    selected_ids: tuple[str, ...],
    evidence_identifier: dict[str, object],
    reason_code: dict[str, object],
    *,
    max_selected_items: int | None = None,
) -> dict[str, object]:
    return _object(
        {
            "state": _enum_members(ChoiceState),
            "selected_ids": _restricted_identifier_array(
                selected_ids, max_items=max_selected_items
            ),
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


def _array(
    items: dict[str, object],
    *,
    min_items: int | None = None,
    max_items: int | None = None,
) -> dict[str, object]:
    schema: dict[str, object] = {"type": "array", "items": items}
    if min_items is not None:
        schema["minItems"] = min_items
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def _optional(items: dict[str, object]) -> dict[str, object]:
    return _array(items, max_items=1)


def _restricted_identifier_array(
    values: tuple[str, ...],
    *,
    min_items: int | None = None,
    max_items: int | None = None,
) -> dict[str, object]:
    if values:
        return _array(
            _enum_strings(values), min_items=min_items, max_items=max_items
        )
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
