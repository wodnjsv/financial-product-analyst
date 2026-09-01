import json

import pytest
from pydantic import ValidationError

from financial_agent.intent.proposal import IntentResolutionProposalV2


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


def test_covered_frame_rejects_ood_reason_and_evidence() -> None:
    payload = valid_proposal_payload()
    payload["frames"][0]["semantic_coverage"] = {
        "state": "covered",
        "reason": "lexical_ood",
        "evidence_ids": ["e1"],
    }

    with pytest.raises(ValidationError):
        IntentResolutionProposalV2.model_validate(payload)


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
        IntentResolutionProposalV2.model_validate(payload)
