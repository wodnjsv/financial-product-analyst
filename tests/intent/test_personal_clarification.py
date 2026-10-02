"""Clarification does not guess names, families, periods or previous results."""

from copy import deepcopy
from types import SimpleNamespace as Object

import pytest

from financial_agent.contracts.enums import ProductFamily
from financial_agent.intent.personal_clarification import (
    ambiguous_product_family_frames,
    personal_clarifications,
    unsupported_boolean_frames,
)
from financial_agent.intent.types import ChoiceState, EntitySemanticRole


def result(*, family="domestic_etf", codes=(), rejections=(), state=ChoiceState.SELECTED):
    frame = Object(frame_id="f1", segment_ids=("s1",), entity_hint_ids=(),
                   product_family_choice=Object(selected_ids=(ProductFamily(family),), state=state))
    resolution = Object(canonical_frames=(frame,), entity_hints=(), issues=())
    view = Object(mention_spans=Object(items=()), exact_lock_projections=(), entity_candidates=())
    group = Object(frame_id="f1", complete_candidates=(), rejections=rejections)
    attempt = Object(resolution=resolution, view=view,
                     candidates=Object(frames=(group,), rejections=rejections))
    return Object(attempt=attempt, context=Object(named_entities=()), issue_codes=codes, compilation=None)


def lock(attempt, *, family="domestic_etf", segment="s1", mention="m1"):
    attempt.view.mention_spans.items += (Object(mention_id=mention, segment_id=segment),)
    attempt.view.exact_lock_projections += (
        Object(role="product_family", mention_id=mention, canonical_semantic_id=family),
    )


@pytest.mark.parametrize("family", ["domestic_etf", "overseas_etf", "domestic_bond", "public_fund"])
def test_generic_family_cannot_be_resolved_by_a_model_selection_alone(family):
    actual = result(family=family)
    assert ambiguous_product_family_frames(actual.attempt) == ("f1",)


def test_registered_explicit_listing_family_is_preserved():
    actual = result()
    lock(actual.attempt)
    assert ambiguous_product_family_frames(actual.attempt) == ()


@pytest.mark.parametrize("kind", ["exact_name", "exact_alias", "exact_identifier"])
def test_exact_subject_product_identity_resolves_listing_family(kind):
    actual = result()
    actual.attempt.view.entity_candidates = (Object(items=(
        Object(entity_id="product-1", product_family="domestic_etf", match_kind=kind),
    )),)
    hint = Object(entity_hint_id="h1", semantic_role=EntitySemanticRole.FRAME_SUBJECT,
                  selected_candidate_ids=("product-1",))
    actual.attempt.resolution.entity_hints = (hint,)
    actual.attempt.resolution.canonical_frames[0].entity_hint_ids = ("h1",)
    assert ambiguous_product_family_frames(actual.attempt) == ()


@pytest.mark.parametrize("kind,role", [
    ("trigram", EntitySemanticRole.FRAME_SUBJECT),
    ("exact_name", EntitySemanticRole.RELATION_OBJECT),
])
def test_typo_candidate_or_relation_object_does_not_supply_a_product_family(kind, role):
    actual = result()
    actual.attempt.view.entity_candidates = (Object(items=(
        Object(entity_id="candidate-1", product_family="domestic_etf", match_kind=kind),
    )),)
    hint = Object(entity_hint_id="h1", semantic_role=role, selected_candidate_ids=("candidate-1",))
    actual.attempt.resolution.entity_hints = (hint,)
    actual.attempt.resolution.canonical_frames[0].entity_hint_ids = ("h1",)
    assert ambiguous_product_family_frames(actual.attempt) == ("f1",)


def test_compound_frames_keep_both_scopes_and_report_only_the_unresolved_scope():
    actual = result()
    lock(actual.attempt)
    second = Object(frame_id="f2", segment_ids=("s2",), entity_hint_ids=(),
                    product_family_choice=Object(selected_ids=(ProductFamily.OVERSEAS_ETF,),
                                                 state=ChoiceState.SELECTED))
    actual.attempt.resolution.canonical_frames += (second,)
    actual.attempt.candidates.frames += (Object(frame_id="f2", complete_candidates=()),)
    assert ambiguous_product_family_frames(actual.attempt) == ("f2",)
    lock(actual.attempt, family="overseas_etf", segment="s2", mention="m2")
    assert ambiguous_product_family_frames(actual.attempt) == ()


