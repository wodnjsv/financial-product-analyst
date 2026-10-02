from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from financial_agent.contracts.canonical import build_request_key
from financial_agent.contracts.request import NamedEntityMention, RequestContext, Segment
from financial_agent.intent.candidates import EntityCandidate, Mention
from financial_agent.intent.catalog import load_hybrid_catalog
from financial_agent.intent.entity_discovery import (
    MAX_CATALOG_SURFACES,
    EntityDiscoveryError,
    EntityMentionDiscovery,
)
from financial_agent.intent.entity_repository import (
    EntityCandidateRepository,
    ResolverCatalogUnavailable,
    _search_statement,
)
from financial_agent.intent.normalization import normalize_request
from financial_agent.intent.service import IntentResolverService, _entity_mentions, _hybrid_entity_mentions
from financial_agent.intent.mention_spans import generate_mention_spans
from financial_agent.intent.view import ActiveDatasetPin, _validated_hybrid_output_capabilities, build_hybrid_manifest
from financial_agent.intent.evidence import EvidenceSourceKind
from financial_agent.intent.types import ResolutionStatus
from tests.intent.view_fixtures import hybrid_manifest_versions


def context(question: str, *, segments: tuple[Segment, ...] | None = None) -> RequestContext:
    created_at = datetime(2026, 10, 2, tzinfo=UTC)
    return RequestContext(
        request_key=build_request_key("discovery", question, "dataset-v1", "1.0"),
        run_id="run-discovery",
        dataset_version="dataset-v1",
        producer="test",
        created_at=created_at,
        question_id="discovery",
        question=question,
        segments=segments or (Segment(segment_id="s1", ordinal=0, text=question),),
        deadline_at=created_at + timedelta(seconds=55),
    )


class FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict[str, object]], error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    def begin(self) -> FakeConnection:
        return self

    async def execute(self, statement: object, parameters: dict[str, object] | None = None) -> FakeResult:
        self.calls.append((str(statement), parameters))
        if str(statement).lstrip().startswith("WITH") and self.error is not None:
            raise self.error
        return FakeResult(self.rows)


class FakeEngine:
    def __init__(self, surfaces: list[str], *, available: bool = True, error: Exception | None = None) -> None:
        rows: list[dict[str, object]] = [
            {"surface": None, "dataset_exists": available, "is_dataset_status": True}
        ]
        rows.extend(
            {"surface": surface, "dataset_exists": True, "is_dataset_status": False}
            for surface in surfaces
        )
        self.connection = FakeConnection(rows, error)
        self.connections = 0

    def connect(self) -> FakeConnection:
        self.connections += 1
        return self.connection


@pytest.mark.asyncio
async def test_discovery_keeps_exact_original_spans_and_all_repeated_occurrences() -> None:
    question = "삼성\t전자 비중과 삼성전자 위험을 알려줘"
    engine = FakeEngine(["삼성전자"])
    mentions = await EntityMentionDiscovery(engine).discover(context(question))

    assert [mention.text for mention in mentions] == ["삼성\t전자", "삼성전자"]
    assert [(mention.start_char, mention.end_char) for mention in mentions] == [(0, 5), (10, 14)]
    assert all(question[mention.start_char:mention.end_char] == mention.text for mention in mentions)
    assert len({mention.mention_id for mention in mentions}) == 2
    assert all(mention.expected_entity_types == () for mention in mentions)

    enriched = context(question).model_copy(update={"named_entities": mentions})
    normalized = normalize_request(enriched)
    assert [(mention.start_char, mention.end_char) for mention in _entity_mentions(enriched, normalized)] == [(0, 5), (10, 14)]
    assert [(mention.start_char, mention.end_char) for mention in _hybrid_entity_mentions(enriched, normalized)] == [(0, 5), (10, 14)]
    spans = generate_mention_spans(normalized, (), (), _hybrid_entity_mentions(enriched, normalized), ())
    assert _validated_hybrid_output_capabilities(enriched, normalized, spans) == (True, False)


@pytest.mark.asyncio
async def test_longer_names_suppress_nested_mentions_without_losing_separate_short_names() -> None:
    question = "삼성전자와 삼성전자우를 비교해줘"
    mentions = await EntityMentionDiscovery(FakeEngine(["삼성", "삼성전자", "삼성전자우"])).discover(context(question))
    assert [mention.text for mention in mentions] == ["삼성전자", "삼성전자우"]


@pytest.mark.asyncio
async def test_overlapping_names_preserve_non_contained_ambiguity_and_group_duplicate_surface() -> None:
    question = "가나다라를 조회해줘"
    mentions = await EntityMentionDiscovery(FakeEngine(["가나다", "나다라", "가나다"])).discover(context(question))
    assert [mention.text for mention in mentions] == ["가나다", "나다라"]


