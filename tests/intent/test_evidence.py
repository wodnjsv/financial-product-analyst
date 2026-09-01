from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import (
    NamedEntityMention,
    RequestContext,
    Segment,
)
from financial_agent.intent.candidates import (
    EntityCandidate,
    generate_semantic_candidates,
)
from financial_agent.intent.catalog import load_catalog
from financial_agent.intent.evidence import build_evidence_candidates
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.normalization import normalize_request


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def inputs_for(
    question: str,
    *,
    named_entities: tuple[NamedEntityMention, ...] = (),
) -> dict[str, object]:
    created_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    context = RequestContext(
        request_key=build_request_key("q-evidence", question, "dataset-v1", "1.0"),
        run_id="run-evidence",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="q-evidence",
        question=question,
        segments=(Segment(segment_id="s1", ordinal=0, text=question),),
        named_entities=named_entities,
        deadline_at=created_at + timedelta(seconds=10),
    )
    catalog = load_catalog(PROJECT_ROOT)
    normalized = normalize_request(context)
    return {
        "normalized": normalized,
        "literals": extract_literals(normalized),
        "semantic_candidates": generate_semantic_candidates(normalized, catalog),
        "entity_candidates": {},
        "policy_cues": catalog.policy_cues,
    }


def test_duplicate_surface_text_keeps_distinct_evidence_ids() -> None:
    """Catches merging repeated text that occurs at different original coordinates."""
    evidence = build_evidence_candidates(**inputs_for("ETF와 ETF를 비교해줘"))

    etf = [item for item in evidence if item.text == "ETF"]
    assert len(etf) == 2
    assert etf[0].evidence_id != etf[1].evidence_id
    assert [(item.start_char, item.end_char) for item in etf] == [(0, 3), (5, 8)]


def test_same_span_merges_offered_semantic_ids() -> None:
    """Catches dropping one registered meaning for an ambiguous surface span."""
    evidence = build_evidence_candidates(**inputs_for("위험등급"))

    item = next(value for value in evidence if value.text == "위험등급")
    assert item.offered_semantic_ids == ("credit_grade", "product_risk_grade")


def test_surface_evidence_uses_bounded_uncovered_tokens() -> None:
    """Catches turning uncovered text into whole-sentence or arbitrary n-grams."""
    evidence = build_evidence_candidates(
        **inputs_for("미등록어! " + "가" * 33 + " ETF")
    )

    surfaces = [item for item in evidence if "surface" in item.source_kinds]
    assert [item.text for item in surfaces] == ["미등록어", "가" * 32, "가"]
    assert all(len(item.text) <= 32 for item in surfaces)


def test_policy_cue_is_exact_original_span_evidence() -> None:
    """Catches policy evidence being omitted or mapped through normalized offsets."""
    question = "내 투자성향에 맞춰 ETF를 골라줘"
    evidence = build_evidence_candidates(**inputs_for(question))

    item = next(
        value for value in evidence if value.text == "내 투자성향에 맞춰"
    )
    assert item.source_kinds == ("policy",)
    assert item.offered_semantic_ids == ("PERSONALIZED_ADVICE",)
    assert question[item.start_char : item.end_char] == item.text


def test_duplicate_named_entity_text_is_not_assigned_an_ambiguous_coordinate() -> None:
    """Catches assigning entity evidence to the first repeated source occurrence."""
    inputs = inputs_for(
        "KODEX, KODEX",
        named_entities=(
            NamedEntityMention(
                mention_id="named-kodex",
                segment_id="s1",
                text="KODEX",
                expected_entity_types=("ETF",),
            ),
        ),
    )
    inputs["entity_candidates"] = {
        "named-kodex": (
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
    }

    evidence = build_evidence_candidates(**inputs)
    kodex = [item for item in evidence if item.text == "KODEX"]

    assert [(item.start_char, item.end_char) for item in kodex] == [(0, 5), (7, 12)]
    assert all(item.source_kinds == ("surface",) for item in kodex)
