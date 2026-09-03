"""V3 compact semantic-linking prompt and adaptive HCX response schema."""

from __future__ import annotations

import json
from typing import Any

from financial_agent.contracts.enums import Cardinality, ReferenceMentionType
from financial_agent.contracts.request import RequestContext

from .catalog import SemanticCatalogSnapshot
from .prompt import ResolverPromptEnvelope
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
from .view import (
    ResolverInvariantError,
    ResolverViewV3,
    model_safe_resolver_view_v3_payload,
)


SYSTEM_MESSAGE = (
    "You are the financial-product intent resolver. Return only one JSON object "
    "that conforms to the supplied response schema. Map offered source mention IDs "
    "to registered semantic IDs from the compact catalog. Select only offered IDs. "
    "When a mention cannot be grounded, put its ID in unmapped_mention_ids; when "
    "multiple meanings remain possible, return an ambiguous semantic link. Do not "
    "force a meaning for an uncertain mention. Leave entity, reference, context, "
    "and mutation arrays empty when the schema disables them. Do not create IDs, "
    "evidence text, or offsets."
)

_FRAME_ORDINAL = {"type": "integer", "minimum": 0, "maximum": 15}
_REASON_CODES = ("ambiguous", "explicit", "implicit", "policy_explicit", "unmapped")
_MODEL_SLOT_KINDS = tuple(
    item for item in SlotKind if item not in {SlotKind.UNIT, SlotKind.ENTITY}
)


