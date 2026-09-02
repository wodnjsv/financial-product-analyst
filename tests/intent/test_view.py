from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from financial_agent.contracts import canonical_json_bytes
from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import (
    EntityCandidate,
    Mention,
    SemanticCandidate,
    SemanticCandidateGroup,
    SemanticCandidateSet,
    generate_semantic_candidates,
)
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    AxisDefinition,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ActiveDatasetPin,
    ResolverInvariantError,
    ResolverView,
    ResolverViewEntityCandidateGroup,
    build_manifest,
    build_resolver_view,
    offered_entity_type_ids,
    validate_resolver_view_catalog,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def resolver_inputs() -> dict[str, object]:
    question = "AUM과 운용사, 3개를 알려줘"
    created_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("q-view", question, "dataset-v1", "1.0"),
        run_id="run-view",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q-view",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    snapshot = load_catalog(PROJECT_ROOT)
    normalized = normalize_request(context)
    return {
        "catalog": snapshot,
        "context": context,
        "normalized": normalized,
        "literals": extract_literals(normalized),
        "semantic_candidates": generate_semantic_candidates(normalized, snapshot),
        "entity_candidates": {
            "mention-s1-0-3": (
                EntityCandidate(
                    entity_id="entity-kodex",
                    canonical_name="KODEX 200",
                    ontology_type_ids=("DomesticETF", "ETF", "FinancialProduct"),
                    product_family="domestic_etf",
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="entity-kodex",
                ),
            )
        },
        "manifest": build_manifest(
            snapshot,
            {
                "normalizer_version": NORMALIZER_VERSION,
                "candidate_policy_version": CANDIDATE_POLICY_VERSION,
                "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
                "prompt_version": PROMPT_VERSION,
                "adapter_version": ADAPTER_VERSION,
            },
        ),
        "active_dataset_pin": ActiveDatasetPin(
            dataset_version="dataset-v1",
            manifest_hash="e" * 64,
        ),
    }


