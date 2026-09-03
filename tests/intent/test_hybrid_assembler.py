from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import (
    NamedEntityMention,
    RequestContext,
    Segment,
)
from financial_agent.intent.axis_locks import ExactSemanticLock
from financial_agent.intent.candidates import (
    EntityCandidate,
    Mention,
    generate_semantic_candidates,
)
from financial_agent.intent.catalog import load_hybrid_catalog
from financial_agent.intent.errors import ResolverContractError
from financial_agent.intent.hybrid_assembler import assemble_hybrid_proposal
from financial_agent.intent.hybrid_proposal import (
    FrameSemanticCoverageV3,
    IntentResolutionProposalV3,
    ProposedIntentFrameV3,
    ProposedSemanticLinkV3,
)
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.mention_spans import generate_mention_spans
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.proposal import ProposedAxisChoice, ProposedEntityHint
from financial_agent.intent.types import (
    ChoiceState,
    EntitySemanticRole,
    SemanticCoverageReason,
    SemanticCoverageState,
    SourceRole,
)
from financial_agent.intent.view import (
    ActiveDatasetPin,
    build_hybrid_manifest,
    build_resolver_view_v3,
)

from .view_fixtures import hybrid_manifest_versions


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _inputs(
    question: str = "비용 부담이 작은 ETF",
    *,
    exact_semantic_id: str | None = None,
):
    created_at = datetime(2026, 9, 3, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("q-hybrid-assembly", question, "dataset-v1", "1.0"),
        run_id="run-hybrid-assembly",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q-hybrid-assembly",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    catalog = load_hybrid_catalog(PROJECT_ROOT)
    normalized = normalize_request(context)
    literals = extract_literals(normalized)
    candidates = generate_semantic_candidates(normalized, catalog)
    mention_spans = generate_mention_spans(
        normalized,
        tuple(group.mention for group in candidates.by_mention),
        literals,
        (),
        normalized.reference_candidates,
    )
    mention = next(item for item in mention_spans.items if item.text == "비용 부담")
    locks = (
        (
            ExactSemanticLock(
                lock_id="lock-field-cost",
                role="field",
                canonical_id=exact_semantic_id,
                evidence_span_ids=(mention.mention_id,),
                source="direct_alias",
            ),
        )
        if exact_semantic_id is not None
        else ()
    )
    view = build_resolver_view_v3(
        context=context,
        normalized=normalized,
        literals=literals,
        semantic_candidates=candidates,
        entity_candidates={},
        manifest=build_hybrid_manifest(catalog, hybrid_manifest_versions()),
        active_dataset_pin=ActiveDatasetPin(
            dataset_version="dataset-v1", manifest_hash="d" * 64
        ),
        catalog=catalog,
        mention_spans=mention_spans,
        exact_semantic_locks=locks,
    )
    return context, normalized, view, catalog, mention.mention_id


def _choice(axis_id: str) -> ProposedAxisChoice:
    return ProposedAxisChoice(
        state=ChoiceState.SELECTED,
        selected_ids=(axis_id,),
        evidence_ids=(),
        reason_code="explicit",
    )


def _proposal(
    mention_id: str,
    semantic_id: str | None = "fee_rate",
) -> IntentResolutionProposalV3:
    links = (
        (
            ProposedSemanticLinkV3(
                mention_id=mention_id,
                semantic_ids=(semantic_id,),
                state="selected",
                reason_code="explicit",
            ),
        )
        if semantic_id is not None
        else ()
    )
    return IntentResolutionProposalV3(
        proposal_schema_version="3.0",
        frames=(
            ProposedIntentFrameV3(
                segment_ids=("s1",),
                action_choice=_choice("rank"),
                product_family_choice=_choice("domestic_etf"),
                entity_type_ids=("FinancialProduct",),
                semantic_links=links,
                unmapped_mention_ids=(),
                semantic_coverage=FrameSemanticCoverageV3(
                    state=SemanticCoverageState.COVERED,
                    reason=SemanticCoverageReason.NONE,
                ),
                entity_hints=(),
                produced_result_hints=(SourceRole.CANDIDATES,),
            ),
        ),
        references=(),
        context_links=(),
        slot_mutations=(),
        semantic_flag_hints=(),
        frame_limit_exceeded=False,
    )


def test_assembler_accepts_registered_unhinted_semantic_link() -> None:
    """Catches advisory hints accidentally becoming a semantic allowlist."""
    _, normalized, view, catalog, mention_id = _inputs()
    view = view.model_copy(update={"semantic_candidates": ()})

    draft = assemble_hybrid_proposal(
        _proposal(mention_id), normalized, view, catalog
    )

    assert draft.semantic_links[0].semantic_ids == ("fee_rate",)
    assert draft.semantic_links[0].mention_id == mention_id


@pytest.mark.parametrize(
    ("mention_id", "semantic_id"),
    (("unknown-mention", "fee_rate"), (None, "unknown_semantic")),
)
def test_assembler_rejects_unknown_link_ids(
    mention_id: str | None, semantic_id: str
) -> None:
    """Catches model-authored mention or semantic IDs crossing the trust boundary."""
    _, normalized, view, catalog, offered_mention_id = _inputs()

    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        assemble_hybrid_proposal(
            _proposal(mention_id or offered_mention_id, semantic_id),
            normalized,
            view,
            catalog,
        )


def test_assembler_rejects_exact_lock_contradiction() -> None:
    """Catches a selected model meaning replacing a deterministic exact lock."""
    _, normalized, view, catalog, mention_id = _inputs(exact_semantic_id="fee_rate")

    with pytest.raises(ResolverContractError, match="MODEL_EXACT_LOCK_CONFLICT"):
        assemble_hybrid_proposal(
            _proposal(mention_id, "aum"), normalized, view, catalog
        )


def test_assembler_restores_omitted_exact_lock() -> None:
    """Catches omission of a deterministic field lock from canonical provenance."""
    _, normalized, view, catalog, mention_id = _inputs(exact_semantic_id="fee_rate")

    draft = assemble_hybrid_proposal(
        _proposal(mention_id, None), normalized, view, catalog
    )

    assert [(link.mention_id, link.semantic_ids) for link in draft.semantic_links] == [
        (mention_id, ("fee_rate",))
    ]


def test_assembler_rejects_family_incompatible_concept() -> None:
    """Catches a registered bond-only meaning becoming an ETF semantic link."""
    _, normalized, view, catalog, mention_id = _inputs()

    with pytest.raises(ResolverContractError, match="MODEL_INAPPLICABLE_CONCEPT"):
        assemble_hybrid_proposal(
            _proposal(mention_id, "credit_grade"), normalized, view, catalog
        )


def test_assembler_rejects_relation_object_endpoint_reversal() -> None:
    """Catches a relation object typed as the relation's subject endpoint."""
    _, normalized, view, catalog, mention_id = _inputs()
    view = view.model_copy(update={"entity_output_enabled": True})
    proposal = _proposal(mention_id, "managedBy")
    hint = ProposedEntityHint(
        semantic_role=EntitySemanticRole.RELATION_OBJECT,
        relation_id=("managedBy",),
        expected_entity_type_ids=("ETF",),
        mention_id=(),
        candidate_entity_ids=(),
        selected_candidate_ids=(),
    )
    frame = proposal.frames[0].model_copy(update={"entity_hints": (hint,)})

    with pytest.raises(ResolverContractError, match="MODEL_INVALID_RELATION"):
        assemble_hybrid_proposal(
            proposal.model_copy(update={"frames": (frame,)}),
            normalized,
            view,
            catalog,
        )


def test_assembler_rejects_linked_and_unmapped_overlap_after_model_copy() -> None:
    """Catches unchecked model-copy payloads bypassing proposal shape validation."""
    _, normalized, view, catalog, mention_id = _inputs()
    proposal = _proposal(mention_id)
    frame = proposal.frames[0].model_copy(
        update={"unmapped_mention_ids": (mention_id,)}
    )

    with pytest.raises(ResolverContractError, match="MODEL_INVALID_SEMANTIC_COVERAGE"):
        assemble_hybrid_proposal(
            proposal.model_copy(update={"frames": (frame,)}),
            normalized,
            view,
            catalog,
        )


def test_assembler_rejects_covered_frame_with_unmapped_evidence() -> None:
    """Catches covered status hiding an explicitly unmapped source mention."""
    _, normalized, view, catalog, mention_id = _inputs()
    proposal = _proposal(mention_id)
    frame = proposal.frames[0].model_copy(
        update={"semantic_links": (), "unmapped_mention_ids": (mention_id,)}
    )

    with pytest.raises(ResolverContractError, match="MODEL_INVALID_SEMANTIC_COVERAGE"):
        assemble_hybrid_proposal(
            proposal.model_copy(update={"frames": (frame,)}),
            normalized,
            view,
            catalog,
        )


def test_assembler_rejects_entity_output_when_disabled() -> None:
    """Catches a simple question smuggling model entity output into V3."""
    _, normalized, view, catalog, mention_id = _inputs()
    proposal = _proposal(mention_id)
    hint = ProposedEntityHint(
        semantic_role=EntitySemanticRole.FRAME_SUBJECT,
        relation_id=(),
        expected_entity_type_ids=("FinancialProduct",),
        mention_id=(),
        candidate_entity_ids=(),
        selected_candidate_ids=(),
    )
    frame = proposal.frames[0].model_copy(update={"entity_hints": (hint,)})

    with pytest.raises(ResolverContractError, match="MODEL_OUTPUT_DISABLED"):
        assemble_hybrid_proposal(
            proposal.model_copy(update={"frames": (frame,)}),
            normalized,
            view,
            catalog,
        )


def test_assembler_rejects_entity_mention_owned_by_another_frame_segment() -> None:
    """Catches a valid entity mention crossing from its source clause into another frame."""
    question = "ETF를 찾아줘 KODEX 200을 비교해줘"
    created_at = datetime(2026, 9, 3, tzinfo=timezone.utc)
    entity_mention_id = "mention-s2-0-9"
    context = RequestContext(
        request_key=build_request_key(
            "q-hybrid-entity-ownership", question, "dataset-v1", "1.0"
        ),
        run_id="run-hybrid-entity-ownership",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q-hybrid-entity-ownership",
        question=question,
        segments=(
            Segment(segment_id="s1", ordinal=0, text="ETF를 찾아줘"),
            Segment(segment_id="s2", ordinal=1, text="KODEX 200을 비교해줘"),
        ),
        named_entities=(
            NamedEntityMention(
                mention_id=entity_mention_id,
                segment_id="s2",
                text="KODEX 200",
                expected_entity_types=("ETF",),
            ),
        ),
        deadline_at=created_at + timedelta(seconds=10),
    )
    catalog = load_hybrid_catalog(PROJECT_ROOT)
    normalized = normalize_request(context)
    literals = extract_literals(normalized)
    semantic_candidates = generate_semantic_candidates(normalized, catalog)
    entity_mention = Mention(
        mention_id=entity_mention_id,
        segment_id="s2",
        text="KODEX 200",
        normalized_text="KODEX 200",
        start_char=0,
        end_char=9,
    )
    mention_spans = generate_mention_spans(
        normalized,
        tuple(group.mention for group in semantic_candidates.by_mention),
        literals,
        (entity_mention,),
        normalized.reference_candidates,
    )
    view = build_resolver_view_v3(
        context=context,
        normalized=normalized,
        literals=literals,
        semantic_candidates=semantic_candidates,
        entity_candidates={
            entity_mention_id: (
                EntityCandidate(
                    entity_id="entity-kodex-200",
                    canonical_name="KODEX 200",
                    ontology_type_ids=("DomesticETF", "ETF", "FinancialProduct"),
                    product_family="domestic_etf",
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="entity-kodex-200",
                ),
            )
        },
        manifest=build_hybrid_manifest(catalog, hybrid_manifest_versions()),
        active_dataset_pin=ActiveDatasetPin(
            dataset_version="dataset-v1", manifest_hash="d" * 64
        ),
        catalog=catalog,
        mention_spans=mention_spans,
    )
    foreign_hint = ProposedEntityHint(
        semantic_role=EntitySemanticRole.FRAME_SUBJECT,
        relation_id=(),
        expected_entity_type_ids=("FinancialProduct",),
        mention_id=(entity_mention_id,),
        candidate_entity_ids=("entity-kodex-200",),
        selected_candidate_ids=("entity-kodex-200",),
    )
    frames = (
        ProposedIntentFrameV3(
            segment_ids=("s1",),
            action_choice=_choice("lookup"),
            product_family_choice=_choice("domestic_etf"),
            entity_type_ids=("FinancialProduct",),
            semantic_links=(),
            unmapped_mention_ids=(),
            semantic_coverage=FrameSemanticCoverageV3(
                state=SemanticCoverageState.COVERED,
                reason=SemanticCoverageReason.NONE,
            ),
            entity_hints=(foreign_hint,),
            produced_result_hints=(SourceRole.CANDIDATES,),
        ),
        ProposedIntentFrameV3(
            segment_ids=("s2",),
            action_choice=_choice("compare"),
            product_family_choice=_choice("domestic_etf"),
            entity_type_ids=("FinancialProduct",),
            semantic_links=(),
            unmapped_mention_ids=(),
            semantic_coverage=FrameSemanticCoverageV3(
                state=SemanticCoverageState.COVERED,
                reason=SemanticCoverageReason.NONE,
            ),
            entity_hints=(),
            produced_result_hints=(SourceRole.CANDIDATES,),
        ),
    )
    proposal = IntentResolutionProposalV3(
        proposal_schema_version="3.0",
        frames=frames,
        references=(),
        context_links=(),
        slot_mutations=(),
        semantic_flag_hints=(),
        frame_limit_exceeded=False,
    )

    with pytest.raises(ResolverContractError, match="MODEL_UNKNOWN_ID"):
        assemble_hybrid_proposal(proposal, normalized, view, catalog)
