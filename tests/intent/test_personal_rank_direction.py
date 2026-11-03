from copy import deepcopy
import json

from financial_agent.contracts.request import NamedEntityMention, Segment
from financial_agent.intent.literals import extract_literals
from financial_agent.intent.model import ModelInvocationResult
from financial_agent.intent.normalization import normalize_request
import pytest

from tests.intent.test_literals import normalized_request
from tests.intent.test_personal_intent import Adapter, service


@pytest.mark.asyncio
@pytest.mark.parametrize("cue,direction", [
    ("하위", "asc"), ("낮은", "asc"), ("작은", "asc"), ("오름차순", "asc"),
    ("상위", "desc"), ("높은", "desc"), ("큰", "desc"), ("내림차순", "desc"),
])
async def test_personal_rank_uses_explicit_source_direction(cue, direction):
    question = f"국내 ETF의 1년 수익률 {cue} 10개를 알려줘."
    adapter = Adapter("domestic_etf", "trailing_1y_historical_cumulative_return", entity=False)

    output = (await service(adapter).resolve(question)).to_dict()

    assert output["route"] == "compose"
    contract = output["frames"][0]["selected_contract"]
    assert contract["limit"] == 10
    assert contract["ordering"][0]["direction"] == direction
    assert contract["ordering"][0]["direction_policy_id"] is None
    literal = next(item for item in extract_literals(normalized_request(question))
                   if item.kind == "sort_direction")
    assert literal.original_text == cue
    assert question[literal.start_char:literal.end_char] == cue
    assert {"semantic_input_id": "ordering.0.direction", "source_kind": "exact_lock",
            "source_ref": f"lock-literal-{literal.literal_id}"} in contract["provenance"]
    assert output["logical_query_plan"]["tasks"][0]["operation"]["ordering"][0]["direction"] == direction
    assert adapter.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cue", ["낮은", "작은", "하위"])
async def test_low_fee_direction_remains_ascending(cue):
    output = (await service(Adapter("domestic_etf", "fee_rate", entity=False)).resolve(
        f"국내 ETF 중 총보수가 {cue} 5개를 알려줘."
    )).to_dict()

    assert output["route"] == "compose"
    assert output["frames"][0]["selected_contract"]["ordering"][0]["direction"] == "asc"


@pytest.mark.asyncio
async def test_opposite_source_directions_cannot_choose_a_default():
    output = (await service(Adapter(
        "domestic_etf", "trailing_1y_historical_cumulative_return", entity=False
    )).resolve("국내 ETF의 1년 수익률 상위 하위 10개를 알려줘.")).to_dict()

    assert output["route"] == "abstain"
    assert "EXACT_LITERAL_CONFLICT" in output["issue_codes"]
    assert output["logical_query_plan"] is None


def test_direction_literals_preserve_original_unicode_offsets_and_limits():
    text = "국내 ＥＴＦ의 １년 수익률 하위 １０개를 알려줘."

    literals = extract_literals(normalized_request(text))

    assert [(item.kind, item.original_text, item.canonical_value) for item in literals] == [
        ("period", "１년", "P1Y"), ("sort_direction", "하위", "asc"),
        ("result_limit", "１０개", "10"),
    ]
    assert all(text[item.start_char:item.end_char] == item.original_text for item in literals)


def test_directions_in_entity_names_do_not_become_query_sort_conditions():
    text = "하위10개 ETF의 총보수가 높은 5개를 알려줘."
    context = normalized_request(text).context.model_copy(update={"named_entities": (
        NamedEntityMention(mention_id="entity-1", segment_id="s1", text="하위10개 ETF",
                           expected_entity_types=("FinancialProduct",), start_char=0, end_char=9),
    )})

    literals = extract_literals(normalize_request(context))

    assert [(item.kind, item.canonical_value) for item in literals] == [
        ("sort_direction", "desc"), ("result_limit", "5"),
    ]


def test_opposite_directions_in_distinct_segments_keep_separate_source_ownership():
    context = normalized_request("총보수 상위 5개. 총보수 하위 5개.").context.model_copy(update={
        "segments": (Segment(segment_id="s1", ordinal=0, text="총보수 상위 5개."),
                     Segment(segment_id="s2", ordinal=1, text="총보수 하위 5개.")),
    })

    directions = [item for item in extract_literals(normalize_request(context))
                  if item.kind == "sort_direction"]

    assert [(item.segment_id, item.original_text, item.canonical_value) for item in directions] == [
        ("s1", "상위", "desc"), ("s2", "하위", "asc"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", ["하위10개", "하위 열 종목"])
async def test_bottom_rank_does_not_confuse_direction_and_number(phrase):
    output = (await service(Adapter(
        "domestic_etf", "trailing_1y_historical_cumulative_return", entity=False
    )).resolve(f"국내 ETF의 1년 수익률 {phrase}를 알려줘.")).to_dict()

    contract = output["frames"][0]["selected_contract"]
    assert contract["ordering"][0]["direction"] == "asc"
    assert contract["limit"] == 10


def test_rank_direction_substrings_inside_words_do_not_become_literals():
    literals = extract_literals(normalized_request("하위법령과 상위법령, 작은별과 큰따옴표"))

    assert literals == ()


@pytest.mark.asyncio
async def test_opposite_directions_in_shared_segment_frames_remain_blocked():
    class TwoFrames(Adapter):
        async def invoke(self, envelope, timeout_seconds):
            result = await super().invoke(envelope, timeout_seconds)
            payload = json.loads(result.content)
            view = json.loads(envelope.user_message)["view"]
            payload["frames"][0]["semantic_links"] = [
                {"mention_id": projection["mention_id"], "state": "selected",
                 "semantic_ids": [projection["canonical_semantic_id"]], "reason_code": "explicit"}
                for projection in view["exact_lock_projections"] if projection["role"] == "field"
            ]
            payload["frames"].append(deepcopy(payload["frames"][0]))
            return ModelInvocationResult(content=json.dumps(payload), usage=result.usage)

    output = (await service(TwoFrames(
        "domestic_etf", "trailing_1y_historical_cumulative_return", entity=False
    )).resolve("국내 ETF의 1년 수익률 상위 5개와 하위 5개를 알려줘.")).to_dict()

    assert len(output["frames"]) == 2
    assert output["route"] == "abstain"
    assert "EXACT_LITERAL_CONFLICT" in output["issue_codes"]
    assert output["logical_query_plan"] is None