def test_current_request_result_scope_can_be_inherited_without_cross_request_memory():
    actual = result()
    lock(actual.attempt)
    consumer = deepcopy(actual.attempt.resolution.canonical_frames[0])
    consumer.frame_id, consumer.segment_ids = "f2", ("s2",)
    actual.attempt.resolution.canonical_frames += (consumer,)
    actual.attempt.candidates.frames += (
        Object(frame_id="f2", complete_candidates=(
            Object(contract=Object(scope=Object(prior_result_binding="f1"))),
        )),
    )
    assert ambiguous_product_family_frames(actual.attempt) == ()
    actual.attempt.view.exact_lock_projections = ()
    assert ambiguous_product_family_frames(actual.attempt) == ("f1", "f2")


def test_missing_period_has_a_concrete_clarification_without_inventing_p1y():
    rejection = Object(reason_code="REQUIRED_QUALIFIER_MISSING",
                       role_id="field.trailing_1y_historical_cumulative_return.qualifier.period")
    actual = result(codes=("QUERY_CONTRACT_NOT_COMPLETE",), rejections=(rejection,))
    messages = personal_clarifications(actual)
    assert [item["code"] for item in messages] == ["PERIOD_MISSING"]
    assert "기간" in messages[0]["message"]
    assert "1년" not in messages[0]["message"]
    assert actual.compilation is None


def test_multiple_periods_remain_ambiguous():
    rejection = Object(reason_code="REQUIRED_QUALIFIER_AMBIGUOUS", role_id="field.return.qualifier.period")
    messages = personal_clarifications(result(rejections=(rejection,)))
    assert [item["code"] for item in messages] == ["PERIOD_AMBIGUOUS"]


def test_unresolved_name_asks_for_exact_spelling_and_does_not_select_a_candidate():
    actual = result(codes=("ENTITY_SCOPE_UNRESOLVED",))
    actual.context.named_entities = (Object(mention_id="unresolved-name", text="티거 200"),)
    messages = personal_clarifications(actual)
    assert [item["code"] for item in messages] == ["ENTITY_NAME_UNRESOLVED"]
    assert "오타" in messages[0]["message"]
    assert actual.attempt.resolution.entity_hints == ()
    assert actual.context.named_entities[0].text == "티거 200"


def test_unknown_lexical_meaning_does_not_get_a_guessed_product_correction():
    messages = personal_clarifications(result(codes=("SEMANTIC_CONCEPT_UNMAPPED",)))
    assert [item["code"] for item in messages] == ["REQUEST_MEANING_UNRESOLVED"]
    assert "오타" in messages[0]["message"]
    assert "TIGER" not in messages[0]["message"]


@pytest.mark.parametrize("code", ["REFERENCE_UNRESOLVED", "REFERENCE_AMBIGUOUS"])
def test_followup_requires_its_scope_in_the_current_question(code):
    messages = personal_clarifications(result(codes=(code,)))
    assert [item["code"] for item in messages] == ["FOLLOWUP_SCOPE_REQUIRED"]
    assert "자동으로 이어받지" in messages[0]["message"]
    assert "이번 질문" in messages[0]["message"]


def test_generic_family_message_and_compound_missing_requirement_are_both_preserved():
    actual = result(codes=("AMBIGUOUS_PRODUCT_FAMILY", "REQUESTED_FIELD_ROLE_MISSING"))
    assert [item["code"] for item in personal_clarifications(actual)] == [
        "AMBIGUOUS_PRODUCT_FAMILY", "REQUEST_REQUIREMENTS_INCOMPLETE",
    ]


def test_valid_executable_plan_is_not_reinterpreted_by_the_clarification_formatter():
    actual = result()
    actual.compilation = Object(logical_query_plan=object())
    before = deepcopy(actual)
    assert personal_clarifications(actual) == ()
    assert actual.issue_codes == before.issue_codes
    assert actual.attempt.resolution.canonical_frames[0].product_family_choice.selected_ids == (
        ProductFamily.DOMESTIC_ETF,
    )


def test_physical_data_limitation_is_not_misreported_as_a_user_clarification():
    assert personal_clarifications(result(codes=("PHYSICAL_BINDING_NOT_REGISTERED",))) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("question,expected_block", [
    ("ETF 중 총보수 0.1% 이하", True),
    ("국내 ETF 중 총보수 0.1% 이하", False),
    ("국내 상장 ETF 중 총보수 0.1% 이하", False),
])
async def test_actual_resolver_catalog_locks_control_generic_family_approval(question, expected_block):
    from tests.intent.test_personal_intent import Adapter
    from tests.intent.test_query_contract_service import _context, _hybrid_service

    resolver = _hybrid_service(Adapter("domestic_etf", "fee_rate", action="screen"))
    attempt = await resolver.resolve_hybrid_query_contract_candidates(_context(question))

    assert bool(ambiguous_product_family_frames(attempt)) is expected_block
    assert attempt.resolution.canonical_frames[0].product_family_choice.selected_ids == (
        ProductFamily.DOMESTIC_ETF,
    )
    assert attempt.candidates.frames[0].complete_candidates


