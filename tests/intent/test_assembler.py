import json
from datetime import datetime, timezone

import pytest

from financial_agent.contracts.canonical import build_request_key, canonical_json_bytes
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.assembler import assemble_proposal
from financial_agent.intent.evidence import EvidenceCandidate, EvidenceSourceKind
from financial_agent.intent.errors import (
    MODEL_INVALID_FRAME_REFERENCE,
    MODEL_UNKNOWN_EVIDENCE_ID,
    ResolverContractError,
)
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.proposal import IntentResolutionProposalV2
from financial_agent.intent.resolution import ContractFileHash, ResolverBuildManifest
from financial_agent.intent.view import (
    ActiveDatasetPin,
    ResolverView,
    ResolverViewEntityCandidate,
    ResolverViewEntityCandidateGroup,
    ResolverViewLiteralCandidate,
    ResolverViewReferenceCandidate,
)

from .view_fixtures import complete_axis_definitions


def normalized():
    created_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return normalize_request(
        RequestContext(
            request_key=build_request_key(
                "q-1", "ETF를 찾아서 그 상품을 비교해줘", "dataset-v1", "1.0"
            ),
            run_id="run-1",
            dataset_version="dataset-v1",
            producer="test",
            created_at=created_at,
            question_id="q-1",
            question="ETF를 찾아서 그 상품을 비교해줘",
            segments=(Segment(segment_id="s1", ordinal=0, text="ETF를 찾아서 그 상품을 비교해줘"),),
            deadline_at=created_at.replace(second=10),
        )
    )


def view() -> ResolverView:
    return ResolverView(
        build_manifest=ResolverBuildManifest(
            catalog_version="catalog-v1",
            catalog_hash="b" * 64,
            ontology_hashes=(
                ContractFileHash(relative_path="ontology.ttl", sha256="c" * 64),
            ),
            overlay_version="overlay-v1",
            overlay_hash="d" * 64,
            normalizer_version="normalizer-v1",
            candidate_policy_version="policy-v1",
            resolver_schema_version="1.0",
            prompt_version="prompt-v1",
            adapter_version="adapter-v1",
        ),
        active_dataset_pin=ActiveDatasetPin(
            dataset_version="dataset-v1", manifest_hash="e" * 64
        ),
        product_family_ids=("domestic_etf",),
        action_ids=("lookup", "compare"),
        semantic_candidates=(),
        concept_definitions=(),
        relation_definitions=(),
        literal_candidates=(
            ResolverViewLiteralCandidate(
                literal_id="literal-1",
                segment_id="s1",
                kind="result_limit",
                original_text="1",
                start_char=0,
                end_char=1,
                canonical_value="1",
            ),
        ),
        entity_candidates=(
            ResolverViewEntityCandidateGroup(
                mention_id="mention-1",
                items=(
                    ResolverViewEntityCandidate(
                        entity_id="entity-1",
                        canonical_name="ETF",
                        ontology_type_ids=("ETF",),
                        product_family="domestic_etf",
                        match_kind="exact_name",
                        score=1_000_000,
                    ),
                ),
            ),
        ),
        axis_definitions=complete_axis_definitions(),
        evidence_candidates=(
            EvidenceCandidate(
                evidence_id="evidence-1",
                segment_id="s1",
                start_char=0,
                end_char=3,
                text="ETF",
                source_kinds=(EvidenceSourceKind.SURFACE,),
                offered_semantic_ids=(),
            ),
            EvidenceCandidate(
                evidence_id="evidence-2",
                segment_id="s1",
                start_char=9,
                end_char=12,
                text="그 상품",
                source_kinds=(EvidenceSourceKind.REFERENCE,),
                offered_semantic_ids=(),
            ),
        ),
        reference_candidates=(
            ResolverViewReferenceCandidate(
                reference_id="ref-s1-9-12",
                segment_id="s1",
                text="그 상품",
                start_char=9,
                end_char=12,
            ),
        ),
    )


