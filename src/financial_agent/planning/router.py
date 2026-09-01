from __future__ import annotations

from dataclasses import dataclass

from financial_agent.intent.resolution import ValidatedIntentResolutionV2
from financial_agent.intent.types import (
    ResolutionStatus,
    SemanticCoverageReason,
    SemanticCoverageState,
    SemanticTag,
)

from .contracts import CompilationRoute
from .registry import ArchetypeDefinition, PlanningRegistry


POLICY_TAGS = frozenset(
    {
        SemanticTag.PERSONALIZED_ADVICE,
        SemanticTag.ORDER_EXECUTION,
        SemanticTag.FUTURE_FORECAST,
        SemanticTag.REALTIME_REQUIRED,
    }
)


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: CompilationRoute
    archetype: ArchetypeDefinition | None = None
    issue_code: str | None = None


def decide_route(
    resolution: ValidatedIntentResolutionV2,
    registry: PlanningRegistry,
) -> RouteDecision:
    if POLICY_TAGS & set(resolution.final_tags):
        return RouteDecision(CompilationRoute.ABSTAIN, issue_code="POLICY_BLOCKED")
    if resolution.resolution_status is ResolutionStatus.CONTEXT_UNRESOLVED:
        return RouteDecision(
            CompilationRoute.ABSTAIN,
            issue_code="CONTEXT_UNRESOLVED",
        )
    if resolution.resolution_status is ResolutionStatus.AMBIGUOUS:
        return RouteDecision(CompilationRoute.ABSTAIN, issue_code="SEMANTIC_AMBIGUOUS")

    coverage = tuple(
        frame.semantic_coverage[0] for frame in resolution.canonical_frames
    )
    reasons = {item.reason for item in coverage}
    if SemanticCoverageReason.DOMAIN_OOD in reasons:
        return RouteDecision(CompilationRoute.ABSTAIN, issue_code="DOMAIN_OOD")
    if SemanticCoverageReason.UNSUPPORTED_OPERATION in reasons:
        return RouteDecision(
            CompilationRoute.ABSTAIN,
            issue_code="UNSUPPORTED_OPERATION",
        )
    if any(item.state is not SemanticCoverageState.COVERED for item in coverage):
        return RouteDecision(CompilationRoute.EXPLORE)
    if resolution.resolution_status is not ResolutionStatus.RESOLVED:
        return RouteDecision(CompilationRoute.ABSTAIN, issue_code="SEMANTIC_UNMAPPED")

    archetype = _match_archetype(resolution, registry)
    if archetype is not None:
        return RouteDecision(CompilationRoute.FAST, archetype=archetype)
    return RouteDecision(CompilationRoute.COMPOSE)


def _match_archetype(
    resolution: ValidatedIntentResolutionV2,
    registry: PlanningRegistry,
) -> ArchetypeDefinition | None:
    actions = tuple(
        frame.action_choice.selected_ids[0] for frame in resolution.canonical_frames
    )
    families = {
        family
        for frame in resolution.canonical_frames
        for family in frame.product_family_choice.selected_ids
    }
    tags = {tag.value for tag in resolution.final_tags}
    slot_kinds = {
        assignment.slot_kind.value
        for frame in resolution.canonical_frames
        for assignment in frame.slot_assignments
    }
    has_context = bool(resolution.context_links)
    for archetype in registry.archetypes_by_id.values():
        if archetype.action_ids != actions:
            continue
        if not archetype.min_family_count <= len(families) <= archetype.max_family_count:
            continue
        if archetype.context_required != has_context:
            continue
        if not set(archetype.required_tags) <= tags:
            continue
        if set(archetype.forbidden_tags) & tags:
            continue
        if not set(archetype.required_slots) <= slot_kinds:
            continue
        return archetype
    return None