@pytest.mark.asyncio
async def test_identifier_alias_full_width_and_punctuation_use_original_source() -> None:
    question = "０６９５００과 tiger 200, S&P 500을 비교해줘"
    mentions = await EntityMentionDiscovery(FakeEngine(["069500", "TIGER200", "S&P500"])).discover(context(question))
    assert [mention.text for mention in mentions] == ["０６９５００", "tiger 200", "S&P 500"]


@pytest.mark.asyncio
async def test_long_product_names_are_not_limited_to_four_phrase_tokens() -> None:
    name = "Synthetic Global Long Term Corporate Bond Index Fund"
    question = f"{name}의 보수를 알려줘"
    mentions = await EntityMentionDiscovery(FakeEngine([name.replace(" ", "").upper()])).discover(context(question))
    assert [mention.text for mention in mentions] == [name]


@pytest.mark.asyncio
async def test_generic_surfaces_and_partial_ascii_identifiers_do_not_create_entities() -> None:
    question = "ETF 펀드 미국 해외 상품 AAAPL, 10695000 대신 AAPL을 찾아줘"
    mentions = await EntityMentionDiscovery(FakeEngine(["ETF", "펀드", "미국", "해외", "상품", "AA", "AAPL", "069500"])).discover(context(question))
    assert [mention.text for mention in mentions] == ["AAPL"]


@pytest.mark.asyncio
async def test_discovery_is_dataset_pinned_bounded_and_one_batched_read_only_lookup() -> None:
    question = "삼성전자와 TIGER 200"
    engine = FakeEngine(["삼성전자", "TIGER200"])
    await EntityMentionDiscovery(engine).discover(context(question))
    assert engine.connections == 1
    statements = engine.connection.calls
    assert statements[0][0] == "SET TRANSACTION READ ONLY"
    assert "statement_timeout" in statements[1][0]
    query, parameters = statements[2]
    assert len(statements) == 3
    assert parameters["dataset_version"] == "dataset-v1"
    assert parameters["segment_text_0"] == "삼성전자와TIGER200"
    assert question not in query
    assert "catalog.identifier" in query
    assert "entity.normalized_name" in query
    assert "alias.normalized_alias_text" in query
    assert "alias.valid_from <= dataset.cutoff_date" in query
    assert "alias.valid_to >= dataset.cutoff_date" in query
    assert "LIMIT :surface_limit" in query
    assert parameters["surface_limit"] == MAX_CATALOG_SURFACES + 1
    assert "'product', 'security', 'company', 'institution'" in query


@pytest.mark.asyncio
async def test_more_than_sixteen_final_mentions_fail_closed_without_truncation() -> None:
    names = [f"가나다{i:02d}" for i in range(17)]
    with pytest.raises(EntityDiscoveryError, match="ENTITY_MENTION_LIMIT_EXCEEDED"):
        await EntityMentionDiscovery(FakeEngine(names)).discover(context(" ".join(names)))


@pytest.mark.asyncio
async def test_lexical_candidate_overflow_is_explicit_before_silent_selection() -> None:
    names = [f"가나다{i:02d}" for i in range(MAX_CATALOG_SURFACES + 1)]
    with pytest.raises(EntityDiscoveryError, match="ENTITY_DISCOVERY_SURFACE_LIMIT_EXCEEDED"):
        await EntityMentionDiscovery(FakeEngine(names)).discover(context(" ".join(names)))