def proposal() -> IntentResolutionProposalV2:
    return IntentResolutionProposalV2.model_validate_json(
        json.dumps(
            {
            "proposal_schema_version": "2.0",
            "frames": [
                {
                    "segment_ids": ["s1"],
                    "action_choice": {"state": "selected", "selected_ids": ["lookup"], "evidence_ids": ["evidence-1"], "reason_code": "explicit"},
                    "product_family_choice": {"state": "selected", "selected_ids": ["domestic_etf"], "evidence_ids": ["evidence-1"], "reason_code": "explicit"},
                    "semantic_coverage": {"state": "covered", "reason": "none", "evidence_ids": []},
                    "slot_assignments": [{"slot_kind": "result_limit", "value_ids": ["literal-1"], "evidence_ids": ["evidence-1"], "reason_code": "explicit"}],
                    "entity_hints": [{"mention_id": ["mention-1"], "candidate_entity_ids": ["entity-1"]}],
                    "produced_result_hints": ["candidates"],
                },
                {
                    "segment_ids": ["s1"],
                    "action_choice": {"state": "selected", "selected_ids": ["compare"], "evidence_ids": ["evidence-2"], "reason_code": "explicit"},
                    "product_family_choice": {"state": "selected", "selected_ids": ["domestic_etf"], "evidence_ids": ["evidence-2"], "reason_code": "explicit"},
                    "semantic_coverage": {"state": "covered", "reason": "none", "evidence_ids": []},
                    "slot_assignments": [],
                    "entity_hints": [],
                    "produced_result_hints": [],
                },
            ],
            "references": [
                {
                    "reference_id": "ref-s1-9-12",
                    "producer_frame_ordinals": [0],
                    "surface_presence": "explicit",
                    "reference_form": "demonstrative",
                    "grammatical_number": ["singular"],
                    "expected_target_kind": ["entity"],
                    "expected_cardinality": ["one"],
                    "status": "resolved",
                    "reason_code": "explicit",
                }
            ],
            "context_links": [
                {
                    "reference_id": "ref-s1-9-12",
                    "link_type": "consume_single_result",
                    "source_role": "candidates",
                    "selector": ["first"],
                    "selector_literal_candidate_id": [],
                    "producer_frame_ordinal": 0,
                    "consumer_frame_ordinal": 1,
                    "target_slot_kind": [],
                }
            ],
            "slot_mutations": [
                {
                    "consumer_frame_ordinal": 1,
                    "slot_kind": "metric",
                    "mutation_kind": "carryover",
                    "source_frame_ordinal": [0],
                    "evidence_ids": ["evidence-2"],
                    "reason_code": "implicit",
                }
            ],
            "semantic_flag_hints": [],
            "frame_limit_exceeded": False,
            }
        )
    )


def unknown_evidence(value: IntentResolutionProposalV2) -> IntentResolutionProposalV2:
    frame = value.frames[0]
    return value.model_copy(
        update={
            "frames": (
                frame.model_copy(
                    update={
                        "action_choice": frame.action_choice.model_copy(
                            update={"evidence_ids": ("unknown-evidence",)}
                        )
                    }
                ),
                *value.frames[1:],
            )
        }
    )


def forward_link(value: IntentResolutionProposalV2) -> IntentResolutionProposalV2:
    link = value.context_links[0]
    return value.model_copy(
        update={
            "context_links": (
                link.model_copy(
                    update={"producer_frame_ordinal": 1, "consumer_frame_ordinal": 0}
                ),
            )
        }
    )


def bad_ordinal(value: IntentResolutionProposalV2) -> IntentResolutionProposalV2:
    reference = value.references[0]
    return value.model_copy(
        update={
            "references": (
                reference.model_copy(update={"producer_frame_ordinals": (2,)}),
            )
        }
    )


def test_assembly_is_byte_stable_and_server_assigns_ids() -> None:
    first = assemble_proposal(proposal(), normalized(), view())
    second = assemble_proposal(proposal(), normalized(), view())

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first.intent_frames[0].frame_id == "frame-0000"
    assert (
        first.intent_frames[0].slot_assignments[0].slot_assignment_id
        == "slot-0000-0000"
    )
    assert first.intent_frames[0].semantic_coverage == (
        proposal().frames[0].semantic_coverage,
    )
    assert first.evidence_spans[0].span_id == "evidence-1"
    assert first.evidence_spans[0].text == "ETF"
    assert first.context_link_hints[0].context_link_id == "link-0000"
    assert first.slot_mutations[0].slot_mutation_id == "mutation-0000"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (unknown_evidence, MODEL_UNKNOWN_EVIDENCE_ID),
        (forward_link, MODEL_INVALID_FRAME_REFERENCE),
        (bad_ordinal, MODEL_INVALID_FRAME_REFERENCE),
    ],
)
def test_assembler_rejects_unoffered_or_invalid_references(mutation, code: str) -> None:
    with pytest.raises(ResolverContractError, match=code):
        assemble_proposal(mutation(proposal()), normalized(), view())