def build_hybrid_prompt(
    context: RequestContext,
    view: ResolverViewV3,
    catalog: SemanticCatalogSnapshot,
) -> ResolverPromptEnvelope:
    """Create the V3 envelope while retaining the existing structured transport."""
    _validate_hybrid_catalog(view, catalog)
    return ResolverPromptEnvelope(
        system_message=SYSTEM_MESSAGE,
        user_message=json.dumps(
            {
                "context": context.model_dump(mode="json"),
                "view": model_safe_resolver_view_v3_payload(view),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        response_schema=build_hybrid_response_schema(view),
    )


def build_hybrid_response_schema(view: ResolverViewV3) -> dict[str, object]:
    """Build a closed V3 schema with only evidence-backed output branches."""
    mention_ids = tuple(sorted(item.mention_id for item in view.mention_spans.items))
    semantic_ids = tuple(
        sorted(card.semantic_id for card in view.compact_semantic_catalog.concepts)
    )
    reference_ids = tuple(
        sorted(item.reference_id for item in view.reference_candidates)
    )
    relation_ids = tuple(
        sorted(
            card.semantic_id
            for card in view.compact_semantic_catalog.concepts
            if card.concept_kind == "relation"
        )
    )
    entity_ids = tuple(
        sorted(item.entity_id for group in view.entity_candidates for item in group.items)
    )
    entity_mention_ids = tuple(
        sorted(group.mention_id for group in view.entity_candidates)
    )
    segment_ids = tuple(sorted({item.segment_id for item in view.mention_spans.items}))
    evidence_ids = tuple(sorted(item.evidence_id for item in view.evidence_candidates))
    action_choice = _axis_choice(
        tuple(view.action_ids), evidence_ids, max_selected_items=1
    )
    product_family_choice = _axis_choice(tuple(view.product_family_ids), evidence_ids)
    semantic_link = {
        "oneOf": [
            _object(
                {
                    "mention_id": _restricted_identifier(mention_ids),
                    "state": _enum_strings(("selected",)),
                    "semantic_ids": _restricted_identifier_array(
                        semantic_ids, min_items=1, max_items=1
                    ),
                    "reason_code": _enum_strings(("explicit", "implicit")),
                }
            ),
            _object(
                {
                    "mention_id": _restricted_identifier(mention_ids),
                    "state": _enum_strings(("ambiguous",)),
                    "semantic_ids": _restricted_identifier_array(
                        semantic_ids, min_items=2, unique_items=True
                    ),
                    "reason_code": _enum_strings(("ambiguous",)),
                }
            ),
        ]
    }
    entity_hint = _object(
        {
            "semantic_role": _enum_members(EntitySemanticRole),
            "relation_id": _restricted_identifier_array(relation_ids, max_items=1),
            "expected_entity_type_ids": _restricted_identifier_array(
                tuple(view.entity_type_ids), min_items=1
            ),
            "mention_id": _restricted_identifier_array(
                entity_mention_ids, max_items=1
            ),
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
            "entity_type_ids": _restricted_identifier_array(tuple(view.entity_type_ids)),
            "semantic_links": _array(semantic_link),
            "unmapped_mention_ids": _restricted_identifier_array(mention_ids),
            "semantic_coverage": _semantic_coverage_schema(),
            "entity_hints": _array(
                entity_hint, max_items=0 if not view.entity_output_enabled else None
            ),
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
            "reason_code": _enum_strings(_REASON_CODES),
        }
    )
    context_link = _object(
        {
            "reference_id": _restricted_identifier(reference_ids),
            "link_type": _enum_members(ContextLinkType),
            "source_role": _enum_members(SourceRole),
            "selector": _optional(_enum_members(Selector)),
            "selector_literal_candidate_id": _restricted_identifier_array(
                tuple(sorted(item.literal_id for item in view.literal_candidates)),
                max_items=1,
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
            "evidence_ids": _restricted_identifier_array(evidence_ids),
            "reason_code": _enum_strings(_REASON_CODES),
        }
    )
    reference_max_items = 0 if not view.reference_output_enabled else None
    return _object(
        {
            "proposal_schema_version": _enum_strings(("3.0",)),
            "frames": _array(frame, min_items=1, max_items=16),
            "references": _array(reference, max_items=reference_max_items),
            "context_links": _array(context_link, max_items=reference_max_items),
            "slot_mutations": _array(slot_mutation, max_items=reference_max_items),
            "semantic_flag_hints": _array(
                _object(
                    {
                        "semantic_tag": _enum_members(SemanticTag),
                        "evidence_ids": _restricted_identifier_array(evidence_ids),
                        "reason_code": _enum_strings(_REASON_CODES),
                    }
                )
            ),
            "frame_limit_exceeded": {"type": "boolean"},
        }
    )


def _validate_hybrid_catalog(
    view: ResolverViewV3, catalog: SemanticCatalogSnapshot
) -> None:
    compact_catalog = view.compact_semantic_catalog
    if (
        compact_catalog.source_catalog_hash != catalog.catalog_hash
        or compact_catalog.source_overlay_hash != catalog.overlay_hash
        or {card.semantic_id for card in compact_catalog.concepts}
        != set(catalog.concepts_by_id)
    ):
        raise ResolverInvariantError("CATALOG_VERSION_MISMATCH")


def _semantic_coverage_schema() -> dict[str, object]:
    return {
        "anyOf": [
            _object(
                {
                    "state": _enum_strings((SemanticCoverageState.COVERED.value,)),
                    "reason": _enum_strings((SemanticCoverageReason.NONE.value,)),
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
                }
            ),
        ]
    }


def _axis_choice(
    selected_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    *,
    max_selected_items: int | None = None,
) -> dict[str, object]:
    return _object(
        {
            "state": _enum_members(ChoiceState),
            "selected_ids": _restricted_identifier_array(
                selected_ids, max_items=max_selected_items
            ),
            "evidence_ids": _restricted_identifier_array(evidence_ids),
            "reason_code": _enum_strings(_REASON_CODES),
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
    unique_items: bool = False,
) -> dict[str, object]:
    schema: dict[str, object] = {"type": "array", "items": items}
    if min_items is not None:
        schema["minItems"] = min_items
    if max_items is not None:
        schema["maxItems"] = max_items
    if unique_items:
        schema["uniqueItems"] = True
    return schema


def _optional(items: dict[str, object]) -> dict[str, object]:
    return _array(items, max_items=1)


def _restricted_identifier_array(
    values: tuple[str, ...],
    *,
    min_items: int | None = None,
    max_items: int | None = None,
    unique_items: bool = False,
) -> dict[str, object]:
    if values:
        return _array(
            _enum_strings(values),
            min_items=min_items,
            max_items=max_items,
            unique_items=unique_items,
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
