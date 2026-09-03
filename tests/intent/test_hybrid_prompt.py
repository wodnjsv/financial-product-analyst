from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import RequestContext, Segment
from financial_agent.intent.candidates import generate_semantic_candidates
from financial_agent.intent.catalog import load_hybrid_catalog
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.mention_spans import generate_mention_spans
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.view import (
    ActiveDatasetPin,
    build_hybrid_manifest,
    build_resolver_view_v3,
)

from financial_agent.intent.hybrid_prompt import (
    build_hybrid_prompt,
    build_hybrid_response_schema,
)

from .view_fixtures import hybrid_manifest_versions


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _view(question: str = "비용 부담이 작은 ETF를 알려줘"):
    created_at = datetime(2026, 9, 3, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key(
            "q-hybrid-prompt", question, "dataset-v1", "1.0"
        ),
        run_id="run-hybrid-prompt",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q-hybrid-prompt",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=10),
    )
    catalog = load_hybrid_catalog(PROJECT_ROOT)
    normalized = normalize_request(context)
    literals = extract_literals(normalized)
    semantic_candidates = generate_semantic_candidates(normalized, catalog)
    view = build_resolver_view_v3(
        context=context,
        normalized=normalized,
        literals=literals,
        semantic_candidates=semantic_candidates,
        entity_candidates={},
        manifest=build_hybrid_manifest(catalog, hybrid_manifest_versions()),
        active_dataset_pin=ActiveDatasetPin(
            dataset_version="dataset-v1", manifest_hash="d" * 64
        ),
        catalog=catalog,
        mention_spans=generate_mention_spans(
            normalized,
            tuple(group.mention for group in semantic_candidates.by_mention),
            literals,
            (),
            normalized.reference_candidates,
        ),
    )
    return context, view, catalog


def semantic_id_enum(schema: object) -> set[str]:
    if isinstance(schema, dict):
        values = set(schema.get("enum", ()))
        return values | set().union(
            *(semantic_id_enum(item) for item in schema.values())
        )
    if isinstance(schema, list):
        return set().union(*(semantic_id_enum(item) for item in schema))
    return set()


def test_simple_question_schema_forbids_entity_and_context_arrays() -> None:
    """Catches disabled entity or reference branches becoming model-selectable."""
    _, simple_v3_view, _ = _view()

    schema = build_hybrid_response_schema(simple_v3_view)
    frame = schema["properties"]["frames"]["items"]
    assert frame["properties"]["entity_hints"]["maxItems"] == 0
    assert schema["properties"]["references"]["maxItems"] == 0
    assert schema["properties"]["context_links"]["maxItems"] == 0
    assert schema["properties"]["slot_mutations"]["maxItems"] == 0


def test_semantic_link_enum_contains_unhinted_catalog_id() -> None:
    """Catches advisory candidate generation narrowing full catalog selection."""
    _, simple_v3_view, _ = _view()

    schema = build_hybrid_response_schema(simple_v3_view)
    assert "fee_rate" in semantic_id_enum(schema)


def test_semantic_link_enum_is_exactly_the_compact_catalog() -> None:
    """Catches a registered compact concept disappearing from the response schema."""
    _, view, _ = _view()

    schema = build_hybrid_response_schema(view)
    semantic_ids = {
        card.semantic_id for card in view.compact_semantic_catalog.concepts
    }
    link_schema = schema["properties"]["frames"]["items"]["properties"][
        "semantic_links"
    ]["items"]
    link_ids = set().union(
        *(
            set(choice["properties"]["semantic_ids"]["items"]["enum"])
            for choice in link_schema["oneOf"]
        )
    )
    assert link_ids == semantic_ids


def test_ambiguous_schema_requires_distinct_catalog_ids() -> None:
    """Catches a schema accepting repeated IDs as a semantic ambiguity."""
    _, view, _ = _view()

    link_schema = build_hybrid_response_schema(view)["properties"]["frames"][
        "items"
    ]["properties"]["semantic_links"]["items"]
    ambiguous = link_schema["oneOf"][1]["properties"]["semantic_ids"]
    assert ambiguous["minItems"] == 2
    assert ambiguous["uniqueItems"] is True


def test_hybrid_prompt_uses_explicit_unmapped_outputs_and_compact_payload() -> None:
    """Catches nearest-concept instructions or physical implementation leakage."""
    context, view, catalog = _view()
    envelope = build_hybrid_prompt(context, view, catalog)
    payload = (
        f"{envelope.system_message}\n{envelope.user_message}\n"
        f"{json.dumps(envelope.response_schema)}"
    )

    assert "unmapped_mention_ids" in envelope.system_message
    assert "nearest" not in envelope.system_message.lower()
    assert "raw TBox" not in payload
    assert "SHACL" not in payload
    assert "SELECT " not in payload
    assert "FROM " not in payload
    assert "column_name" not in payload
    assert "catalog.observation" not in payload
    assert "bindings" not in payload
    assert "formulas" not in payload
