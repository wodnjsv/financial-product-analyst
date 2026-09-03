from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from financial_agent.contracts import canonical_json_bytes
from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import NamedEntityMention, RequestContext, Segment
from financial_agent.intent.candidates import (
    EntityCandidate,
    Mention,
    SemanticCandidate,
    SemanticCandidateGroup,
    SemanticCandidateSet,
    generate_semantic_candidates,
)
from financial_agent.intent.axis_locks import build_exact_semantic_locks
from financial_agent.intent.catalog import load_catalog, load_hybrid_catalog
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.mention_spans import generate_mention_spans
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.view import (
    ADAPTER_VERSION,
    AxisDefinition,
    CANDIDATE_POLICY_VERSION,
    NORMALIZER_VERSION,
    PROMPT_VERSION,
    RESOLVER_SCHEMA_VERSION,
    ActiveDatasetPin,
    HYBRID_ADAPTER_VERSION,
    HYBRID_CANDIDATE_POLICY_VERSION,
    HYBRID_PROMPT_VERSION,
    HYBRID_RESOLVER_SCHEMA_VERSION,
    ResolverInvariantError,
    ResolverView,
    ResolverViewV3,
    ResolverViewEntityCandidateGroup,
    build_manifest,
    build_hybrid_manifest,
    build_resolver_view,
    build_resolver_view_v3,
    model_safe_resolver_view_v3_payload,
    offered_entity_type_ids,
    validate_resolver_view_catalog,
)

from .view_fixtures import hybrid_manifest_versions


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


@pytest.fixture
def v3_inputs():
    def build(
        *,
        question: str,
        named_entities=(),
    ) -> dict[str, object]:
        created_at = datetime(2026, 9, 3, tzinfo=timezone.utc)
        context = RequestContext(
            request_key=build_request_key("q-view-v3", question, "dataset-v1", "1.0"),
            run_id="run-view-v3",
            dataset_version="dataset-v1",
            producer="test",
            created_at=created_at,
            question_id="q-view-v3",
            question=question,
            segments=(Segment(segment_id="s1", ordinal=0, text=question),),
            named_entities=named_entities,
            deadline_at=created_at + timedelta(seconds=10),
        )
        catalog = load_hybrid_catalog(PROJECT_ROOT)
        normalized = normalize_request(context)
        literals = extract_literals(normalized)
        semantic_candidates = generate_semantic_candidates(normalized, catalog)
        return {
            "catalog": catalog,
            "context": context,
            "normalized": normalized,
            "literals": literals,
            "semantic_candidates": semantic_candidates,
            "entity_candidates": {},
            "manifest": build_hybrid_manifest(catalog, hybrid_manifest_versions()),
            "active_dataset_pin": ActiveDatasetPin(
                dataset_version="dataset-v1", manifest_hash="d" * 64
            ),
            "mention_spans": generate_mention_spans(
                normalized,
                tuple(group.mention for group in semantic_candidates.by_mention),
                literals,
                (),
                normalized.reference_candidates,
            ),
            "exact_semantic_locks": build_exact_semantic_locks(
                normalized,
                catalog,
                semantic_candidates=semantic_candidates,
                literals=literals,
            ),
        }

    return build


def test_v3_view_offers_full_catalog_when_no_alias_matches(v3_inputs) -> None:
    """Catches an absent lexical hint making a registered semantic unselectable."""
    view = build_resolver_view_v3(**v3_inputs(question="비용 부담이 작은 ETF"))

    assert not any(
        item.semantic_id == "fee_rate"
        for group in view.semantic_candidates
        for item in group.items
    )
    assert "fee_rate" in {
        item.semantic_id for item in view.compact_semantic_catalog.concepts
    }


def test_v3_non_entity_request_disables_entity_output(v3_inputs) -> None:
    """Catches enabling an entity branch without a source entity mention."""
    view = build_resolver_view_v3(**v3_inputs(question="ETF 순위를 알려줘"))

    assert view.entity_output_enabled is False


def test_v3_reference_output_requires_reference_evidence(v3_inputs) -> None:
    """Catches enabling context output where no reference was detected."""
    plain = build_resolver_view_v3(**v3_inputs(question="ETF 순위를 알려줘"))
    contextual = build_resolver_view_v3(**v3_inputs(question="그 상품들 순위를 알려줘"))

    assert plain.reference_output_enabled is False
    assert contextual.reference_output_enabled is True


@pytest.mark.parametrize("source_kind", ("entity", "reference"))
def test_v3_view_rejects_forged_output_source_kinds_without_request_evidence(
    v3_inputs, source_kind: str
) -> None:
    """Catches injected span tags enabling model branches without source evidence."""
    inputs = v3_inputs(question="ETF 순위를 알려줘")
    first_span = inputs["mention_spans"].items[0]
    inputs["mention_spans"] = inputs["mention_spans"].model_copy(
        update={
            "items": (
                first_span.model_copy(update={"source_kinds": (source_kind,)}),
                *inputs["mention_spans"].items[1:],
            )
        }
    )

    with pytest.raises(ResolverInvariantError, match="MENTION_SPAN_PROVENANCE_MISMATCH"):
        build_resolver_view_v3(**inputs)


