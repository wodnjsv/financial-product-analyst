"""Relation objects remain directed constraints on product subjects."""

from datetime import date
import json

import pytest
from pydantic import ValidationError

from financial_agent.contracts.enums import AnswerDisposition
from financial_agent.contracts.values import decode_contract_value
from financial_agent.intent.candidates import EntityCandidate
from financial_agent.intent.model import ModelInvocationResult
from financial_agent.intent.query_contracts import QueryScopeV2, RelationConditionV2
from financial_agent.planning.contracts import CompilationRoute
from financial_agent.planning.physical_bindings import (
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)
from financial_agent.planning.registry import load_planning_registry
from financial_agent.sql.compiler import SemanticSqlCompiler
from financial_agent.sql.result_mapping import SqlResultMappingError, map_sql_rows
from tests.intent.test_personal_intent import Adapter, PIN, ROOT, service


class _RelationEntities:
    def __init__(self, object_type):
        self.object_type = object_type

    async def search_batch(self, dataset_version, mentions):
        return {
            mention.mention_id: (EntityCandidate(
                entity_id="relation-object-1", canonical_name=mention.text,
                ontology_type_ids=(self.object_type,), product_family=None,
                match_kind="exact_name", score=1_000_000, source_id="source-1",
            ),)
            for mention in mentions
        }


class _RelationAdapter(Adapter):
    def __init__(self, relation_id, field=None, *, action="screen"):
        super().__init__("domestic_etf", field, action=action)
        self.relation_id = relation_id
        self.object_type = "Security" if relation_id == "holdsSecurity" else "AssetManager"

    async def invoke(self, envelope, timeout_seconds):
        result = await super().invoke(envelope, timeout_seconds)
        payload = json.loads(result.content)
        frame = payload["frames"][0]
        frame["entity_type_ids"] = ["ETF"]
        mention_id = frame["entity_hints"][0]["mention_id"][0]
        frame["semantic_links"].append({
            "mention_id": mention_id, "state": "selected",
            "semantic_ids": [self.relation_id], "reason_code": "implicit",
        })
        for hint in frame["entity_hints"]:
            hint.update({"semantic_role": "relation_object",
                         "relation_id": [self.relation_id],
                         "expected_entity_type_ids": [self.object_type]})
        return ModelInvocationResult(content=json.dumps(payload), usage=result.usage)


async def _resolve(relation_id, question, *, field=None, action="screen"):
    name = "삼성전자" if relation_id == "holdsSecurity" else "삼성자산운용"
    adapter = _RelationAdapter(relation_id, field, action=action)
    resolver = service(adapter, name=name)
    resolver._resolver._entity_repository = _RelationEntities(adapter.object_type)
    return await resolver.resolve(question)


@pytest.mark.asyncio
@pytest.mark.parametrize("relation_id,question,field", [
    ("managedBy", "삼성자산운용의 국내 ETF 중 총보수 0.1% 이하", "fee_rate"),
    ("managedBy", "삼성자산운용의 국내 ETF 찾아줘", None),
    ("holdsSecurity", "2026-08-21 삼성전자를 보유한 국내 ETF 찾아줘", None),
])
async def test_relation_object_is_preserved_outside_product_scope(relation_id, question, field):
    result = await _resolve(relation_id, question, field=field)

    assert result.route is CompilationRoute.COMPOSE
    assert result.issue_codes == ()
    contract = result.attempt.candidates.frames[0].complete_candidates[0].contract
    assert contract.scope.entity_refs == ()
    condition, = contract.scope.relation_conditions
    assert condition.relation_id == relation_id
    assert condition.object_entity_id == "relation-object-1"
    assert condition.direction == "subject_to_object"
    assert condition.object_ontology_type_id == ("Security" if relation_id == "holdsSecurity" else "AssetManager")
    assert (contract.predicate is None) == (field is None)
    task, = result.compilation.logical_query_plan.tasks
    assert task.scope == contract.scope
    assert all(step.execution_route.value == "semantic_sql" for step in task.execution_steps)
    assert {"relation_record", "evidence_record", "source_record"} <= set(task.evidence_requirements)


@pytest.mark.asyncio
async def test_holding_condition_without_as_of_is_not_broadened():
    result = await _resolve("holdsSecurity", "삼성전자를 보유한 국내 ETF 찾아줘")

    assert result.route is CompilationRoute.EXPLORE
    assert result.disposition is AnswerDisposition.LIMITATION
    assert "PHYSICAL_REQUIRED_QUALIFIER_MISSING" in result.issue_codes
    assert result.compilation.logical_query_plan is None
    contract = result.attempt.candidates.frames[0].complete_candidates[0].contract
    assert contract.scope.entity_refs == ()
    assert contract.scope.relation_conditions[0].object_entity_id == "relation-object-1"
    assert contract.qualifiers.as_of_date is None


@pytest.mark.asyncio
async def test_relation_only_lookup_has_only_registered_product_projection():
    result = await _resolve("managedBy", "삼성자산운용의 국내 ETF 조회", action="lookup")
    assert result.issue_codes == ()
    plan = result.compilation.logical_query_plan
    compiler = SemanticSqlCompiler(load_physical_binding_registry(ROOT),
        load_semantic_sql_policy_registry(ROOT), load_planning_registry(ROOT), PIN)
    request = compiler.compile_task(plan, plan.tasks[0].task_id).request
    assert request is not None
    mapped = map_sql_rows(request, [{"product_id": "product-1", "product_name": "검증 ETF",
        "relation_ids_0": ["relation-1"], "relation_evidence_ids_0": ["evidence-1"],
        "relation_source_ids_0": ["source-1"]}])
    assert [field.field_id for field in mapped.result_rows[0].fields] == ["product_name"]


