from enum import Enum

from pydantic import model_validator

from financial_agent.contracts.base import (
    ContractModel,
    Identifier,
    RuntimeArtifact,
    Sha256Hex,
)
from financial_agent.contracts.query import QueryPlan
from financial_agent.contracts.validation import require_unique_ids


class CompilationRoute(str, Enum):
    FAST = "fast"
    COMPOSE = "compose"
    EXPLORE = "explore"
    ABSTAIN = "abstain"


class CompilerManifest(ContractModel):
    registry_version: Identifier
    registry_hash: Sha256Hex
    compiler_version: Identifier


class LoweringRecord(ContractModel):
    source_id: Identifier
    target_kind: Identifier
    target_ids: tuple[Identifier, ...]


class CompilationIssue(ContractModel):
    code: Identifier
    related_ids: tuple[Identifier, ...] = ()


class QueryPlanCompilation(RuntimeArtifact):
    compilation_id: Identifier
    resolution_id: Identifier
    route: CompilationRoute
    query_plan: QueryPlan | None
    matched_archetype_id: Identifier | None
    primitive_ids: tuple[Identifier, ...]
    applied_default_ids: tuple[Identifier, ...]
    lowering_records: tuple[LoweringRecord, ...]
    blocking_issues: tuple[CompilationIssue, ...]
    resolver_view_hash: Sha256Hex
    compiler_manifest: CompilerManifest

    @model_validator(mode="after")
    def validate_compilation(self) -> "QueryPlanCompilation":
        if self.route is not CompilationRoute.ABSTAIN and self.query_plan is None:
            raise ValueError("executable route requires query plan")
        if self.route is CompilationRoute.ABSTAIN:
            if self.query_plan is not None:
                raise ValueError("abstain cannot carry query plan")
            if not self.blocking_issues:
                raise ValueError("abstain requires blocking issue")
            if self.primitive_ids or self.matched_archetype_id is not None:
                raise ValueError("abstain cannot select executable registry entries")
        elif self.blocking_issues:
            raise ValueError("executable route cannot carry blocking issues")
        if self.route is CompilationRoute.FAST and self.matched_archetype_id is None:
            raise ValueError("fast route requires matched archetype")
        if (
            self.route is not CompilationRoute.FAST
            and self.matched_archetype_id is not None
        ):
            raise ValueError("only fast route may select an archetype")
        if self.route is not CompilationRoute.ABSTAIN and not self.primitive_ids:
            raise ValueError("executable route requires primitives")
        require_unique_ids(self.primitive_ids, label="primitive IDs")
        require_unique_ids(self.applied_default_ids, label="default IDs")
        source_ids = tuple(item.source_id for item in self.lowering_records)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("lowering sources must be unique")
        if self.query_plan is not None and (
            self.query_plan.request_key != self.request_key
            or self.query_plan.run_id != self.run_id
            or self.query_plan.dataset_version != self.dataset_version
            or self.query_plan.cutoff_date != self.cutoff_date
        ):
            raise ValueError("query plan pins must match compilation")
        return self
