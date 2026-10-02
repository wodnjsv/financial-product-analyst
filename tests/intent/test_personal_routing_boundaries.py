"""Personal routing must preserve entity roles and typed result-set ownership."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from financial_agent.contracts.enums import AnswerDisposition, Cardinality
from financial_agent.intent.candidates import EntityCandidate
from financial_agent.intent.model import ModelInvocationResult
from financial_agent.intent.resolution import ValidatedContextLink
from financial_agent.intent.types import (
    ContextLinkType,
    EntitySemanticRole,
    ReferenceTargetKind,
    Selector,
    SourceRole,
)
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.semantic_compiler import PriorResultOwnershipV2
from tests.intent.test_personal_intent import Adapter, service


class _ManagerEntities:
    async def search_batch(self, dataset_version, mentions):
        return {
            mention.mention_id: (
                EntityCandidate(
                    entity_id="manager-1",
                    canonical_name=mention.text,
                    ontology_type_ids=("AssetManager", "Organization"),
                    product_family=None,
                    match_kind="exact_name",
                    score=1_000_000,
                    source_id="manager-source",
                ),
            )
            for mention in mentions
        }


class _ManagerRelationAdapter(Adapter):
    async def invoke(self, envelope, timeout_seconds):
        result = await super().invoke(envelope, timeout_seconds)
        payload = json.loads(result.content)
        view = json.loads(envelope.user_message)["view"]
        frame = payload["frames"][0]
        mention = next(
            item for item in view["mention_spans"]["items"]
            if item["text"] == "삼성자산운용"
        )
        frame["semantic_links"].append({
            "mention_id": mention["mention_id"],
            "state": "selected",
            "semantic_ids": ["managedBy"],
            "reason_code": "implicit",
        })
        for hint in frame["entity_hints"]:
            hint.update({
                "semantic_role": "relation_object",
                "relation_id": ["managedBy"],
                "expected_entity_type_ids": ["AssetManager"],
            })
        return ModelInvocationResult(content=json.dumps(payload), usage=result.usage)


@pytest.mark.asyncio
async def test_relation_object_cannot_be_approved_as_a_product_scope():
    resolver = service(
        _ManagerRelationAdapter("domestic_etf", "fee_rate", action="lookup"),
        name="삼성자산운용",
    )
    resolver._resolver._entity_repository = _ManagerEntities()

    result = await resolver.resolve("삼성자산운용의 국내 ETF 총보수 조회")

    assert result.route is CompilationRoute.EXPLORE
    assert result.disposition is AnswerDisposition.LIMITATION
    assert "ENTITY_RELATION_SCOPE_NOT_LOWERABLE" in result.issue_codes
    assert result.compilation is None
    assert result.attempt.resolution.entity_hints[0].semantic_role is EntitySemanticRole.RELATION_OBJECT


class _OwnershipCheckingCompiler:
    def __init__(self):
        self.owners = ()

    def assess_in_dependency_order(self, *, prior_result_ownership, selected_candidates, **kwargs):
        # Invoke the production contract validator, including its mandatory
        # cardinality field, rather than accepting an arbitrary stub owner.
        self.owners = tuple(
            PriorResultOwnershipV2.model_validate(owner.model_dump())
            for owner in prior_result_ownership
        )
        return tuple(
            SimpleNamespace(plan=SimpleNamespace(reason_codes=()))
            for _ in selected_candidates
        )

    def compile(self, **kwargs):
        return SimpleNamespace(
            route=CompilationRoute.EXPLORE,
            recommended_answer_disposition=AnswerDisposition.LIMITATION,
            blocking_issues=(),
        )


@pytest.mark.asyncio
async def test_prior_result_set_ownership_preserves_many_cardinality_without_crashing():
    resolver = service(Adapter("domestic_etf", "fee_rate"))
    first_result = await resolver.resolve("국내 ETF 총보수가 낮은 5개")
    first_attempt = first_result.attempt
    producer = first_attempt.resolution.canonical_frames[0]
    consumer = producer.model_copy(update={"frame_id": "frame-consumer", "ordinal": 1})
    first_group = first_attempt.candidates.frames[0]
    first_candidate = first_group.complete_candidates[0]
    consumer_contract = first_candidate.contract.model_copy(update={
        "frame_id": consumer.frame_id,
        "scope": first_candidate.contract.scope.model_copy(update={
            "product_family_ids": (),
            "prior_result_binding": producer.frame_id,
        }),
    })
    consumer_group = first_group.model_copy(update={
        "frame_id": consumer.frame_id,
        "complete_candidates": (
            first_candidate.model_copy(update={
                "candidate_id": "candidate-consumer",
                "contract": consumer_contract,
            }),
        ),
    })
    link = ValidatedContextLink(
        context_link_id="link-result-set",
        reference_id="ref-result-set",
        link_type=ContextLinkType.CONSUME_RESULT_SET,
        source_role=SourceRole.CANDIDATES,
        selector=(Selector.ALL,),
        selector_literal_candidate_id=(),
        producer_frame_id=producer.frame_id,
        consumer_frame_id=consumer.frame_id,
        target_kind=(ReferenceTargetKind.RESULT_SET,),
        target_cardinality=(Cardinality.MANY,),
        target_slot_kind=(),
    )
    attempt = replace(
        first_attempt,
        resolution=first_attempt.resolution.model_copy(update={
            "canonical_frames": (producer, consumer),
            "context_links": (link,),
        }),
        candidates=first_attempt.candidates.model_copy(update={
            "frames": (first_group, consumer_group),
        }),
    )
    compiler = _OwnershipCheckingCompiler()
    resolver._compiler = compiler

    result = resolver._route(first_result.context, attempt)

    assert result.route is CompilationRoute.EXPLORE
    assert len(compiler.owners) == 1
    assert compiler.owners[0].binding_id == producer.frame_id
    assert compiler.owners[0].producer_frame_id == producer.frame_id
    assert compiler.owners[0].cardinality is Cardinality.MANY