def test_view_is_byte_reproducible(resolver_inputs: dict[str, object]) -> None:
    """Catches nondeterministic ordering or process-derived view metadata."""
    first = build_resolver_view(**resolver_inputs)
    second = build_resolver_view(**resolver_inputs)

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_resolver_view_offers_complete_sorted_catalog_entity_types(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches a request-local candidate set narrowing the model's type vocabulary."""
    view = build_resolver_view(**resolver_inputs)
    catalog = resolver_inputs["catalog"]

    assert view.entity_type_ids == tuple(sorted(catalog.entity_type_ids))
    assert len(view.entity_type_ids) == 20
    assert offered_entity_type_ids(view) == view.entity_type_ids


def test_resolver_view_rejects_unsorted_or_duplicate_entity_type_registry(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches direct callers bypassing the bounded catalog registry invariant."""
    view = build_resolver_view(**resolver_inputs)

    with pytest.raises(ValidationError, match="entity type IDs must be unique and sorted"):
        ResolverView.model_validate(
            view.model_dump()
            | {"entity_type_ids": ("ETF", "AssetManager", "ETF")}
        )


@pytest.mark.parametrize(
    "entity_type_ids",
    (
        lambda view: view.entity_type_ids[1:],
        lambda view: tuple(sorted((*view.entity_type_ids, "DomesticETF"))),
    ),
)
def test_catalog_trust_boundary_rejects_incomplete_or_extra_entity_type_registry(
    resolver_inputs: dict[str, object], entity_type_ids
) -> None:
    """Catches restored views that differ from the loaded catalog projection."""
    view = build_resolver_view(**resolver_inputs)
    restored = view.model_copy(update={"entity_type_ids": entity_type_ids(view)})

    with pytest.raises(ResolverInvariantError, match="CATALOG_ENTITY_TYPE_MISMATCH"):
        validate_resolver_view_catalog(restored, resolver_inputs["catalog"])


def test_view_projects_sorted_axes_evidence_and_normalizer_references(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches a v2 view losing server-owned evidence or request-order references."""
    question = "그 상품들 위험등급과 3개를 알려줘"
    context = resolver_inputs["context"].model_copy(
        update={
            "question": question,
            "segments": (Segment(segment_id="s1", ordinal=0, text=question),),
        }
    )
    snapshot = resolver_inputs["catalog"]
    normalized = normalize_request(context)
    resolver_inputs.update(
        context=context,
        normalized=normalized,
        literals=extract_literals(normalized),
        semantic_candidates=generate_semantic_candidates(normalized, snapshot),
        entity_candidates={},
    )

    view = build_resolver_view(**resolver_inputs)

    assert [(item.axis_kind, item.axis_id) for item in view.axis_definitions] == sorted(
        (item.axis_kind, item.axis_id) for item in view.axis_definitions
    )
    risk_grade = next(
        item for item in view.evidence_candidates if item.text == "위험등급"
    )
    assert risk_grade.offered_semantic_ids == ("credit_grade", "product_risk_grade")
    assert [(item.reference_id, item.text) for item in view.reference_candidates] == [
        ("ref-s1-0-5", "그 상품들")
    ]


def test_view_rejects_incomplete_axis_projection(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches a model-facing view missing one registered runtime axis."""
    view = build_resolver_view(**resolver_inputs)

    with pytest.raises(ValidationError, match="axis definitions must exactly match"):
        _rebuild_view(
            view,
            view.entity_candidates,
            axis_definitions=view.axis_definitions[:-1],
        )


def test_view_rejects_dataset_manifest_mismatch(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches a request reaching the model with a different active dataset."""
    resolver_inputs["active_dataset_pin"] = ActiveDatasetPin(
        dataset_version="different-version",
        manifest_hash="f" * 64,
    )

    with pytest.raises(ResolverInvariantError, match="CATALOG_VERSION_MISMATCH"):
        build_resolver_view(**resolver_inputs)


@pytest.mark.parametrize(
    "field,wrong_value",
    [
        ("schema_version", "2.0"),
        ("normalizer_version", "different-normalizer"),
        ("candidate_policy_version", "different-policy"),
        ("resolver_schema_version", "1.0"),
        ("prompt_version", "different-prompt"),
        ("adapter_version", "different-adapter"),
    ],
)
def test_view_rejects_manifest_code_version_mismatch(
    resolver_inputs: dict[str, object], field: str, wrong_value: str
) -> None:
    """Catches a stale code-version manifest reaching a resolver view."""
    manifest = resolver_inputs["manifest"]
    resolver_inputs["manifest"] = manifest.model_copy(update={field: wrong_value})

    with pytest.raises(ResolverInvariantError, match="CATALOG_VERSION_MISMATCH"):
        build_resolver_view(**resolver_inputs)


def test_manifest_uses_the_complete_catalog_and_graph_contract(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches a manifest built from constants or a partial graph-contract hash set."""
    manifest = resolver_inputs["manifest"]
    snapshot = load_catalog(PROJECT_ROOT)

    assert manifest.catalog_hash == snapshot.catalog_hash
    assert manifest.overlay_hash == snapshot.overlay_hash
    assert tuple((item.relative_path, item.sha256) for item in manifest.ontology_hashes) == tuple(
        sorted(snapshot.ontology_hashes.items())
    )
    assert manifest.normalizer_version == NORMALIZER_VERSION
    assert manifest.candidate_policy_version == CANDIDATE_POLICY_VERSION
    assert manifest.resolver_schema_version == RESOLVER_SCHEMA_VERSION
    assert manifest.prompt_version == PROMPT_VERSION
    assert manifest.adapter_version == ADAPTER_VERSION


def test_view_preserves_relation_direction_and_excludes_untrusted_source_material(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches exposing full source artifacts or flattening a relation's endpoints."""
    view = build_resolver_view(**resolver_inputs)
    payload = canonical_json_bytes(view).decode("utf-8")

    relation = next(item for item in view.relation_definitions if item.relation_id == "managedBy")
    assert relation.allowed_product_families == (
        "domestic_bond",
        "domestic_etf",
        "overseas_etf",
        "public_fund",
    )
    assert relation.subject_ontology_types == ("FinancialProduct",)
    assert "AssetManager" not in relation.compatible_subject_ontology_types
    assert "ETF" in relation.compatible_subject_ontology_types
    assert relation.object_ontology_types == ("AssetManager",)
    assert "@prefix fp:" not in payload
    assert "sh:NodeShape" not in payload
    assert "catalog.alias" not in payload
    assert "ontology:predicate:" not in payload
    assert "yield_rate" not in payload


def test_view_retains_exact_entity_candidates_before_truncating_fuzzy_candidates(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches a fuzzy candidate displacing exact evidence at the per-mention limit."""
    resolver_inputs["entity_candidates"] = {
        "mention-s1-0-3": tuple(
            EntityCandidate(
                entity_id=f"entity-{index}",
                canonical_name=f"Entity {index}",
                ontology_type_ids=("DomesticETF", "ETF", "FinancialProduct"),
                product_family="domestic_etf",
                match_kind="exact_name" if index < 3 else "trigram",
                score=1_000_000 if index < 3 else 900_000 - index,
                source_id=f"source-{index}",
            )
            for index in range(7)
        )
    }

    view = build_resolver_view(**resolver_inputs)

    assert [item.entity_id for item in view.entity_candidates[0].items] == [
        "entity-0",
        "entity-1",
        "entity-2",
        "entity-3",
        "entity-4",
    ]


def _rebuild_view(
    view: ResolverView,
    entity_candidates: tuple[ResolverViewEntityCandidateGroup, ...],
    *,
    axis_definitions: tuple[AxisDefinition, ...] | None = None,
) -> ResolverView:
    return ResolverView(
        build_manifest=view.build_manifest,
        active_dataset_pin=view.active_dataset_pin,
        product_family_ids=view.product_family_ids,
        action_ids=view.action_ids,
        entity_type_ids=view.entity_type_ids,
        semantic_candidates=view.semantic_candidates,
        concept_definitions=view.concept_definitions,
        relation_definitions=view.relation_definitions,
        literal_candidates=view.literal_candidates,
        entity_candidates=entity_candidates,
        axis_definitions=(
            view.axis_definitions if axis_definitions is None else axis_definitions
        ),
        evidence_candidates=view.evidence_candidates,
        reference_candidates=view.reference_candidates,
    )


def _entity_candidate_groups(
    view: ResolverView,
    group_count: int,
    items_per_group: int,
) -> tuple[ResolverViewEntityCandidateGroup, ...]:
    template = view.entity_candidates[0].items[0]
    return tuple(
        ResolverViewEntityCandidateGroup(
            mention_id=f"entity-mention-{group_index}",
            items=tuple(
                template.model_copy(
                    update={"entity_id": f"entity-{group_index}-{item_index}"}
                )
                for item_index in range(items_per_group)
            ),
        )
        for group_index in range(group_count)
    )


def test_view_accepts_sixteen_and_rejects_seventeen_entity_groups(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches injected callers bypassing the entity-mention bound."""
    view = build_resolver_view(**resolver_inputs)

    accepted = _rebuild_view(view, _entity_candidate_groups(view, 16, 1))
    assert len(accepted.entity_candidates) == 16
    with pytest.raises(ValidationError, match="RESOLVER_VIEW_LIMIT_EXCEEDED"):
        _rebuild_view(view, _entity_candidate_groups(view, 17, 1))


def test_view_accepts_eighty_and_rejects_more_total_entity_candidates(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches oversized injected groups bypassing the total candidate bound."""
    view = build_resolver_view(**resolver_inputs)
    bounded = _entity_candidate_groups(view, 16, 5)
    accepted = _rebuild_view(view, bounded)
    assert sum(len(group.items) for group in accepted.entity_candidates) == 80

    template = view.entity_candidates[0].items[0]
    oversized_first = ResolverViewEntityCandidateGroup.model_construct(
        mention_id="entity-mention-0",
        items=tuple(
            template.model_copy(update={"entity_id": f"entity-0-{index}"})
            for index in range(6)
        ),
    )
    oversized = (oversized_first, *bounded[1:])
    with pytest.raises(ValidationError, match="RESOLVER_VIEW_LIMIT_EXCEEDED"):
        _rebuild_view(view, oversized)


def test_view_rejects_more_than_eighty_exact_semantic_candidates(
    resolver_inputs: dict[str, object],
) -> None:
    """Catches silently dropping exact semantic evidence to satisfy the global limit."""
    groups = tuple(
        SemanticCandidateGroup(
            mention=Mention(
                mention_id=f"mention-{index}",
                segment_id="s1",
                text="AUM",
                normalized_text="AUM",
                start_char=0,
                end_char=3,
            ),
            items=(
                SemanticCandidate(
                    mention_id=f"mention-{index}",
                    semantic_id="aum",
                    match_kind="direct_alias",
                    score=1_000_000,
                    source_id="overlay:AUM",
                ),
            ),
        )
        for index in range(81)
    )
    resolver_inputs["semantic_candidates"] = SemanticCandidateSet(
        candidate_policy_version="semantic-candidates-v1",
        by_mention=groups,
    )

    with pytest.raises(ResolverInvariantError, match="RESOLVER_VIEW_LIMIT_EXCEEDED"):
        build_resolver_view(**resolver_inputs)