def test_v3_view_rejects_missing_entity_span_for_request_entity_evidence(v3_inputs) -> None:
    """Catches silently disabling entity output when a request supplied entity evidence."""
    entity = NamedEntityMention(
        mention_id="entity-kodex",
        segment_id="s1",
        text="KODEX 200",
        expected_entity_types=("ETF",),
    )
    inputs = v3_inputs(question="KODEX 200을 알려줘", named_entities=(entity,))

    with pytest.raises(ResolverInvariantError, match="MENTION_SPAN_PROVENANCE_MISMATCH"):
        build_resolver_view_v3(**inputs)


def test_v3_view_rejects_entity_span_with_forged_normalized_text(v3_inputs) -> None:
    """Catches a matching range and text carrying untrusted normalized content."""
    entity = NamedEntityMention(
        mention_id="entity-kodex",
        segment_id="s1",
        text="KODEX 200",
        expected_entity_types=("ETF",),
    )
    inputs = v3_inputs(question="KODEX 200을 알려줘", named_entities=(entity,))
    entity_mention = Mention(
        mention_id="entity-kodex",
        segment_id="s1",
        text="KODEX 200",
        normalized_text="KODEX 200",
        start_char=0,
        end_char=9,
    )
    spans = generate_mention_spans(
        inputs["normalized"],
        (),
        inputs["literals"],
        (entity_mention,),
        inputs["normalized"].reference_candidates,
    )
    inputs["mention_spans"] = spans.model_copy(
        update={
            "items": tuple(
                item.model_copy(update={"normalized_text": "forged"})
                if "entity" in item.source_kinds
                else item
                for item in spans.items
            )
        }
    )

    with pytest.raises(ResolverInvariantError, match="MENTION_SPAN_PROVENANCE_MISMATCH"):
        build_resolver_view_v3(**inputs)


def test_v3_view_rejects_missing_reference_span_for_request_reference_evidence(
    v3_inputs,
) -> None:
    """Catches silently disabling context output when a reference was detected."""
    inputs = v3_inputs(question="그 상품들 순위를 알려줘")
    inputs["mention_spans"] = inputs["mention_spans"].model_copy(
        update={
            "items": tuple(
                item.model_copy(
                    update={
                        "source_kinds": tuple(
                            kind for kind in item.source_kinds if kind != "reference"
                        )
                    }
                )
                for item in inputs["mention_spans"].items
            )
        }
    )

    with pytest.raises(ResolverInvariantError, match="MENTION_SPAN_PROVENANCE_MISMATCH"):
        build_resolver_view_v3(**inputs)


def test_v3_view_projects_only_source_ranged_semantic_locks(v3_inputs) -> None:
    """Catches leaking lock sources or projecting a lock with no offered mention."""
    inputs = v3_inputs(question="공모펀드의 AUM을 알려줘")
    view = build_resolver_view_v3(**inputs)

    assert view.exact_lock_projections
    assert {
        projection.role for projection in view.exact_lock_projections
    } <= {"product_family", "field"}
    assert {
        projection.mention_id for projection in view.exact_lock_projections
    } <= {item.mention_id for item in view.mention_spans.items}
    assert all(
        set(projection.model_dump())
        == {"lock_id", "mention_id", "canonical_semantic_id", "role"}
        for projection in view.exact_lock_projections
    )
    payload = model_safe_resolver_view_v3_payload(view)
    assert "exact_semantic_locks" not in payload
    assert payload["exact_lock_projections"] == [
        projection.model_dump(mode="json") for projection in view.exact_lock_projections
    ]


def test_v3_view_rejects_exact_lock_projection_without_a_mention_span(v3_inputs) -> None:
    """Catches a model-facing lock whose supporting source range was removed."""
    inputs = v3_inputs(question="공모펀드의 AUM을 알려줘")
    inputs["mention_spans"] = inputs["mention_spans"].model_copy(update={"items": ()})

    with pytest.raises(ResolverInvariantError, match="EXACT_LOCK_MENTION_MISSING"):
        build_resolver_view_v3(**inputs)


def test_hybrid_manifest_rejects_v2_overlay_or_version_pins() -> None:
    """Catches a V3 resolver build being pinned to legacy catalog inputs."""
    with pytest.raises(ResolverInvariantError, match="CATALOG_VERSION_MISMATCH"):
        build_hybrid_manifest(load_catalog(PROJECT_ROOT), hybrid_manifest_versions())
    versions = hybrid_manifest_versions() | {"prompt_version": "intent-resolver-ko-v5-axis-only"}
    with pytest.raises(ResolverInvariantError, match="CATALOG_VERSION_MISMATCH"):
        build_hybrid_manifest(load_hybrid_catalog(PROJECT_ROOT), versions)


def test_hybrid_version_constants_match_the_shadow_v3_contract() -> None:
    """Catches a V3 manifest reaching a model with a mismatched proposal contract."""
    assert (
        HYBRID_RESOLVER_SCHEMA_VERSION,
        HYBRID_CANDIDATE_POLICY_VERSION,
        HYBRID_PROMPT_VERSION,
        HYBRID_ADAPTER_VERSION,
    ) == (
        "3.0",
        "intent-hints-v3",
        "intent-resolver-ko-v6-full-catalog",
        "clova-chat-v3-proposal-v3",
    )


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
