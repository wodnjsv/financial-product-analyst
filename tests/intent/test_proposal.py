import json

import pytest
from pydantic import ValidationError

from financial_agent.intent.proposal import (
    IntentResolutionProposalV2,
    ProposedEntityHint,
    ProposedSlotAssignment,
)


def valid_proposal_payload() -> dict[str, object]:
    return {
        "proposal_schema_version": "2.0",
        "frames": [
            {
                "segment_ids": ["s1"],
                "action_choice": {
                    "state": "selected",
                    "selected_ids": ["lookup"],
                    "evidence_ids": ["e1"],
                    "reason_code": "explicit",
                },
                "product_family_choice": {
                    "state": "selected",
                    "selected_ids": ["domestic_etf"],
                    "evidence_ids": ["e1"],
                    "reason_code": "explicit",
                },
                "entity_type_ids": [],
                "semantic_coverage": {
                    "state": "covered",
                    "reason": "none",
                    "evidence_ids": [],
                },
                "slot_assignments": [],
                "entity_hints": [],
                "produced_result_hints": [],
            }
        ],
        "references": [],
        "context_links": [],
        "slot_mutations": [],
        "semantic_flag_hints": [],
        "frame_limit_exceeded": False,
    }


def test_proposal_schema_has_no_model_owned_artifact_ids_or_offsets() -> None:
    schema = IntentResolutionProposalV2.model_json_schema()
    rendered = json.dumps(schema, sort_keys=True)

    for forbidden in (
        "frame_id",
        "slot_assignment_id",
        "entity_hint_id",
        "context_link_id",
        "slot_mutation_id",
        "start_char",
        "end_char",
        "span_id",
    ):
        assert forbidden not in rendered


def test_proposal_accepts_server_selected_ids_and_positional_frames() -> None:
    proposal = IntentResolutionProposalV2.model_validate_json(
        json.dumps(valid_proposal_payload())
    )

    assert proposal.proposal_schema_version == "2.0"
    assert proposal.frames[0].segment_ids == ("s1",)


def test_proposal_preserves_explicit_entity_types_and_selected_candidates() -> None:
    payload = valid_proposal_payload()
    payload["frames"][0]["entity_type_ids"] = ["ETF"]
    payload["frames"][0]["entity_hints"] = [
        {
            "semantic_role": "frame_subject",
            "relation_id": [],
            "expected_entity_type_ids": ["ETF"],
            "mention_id": ["mention-etf"],
            "candidate_entity_ids": ["entity-etf"],
            "selected_candidate_ids": ["entity-etf"],
        }
    ]

    proposal = IntentResolutionProposalV2.model_validate_json(json.dumps(payload))

    assert proposal.frames[0].entity_type_ids == ("ETF",)
    assert proposal.frames[0].entity_hints[0].selected_candidate_ids == ("entity-etf",)


def test_proposal_rejects_model_authored_entity_slot_assignments() -> None:
    """Catches a ProposalV2 entity selection bypassing its role-aware hint."""
    payload = valid_proposal_payload()
    payload["frames"][0]["slot_assignments"] = [
        {
            "slot_kind": "entity",
            "value_ids": ["entity-etf"],
            "evidence_ids": ["e1"],
            "reason_code": "explicit",
        }
    ]

    with pytest.raises(ValidationError):
        IntentResolutionProposalV2.model_validate_json(json.dumps(payload))


def test_proposal_slot_schema_excludes_entity_kind() -> None:
    schema = ProposedSlotAssignment.model_json_schema()
    slot_kind = schema["properties"]["slot_kind"]

    assert "entity" not in json.dumps(slot_kind, sort_keys=True)


def test_relation_object_requires_one_relation_and_expected_type() -> None:
    with pytest.raises(ValidationError):
        ProposedEntityHint(
            semantic_role="relation_object",
            relation_id=(),
            expected_entity_type_ids=("AssetManager",),
            mention_id=("mention-manager",),
            candidate_entity_ids=("manager-1",),
            selected_candidate_ids=("manager-1",),
        )


def test_frame_subject_rejects_relation_id() -> None:
    with pytest.raises(ValidationError):
        ProposedEntityHint(
            semantic_role="frame_subject",
            relation_id=("managedBy",),
            expected_entity_type_ids=("ETF",),
            mention_id=("mention-etf",),
            candidate_entity_ids=("etf-1",),
            selected_candidate_ids=("etf-1",),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.update({"frames": []}),
        lambda payload: payload["frames"][0].update({"segment_ids": []}),
    ),
)
def test_proposal_rejects_empty_resolution_or_frame_segments(mutation) -> None:
    payload = valid_proposal_payload()
    mutation(payload)

    with pytest.raises(ValidationError):
        IntentResolutionProposalV2.model_validate_json(json.dumps(payload))


def test_proposal_rejects_two_selected_actions() -> None:
    payload = valid_proposal_payload()
    payload["frames"][0]["action_choice"]["selected_ids"] = ["lookup", "compare"]

    with pytest.raises(ValidationError):
        IntentResolutionProposalV2.model_validate_json(json.dumps(payload))


def test_proposal_allows_no_action_only_for_an_uncovered_or_ambiguous_frame() -> None:
    payload = valid_proposal_payload()
    payload["frames"][0]["action_choice"] = {
        "state": "unmapped",
        "selected_ids": [],
        "evidence_ids": ["e1"],
        "reason_code": "unmapped",
    }
    payload["frames"][0]["semantic_coverage"] = {
        "state": "unmapped",
        "reason": "unsupported_operation",
        "evidence_ids": ["e1"],
    }

    proposal = IntentResolutionProposalV2.model_validate_json(json.dumps(payload))

    assert proposal.frames[0].action_choice.selected_ids == ()


def test_covered_frame_rejects_ood_reason_and_evidence() -> None:
    payload = valid_proposal_payload()
    payload["frames"][0]["semantic_coverage"] = {
        "state": "covered",
        "reason": "lexical_ood",
        "evidence_ids": ["e1"],
    }

    with pytest.raises(ValidationError):
        IntentResolutionProposalV2.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "coverage",
    [
        {"state": "partial", "reason": "none", "evidence_ids": ["e1"]},
        {"state": "unmapped", "reason": "domain_ood", "evidence_ids": []},
    ],
)
def test_uncovered_frames_require_an_ood_reason_and_evidence(
    coverage: dict[str, object],
) -> None:
    payload = valid_proposal_payload()
    payload["frames"][0]["semantic_coverage"] = coverage

    with pytest.raises(ValidationError):
        IntentResolutionProposalV2.model_validate_json(json.dumps(payload))