@pytest.mark.asyncio
async def test_multiple_segments_keep_local_source_offsets_and_order() -> None:
    segments = (
        Segment(segment_id="s1", ordinal=0, text="삼성전자 알려줘"),
        Segment(segment_id="s2", ordinal=1, text="TIGER 200과 비교해줘"),
    )
    mentions = await EntityMentionDiscovery(FakeEngine(["TIGER200", "삼성전자"])).discover(context("삼성전자 알려줘 TIGER 200과 비교해줘", segments=segments))
    assert [(mention.segment_id, mention.start_char, mention.text) for mention in mentions] == [
        ("s1", 0, "삼성전자"), ("s2", 0, "TIGER 200")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("available,error", [(False, None), (True, SQLAlchemyError("secret database URL"))])
async def test_unavailable_catalog_has_stable_secret_free_error(available: bool, error: Exception | None) -> None:
    with pytest.raises(ResolverCatalogUnavailable) as caught:
        await EntityMentionDiscovery(FakeEngine(["삼성전자"], available=available, error=error)).discover(context("삼성전자"))
    assert str(caught.value) == "RESOLVER_CATALOG_UNAVAILABLE"


@pytest.mark.asyncio
async def test_segment_size_limit_is_checked_before_database_connection() -> None:
    engine = FakeEngine([])
    with pytest.raises(EntityDiscoveryError, match="ENTITY_DISCOVERY_INPUT_LIMIT_EXCEEDED"):
        await EntityMentionDiscovery(engine).discover(context("짧은 질문", segments=(Segment(segment_id="s1", ordinal=0, text="가" * 4097),)))
    assert engine.connections == 0


@pytest.mark.asyncio
async def test_discovered_repeated_name_survives_real_hybrid_preparation_and_entity_evidence() -> None:
    question = "삼성전자 비중과 삼성전자 위험을 알려줘"
    source = context(question)
    mentions = await EntityMentionDiscovery(FakeEngine(["삼성전자"])).discover(source)
    enriched = source.model_copy(update={"named_entities": mentions})

    class CandidateRepository:
        async def search_batch(self, _dataset: str, spans: tuple[Mention, ...]) -> dict[str, tuple[EntityCandidate, ...]]:
            return {
                span.mention_id: (EntityCandidate(
                    entity_id="security-samsung",
                    canonical_name="삼성전자",
                    ontology_type_ids=("EquitySecurity", "Security"),
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="source-samsung",
                ),)
                for span in spans
            }

    class NoModelAdapter:
        async def invoke(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("preparation must not call a model")

    catalog = load_hybrid_catalog(Path(__file__).resolve().parents[2])
    service = IntentResolverService(
        adapter=NoModelAdapter(),
        entity_repository=CandidateRepository(),
        catalog=catalog,
        manifest=build_hybrid_manifest(catalog, hybrid_manifest_versions()),
        active_dataset_pin=ActiveDatasetPin(dataset_version="dataset-v1", manifest_hash="a" * 64),
        utcnow=lambda: enriched.created_at,
    )
    prepared = await service.prepare_hybrid(enriched)
    assert prepared.view.entity_output_enabled is True
    assert prepared.view.reference_output_enabled is False
    entity_evidence = [
        (item.start_char, item.end_char)
        for item in prepared.view.evidence_candidates
        if EvidenceSourceKind.ENTITY in item.source_kinds
    ]
    assert entity_evidence == [(0, 4), (9, 13)]
    assert len(prepared.entity_candidates) == 2


@pytest.mark.asyncio
async def test_discovered_entity_id_survives_schema_assembly_and_hybrid_validation() -> None:
    """A discovered entity must have the same ID in span and candidate namespaces."""
    question = "KODEX 200의 총보수를 알려줘"
    source = context(question)
    mentions = await EntityMentionDiscovery(FakeEngine(["KODEX200"])).discover(source)
    enriched = source.model_copy(update={"named_entities": mentions})

    class CandidateRepository:
        async def search_batch(self, _dataset: str, spans: tuple[Mention, ...]) -> dict[str, tuple[EntityCandidate, ...]]:
            return {
                span.mention_id: (EntityCandidate(
                    entity_id="synthetic-kodex-200",
                    canonical_name="KODEX 200",
                    ontology_type_ids=("DomesticETF", "ETF", "FinancialProduct"),
                    product_family="domestic_etf",
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="synthetic-kodex-200",
                ),)
                for span in spans
            }

    class NoModelAdapter:
        async def invoke(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("preparation and response validation must not call a model")

    catalog = load_hybrid_catalog(Path(__file__).resolve().parents[2])
    service = IntentResolverService(
        adapter=NoModelAdapter(),
        entity_repository=CandidateRepository(),
        catalog=catalog,
        manifest=build_hybrid_manifest(catalog, hybrid_manifest_versions()),
        active_dataset_pin=ActiveDatasetPin(dataset_version="dataset-v1", manifest_hash="a" * 64),
        utcnow=lambda: enriched.created_at,
    )
    prepared = await service.prepare_hybrid(enriched)
    fee_span = next(span for span in prepared.mention_spans.items if span.text == "총보수")
    payload = {
        "proposal_schema_version": "3.0",
        "frames": [{
            "segment_ids": ["s1"],
            "action_choice": {"state": "selected", "selected_ids": ["lookup"], "evidence_ids": [], "reason_code": "explicit"},
            "product_family_choice": {"state": "selected", "selected_ids": ["domestic_etf"], "evidence_ids": [], "reason_code": "explicit"},
            "entity_type_ids": ["FinancialProduct"],
            "semantic_links": [{"mention_id": fee_span.mention_id, "semantic_ids": ["fee_rate"], "state": "selected", "reason_code": "explicit"}],
            "unmapped_mention_ids": [],
            "semantic_coverage": {"state": "covered", "reason": "none"},
            "entity_hints": [{
                "semantic_role": "frame_subject", "relation_id": [],
                "expected_entity_type_ids": ["FinancialProduct"],
                "mention_id": [mentions[0].mention_id],
                "candidate_entity_ids": ["synthetic-kodex-200"],
                "selected_candidate_ids": ["synthetic-kodex-200"],
            }],
            "produced_result_hints": ["metric_value"],
        }],
        "references": [], "context_links": [], "slot_mutations": [],
        "semantic_flag_hints": [], "frame_limit_exceeded": False,
    }
    resolution = service.validate_hybrid_response(prepared, json.dumps(payload, ensure_ascii=False))
    assert resolution.resolution_status is ResolutionStatus.RESOLVED
    assert resolution.entity_hints[0].selected_candidate_ids == ("synthetic-kodex-200",)
    assert mentions[0].mention_id == "mention-s1-0-9"


def test_named_entity_source_ranges_are_paired_and_checked_against_original_segment() -> None:
    with pytest.raises(ValidationError):
        NamedEntityMention(mention_id="m1", segment_id="s1", text="삼성전자", expected_entity_types=(), start_char=0)
    with pytest.raises(ValidationError):
        NamedEntityMention(mention_id="m1", segment_id="s1", text="삼성전자", expected_entity_types=(), start_char=4, end_char=0)
    invalid = NamedEntityMention(mention_id="m1", segment_id="s1", text="삼성전자", expected_entity_types=(), start_char=1, end_char=5)
    values = {**context("삼성전자 알려줘").model_dump(), "named_entities": (invalid,)}
    with pytest.raises(ValidationError, match="named entity mention"):
        RequestContext.model_validate(values)


def test_legacy_named_entity_without_offsets_remains_compatible_but_repeated_hybrid_is_ambiguous() -> None:
    entity = NamedEntityMention(mention_id="m1", segment_id="s1", text="삼성전자", expected_entity_types=())
    legacy = context("삼성전자 알려줘").model_copy(update={"named_entities": (entity,)})
    assert _hybrid_entity_mentions(legacy, normalize_request(legacy))[0].start_char == 0
    repeated = context("삼성전자와 삼성전자").model_copy(update={"named_entities": (entity,)})
    with pytest.raises(ValueError, match="ENTITY_MENTION_RANGE_AMBIGUOUS"):
        _hybrid_entity_mentions(repeated, normalize_request(repeated))


def test_repository_exact_names_and_aliases_are_spacing_and_case_neutral() -> None:
    mention = Mention(mention_id="m1", segment_id="s1", text="tiger 200", normalized_text="tiger 200", start_char=0, end_char=9)
    statement, parameters = _search_statement("dataset-v1", (mention,))
    sql = str(statement)
    assert "upper(regexp_replace(entity.normalized_name" in sql
    assert "upper(regexp_replace(alias.normalized_alias_text" in sql
    assert "upper(regexp_replace(m.normalized_text" in sql
    assert "'exact_name'::text" in sql and "'exact_alias'::text" in sql
    assert parameters["normalized_text_0"] == "tiger 200"


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["domestic_etf", "overseas_etf"])
async def test_repository_preserves_official_product_type_facts_in_candidate_response(family: str) -> None:
    """The source type lookup must include current namespaced organizer metrics."""
    mention = Mention(mention_id="m1", segment_id="s1", text="Synthetic ETF", normalized_text="Synthetic ETF", start_char=0, end_char=13)
    engine = FakeEngine([])
    engine.connection.rows.append({
        "is_dataset_status": False,
        "mention_id": "m1",
        "entity_id": "synthetic-etf",
        "canonical_name": "Synthetic ETF",
        "storage_entity_type": "product",
        "product_family": family,
        "security_kind": None,
        "institution_kind": None,
        "identifier_schemes": [],
        "product_type_statuses": ["present"],
        "product_type_text_values": ["ETF"],
        "product_type_value_kinds": ["text"],
        "is_share_class_subject": False,
        "is_share_class_object": False,
        "match_kind": "exact_name",
        "score": 1_000_000,
        "source_id": "synthetic-etf",
    })
    candidates = await EntityCandidateRepository(engine).search_batch("dataset-v1", (mention,))
    expected_family_type = "DomesticETF" if family == "domestic_etf" else "OverseasETF"
    assert candidates["m1"][0].ontology_type_ids == tuple(sorted((expected_family_type, "ETF", "ExchangeTradedProduct", "FinancialProduct")))
    query, parameters = engine.connection.calls[0]
    assert parameters["product_type_metric_ids"] == [
        "product_type",
        "organizer.pref01n001.product_type",
        "organizer.pref02n001.product_type",
    ]
    assert query.count("product_type.metric_id = ANY(CAST(:product_type_metric_ids AS text[]))") == 3