@pytest.mark.asyncio
async def test_relation_only_period_qualifier_is_not_dropped():
    result = await _resolve("holdsSecurity", "2026-08-21 최근 1년 삼성전자를 보유한 국내 ETF 찾아줘")
    assert result.route is CompilationRoute.EXPLORE
    assert "PHYSICAL_QUALIFIER_UNSUPPORTED" in result.issue_codes
    assert result.compilation.logical_query_plan is None
    contract = result.attempt.candidates.frames[0].complete_candidates[0].contract
    assert contract.qualifiers.period_id == "P1Y"


@pytest.mark.asyncio
@pytest.mark.parametrize("relation_id,question", [
    ("holdsSecurity", "2026-08-21 삼성전자를 보유하지 않은 국내 ETF 찾아줘"),
    ("holdsSecurity", "2026-08-21 삼성전자를 보유하지는 않은 국내 ETF 찾아줘"),
    ("holdsSecurity", "2026-08-21 삼성전자를 안 보유한 국내 ETF 찾아줘"),
    ("holdsSecurity", "2026-08-21 삼성전자가 없는 국내 ETF 찾아줘"),
    ("managedBy", "삼성자산운용 또는 미래에셋자산운용의 국내 ETF 찾아줘"),
])
async def test_relation_negation_and_disjunction_do_not_become_positive_and(relation_id, question):
    result = await _resolve(relation_id, question)
    assert result.route is CompilationRoute.EXPLORE
    assert result.disposition is AnswerDisposition.LIMITATION
    assert "RELATION_BOOLEAN_SCOPE_UNSUPPORTED" in result.issue_codes
    assert result.compilation is None


@pytest.mark.asyncio
async def test_relation_boolean_guard_masks_known_name_negation_surfaces():
    name = "안 보유 없는 성장운용"
    adapter = _RelationAdapter("managedBy")
    resolver = service(adapter, name=name)
    resolver._resolver._entity_repository = _RelationEntities("AssetManager")

    result = await resolver.resolve(f"{name}의 국내 ETF 찾아줘")

    assert result.route is CompilationRoute.COMPOSE
    assert result.issue_codes == ()
    assert result.compilation.logical_query_plan is not None


@pytest.mark.parametrize("updates,reason", [
    ({"direction": "object_to_subject"}, "subject_to_object"),
    ({"relation_id": "containsSecurity"}, "managedBy"),
    ({"object_ontology_type_id": "Security"}, "RELATION_OBJECT_TYPE_MISMATCH"),
])
def test_unregistered_direction_relation_and_endpoint_fail_closed(updates, reason):
    with pytest.raises(ValidationError, match=reason):
        RelationConditionV2.model_validate({"relation_id": "managedBy",
            "object_entity_id": "manager-1", "object_ontology_type_id": "AssetManager", **updates})


def test_empty_relation_extension_preserves_legacy_scope_and_object_never_becomes_product():
    scope = QueryScopeV2.model_validate_json('{"product_family_ids":["domestic_etf"]}')
    assert "relation_conditions" not in scope.model_dump(mode="json")
    with pytest.raises(ValidationError, match="RELATION_OBJECT_IN_PRODUCT_SCOPE"):
        QueryScopeV2(product_family_ids=scope.product_family_ids, entity_refs=("manager-1",),
            relation_conditions=(RelationConditionV2(relation_id="managedBy",
                object_entity_id="manager-1", object_ontology_type_id="AssetManager"),))


@pytest.mark.asyncio
async def test_relation_only_sql_is_directed_and_returns_grounding_lineage():
    result = await _resolve("holdsSecurity", "2026-08-21 삼성전자를 보유한 국내 ETF 찾아줘")
    plan = result.compilation.logical_query_plan
    compiler = SemanticSqlCompiler(load_physical_binding_registry(ROOT),
        load_semantic_sql_policy_registry(ROOT), load_planning_registry(ROOT), PIN)
    outcome = compiler.compile_task(plan, plan.tasks[0].task_id)

    assert outcome.rejection is None
    request = outcome.request
    assert request is not None
    assert "relation.relation_record" in request.statement
    assert "evidence.evidence_relation_origin" in request.statement
    assert "subject_id" in request.statement and "object_id" in request.statement
    values = {decode_contract_value(parameter.value) for parameter in request.parameters}
    assert {"holdsSecurity", "relation-object-1", date(2026, 8, 21)} <= values
    assert "holding_position" not in request.statement
    row = {"product_id": "product-1", "product_name": "검증 ETF",
           "relation_ids_0": ["relation-1"], "relation_evidence_ids_0": ["evidence-1"],
           "relation_source_ids_0": ["source-1"]}
    mapped = map_sql_rows(request, [row])
    assert mapped.result_rows[0].entity_ids == ("product-1",)
    assert mapped.evidence_refs == ("evidence:evidence-1", "relation:relation-1", "source:source-1")
    with pytest.raises(SqlResultMappingError, match="RETURNED_RELATION_IDS_MALFORMED"):
        map_sql_rows(request, [{**row, "relation_ids_0": []}])
    compiler.validate_request_for_execution(request, plan)