def boolean_request(text, *, entities=()):
    actual = result()
    actual.context.segments = (Object(segment_id="s1", text=text),)
    mentions = []
    for index, entity in enumerate(entities):
        start = text.index(entity)
        mentions.append(Object(mention_id=f"entity-{index}", segment_id="s1", start_char=start,
                               end_char=start + len(entity), text=entity))
    actual.context.named_entities = tuple(mentions)
    return actual


@pytest.mark.parametrize("connector", ["또는", "혹은", "거나", "아니면", "OR", "or"])
def test_explicit_or_cannot_execute_as_an_and_predicate(connector):
    actual = boolean_request(f"국내 ETF 중 총보수 0.1% 이하 {connector} 1년 수익률 10% 이상")
    assert unsupported_boolean_frames(actual.context, actual.attempt) == ("f1",)


def test_explicit_korean_or_without_spaces_is_still_guarded():
    actual = boolean_request("국내 ETF 중 총보수 0.1%이하또는0.2%이상")
    assert unsupported_boolean_frames(actual.context, actual.attempt) == ("f1",)


@pytest.mark.parametrize("text,entities", [
    ("국내 ETF 중 총보수 0.1% 이하이고 1년 수익률 10% 이상", ()),
    ("국내 ETF 총보수 AND 수익률", ()),
    ("ORACLE 국내 ETF 총보수", ()),
    ("OR 국내 ETF 총보수", ("OR",)),
    ("합성 또는 성장 국내 ETF 총보수", ("합성 또는 성장",)),
    ("합성 혹은 성장 국내 ETF 총보수", ("합성 혹은 성장",)),
    ("합성거나성장 국내 ETF 총보수", ("합성거나성장",)),
    ("합성 아니면 성장 국내 ETF 총보수", ("합성 아니면 성장",)),
])
def test_names_and_conjunction_are_not_misclassified_as_or(text, entities):
    actual = boolean_request(text, entities=entities)
    assert unsupported_boolean_frames(actual.context, actual.attempt) == ()


def test_entity_name_masking_does_not_remove_a_real_or_elsewhere():
    actual = boolean_request("합성 또는 성장 국내 ETF 총보수 혹은 수익률", entities=("합성 또는 성장",))
    assert unsupported_boolean_frames(actual.context, actual.attempt) == ("f1",)


def test_boolean_guard_preserves_compound_frames_and_source_offsets():
    actual = boolean_request("국내 ETF 총보수 그리고 수익률")
    second = deepcopy(actual.attempt.resolution.canonical_frames[0])
    second.frame_id, second.segment_ids = "f2", ("s2",)
    actual.attempt.resolution.canonical_frames += (second,)
    actual.context.segments += (Object(segment_id="s2", text="국내 ETF 총보수 OR 수익률"),)
    before = deepcopy(actual)
    assert unsupported_boolean_frames(actual.context, actual.attempt) == ("f2",)
    assert actual == before


@pytest.mark.asyncio
async def test_actual_resolver_or_source_is_guarded_despite_complete_contract():
    from tests.intent.test_personal_intent import Adapter
    from tests.intent.test_query_contract_service import _context, _hybrid_service

    resolver = _hybrid_service(Adapter("domestic_etf", "fee_rate", action="screen"))
    context = _context("국내 ETF 중 총보수 0.1% 이하 또는 0.2% 이상")
    attempt = await resolver.resolve_hybrid_query_contract_candidates(context)
    assert attempt.candidates.frames[0].complete_candidates
    predicate = attempt.candidates.frames[0].complete_candidates[0].contract.predicate
    assert predicate.node_type == "all_of"
    assert [child.operator_id for child in predicate.children] == ["lte", "gte"]
    assert unsupported_boolean_frames(context, attempt) == (attempt.resolution.canonical_frames[0].frame_id,)


@pytest.mark.asyncio
@pytest.mark.parametrize("connector", ["이거나", " 아니면"])
async def test_korean_or_variants_cannot_approve_a_conjunctive_plan(connector):
    from tests.intent.test_personal_intent import Adapter, service

    result = await service(Adapter("domestic_etf", "fee_rate", action="screen")).resolve(
        f"국내 ETF 중 총보수 0.1% 이하{connector} 0.2% 이상인 상품 찾아줘"
    )
    output = result.to_dict()

    assert output["route"] == "explore"
    assert output["disposition"] == "limitation"
    assert output["issue_codes"] == ["BOOLEAN_PREDICATE_SCOPE_UNSUPPORTED"]
    assert output["logical_query_plan"] is None
    assert output["frames"][0]["selected_contract"] is None
    predicate = output["frames"][0]["candidate_contract"]["predicate"]
    assert predicate["node_type"] == "all_of"
    assert [child["operator_id"] for child in predicate["children"]] == ["lte", "gte"]
