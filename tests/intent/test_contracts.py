import json

import pytest
from pydantic import ValidationError

from financial_agent.intent.draft import IntentResolutionDraft
from financial_agent.intent.resolution import (
    ContractFileHash,
    ResolverBuildManifest,
    ValidatedIntentResolution,
)


def span(span_id: str = "span-1") -> dict[str, object]:
    return {
        "span_id": span_id,
        "segment_id": "s1",
        "start_char": 0,
        "end_char": 2,
        "text": "비교",
    }


def choice(selected_id: str) -> dict[str, object]:
    return {
        "state": "selected",
        "selected_ids": [selected_id],
        "evidence_span_ids": ["span-1"],
        "reason_code": "explicit",
    }


def frame(frame_id: str, ordinal: int, action: str) -> dict[str, object]:
    return {
        "frame_id": frame_id,
        "ordinal": ordinal,
        "segment_ids": ["s1"],
        "evidence_span_ids": ["span-1"],
        "normalized_intent_argument": "ETF 비교",
        "action_choice": choice(action),
        "product_family_choice": choice("domestic_etf"),
        "entity_type_ids": [],
        "entity_hint_ids": [],
        "slot_assignments": [],
        "produced_result_hints": [],
    }


def valid_draft_payload() -> dict[str, object]:
    return {
        "evidence_spans": [span()],
        "intent_frames": [frame("f1", 0, "compare")],
        "entity_hints": [],
        "reference_hints": [],
        "context_link_hints": [],
        "slot_mutations": [],
        "semantic_flag_hints": [],
        "frame_limit_exceeded": False,
    }


def sha256(seed: str) -> str:
    return seed * 64


@pytest.mark.clova_integration
def test_resolver_dependency_is_importable() -> None:
    import httpx

    assert httpx.__version__


def test_draft_rejects_unknown_fields() -> None:
    payload = valid_draft_payload()
    payload["sql"] = "SELECT * FROM product"

    with pytest.raises(ValidationError):
        IntentResolutionDraft.model_validate_json(json.dumps(payload))


def test_one_surface_segment_can_produce_two_frames() -> None:
    payload = valid_draft_payload()
    payload["intent_frames"] = [
        frame("f1", 0, "compare"),
        frame("f2", 1, "rank"),
    ]

    draft = IntentResolutionDraft.model_validate_json(json.dumps(payload))

    assert [item.frame_id for item in draft.intent_frames] == ["f1", "f2"]
    assert {item.segment_ids for item in draft.intent_frames} == {("s1",)}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("intent_frames", [frame("f1", 0, "compare"), frame("f1", 1, "rank")]),
        ("intent_frames", [frame("f1", 0, "compare"), frame("f2", 0, "rank")]),
        (
            "intent_frames",
            [frame(f"f{index}", index, "lookup") for index in range(17)],
        ),
    ],
)
def test_draft_rejects_duplicate_frame_ids_duplicate_ordinals_and_too_many_frames(
    field: str,
    value: object,
) -> None:
    payload = valid_draft_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        IntentResolutionDraft.model_validate_json(json.dumps(payload))


def test_build_manifest_rejects_ontology_hashes_out_of_path_order() -> None:
    with pytest.raises(ValidationError):
        ResolverBuildManifest.model_validate_json(
            json.dumps(
                {
                    "catalog_version": "catalog-v1",
                    "catalog_hash": sha256("a"),
                    "ontology_hashes": [
                        {"relative_path": "z.ttl", "sha256": sha256("b")},
                        {"relative_path": "a.ttl", "sha256": sha256("c")},
                    ],
                    "overlay_version": "overlay-v1",
                    "overlay_hash": sha256("d"),
                    "normalizer_version": "normalizer-v1",
                    "candidate_policy_version": "policy-v1",
                    "resolver_schema_version": "1.0",
                    "prompt_version": "prompt-v1",
                    "adapter_version": "adapter-v1",
                }
            )
        )


def test_validated_resolution_preserves_runtime_provenance() -> None:
    validated = ValidatedIntentResolution.model_validate_json(
        json.dumps(
            {
                "request_key": sha256("a"),
                "run_id": "run-1",
                "dataset_version": "dataset-v1",
                "producer": "intent-resolver",
                "created_at": "2026-08-31T00:00:00Z",
                "resolution_id": "resolution-1",
                "draft_hash": sha256("b"),
                "canonical_frames": [],
                "context_links": [],
                "final_tags": [],
                "resolution_status": "resolved",
                "issues": [],
                "validation_events": [],
                "build_manifest": {
                    "catalog_version": "catalog-v1",
                    "catalog_hash": sha256("c"),
                    "ontology_hashes": [
                        {"relative_path": "ontology.ttl", "sha256": sha256("d")}
                    ],
                    "overlay_version": "overlay-v1",
                    "overlay_hash": sha256("e"),
                    "normalizer_version": "normalizer-v1",
                    "candidate_policy_version": "policy-v1",
                    "resolver_schema_version": "1.0",
                    "prompt_version": "prompt-v1",
                    "adapter_version": "adapter-v1",
                },
                "active_dataset_manifest_hash": sha256("f"),
                "repair_used": False,
                "invalid_attempt_hashes": [],
            }
        )
    )

    assert validated.resolution_id == "resolution-1"
    assert validated.build_manifest.schema_version == "1.0"
    assert isinstance(
        validated.build_manifest.ontology_hashes[0], ContractFileHash
    )
