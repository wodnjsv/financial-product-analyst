from copy import deepcopy

import pytest
from pydantic import ValidationError

from financial_agent.contracts import (
    AnswerBlock,
    AnswerPlan,
    AnswerRow,
    ClaimSlot,
    EvaluationApiResponse,
    ReleasedAnswer,
    VerificationReport,
    VerificationStatus,
)
from financial_agent.contracts.enums import AnswerDisposition


def test_verification_report_preserves_verified_release_set(load_fixture) -> None:
    report = VerificationReport.model_validate(load_fixture("verification_report.json"))

    assert report.verification_status.value == "pass"
    assert report.recommended_answer_disposition is AnswerDisposition.ANSWER
    assert report.releaseable_claim_ids == ("claim-rank-1",)
    assert isinstance(report.claim_checks, tuple)


def test_pass_can_recommend_limitation(load_fixture) -> None:
    payload = load_fixture("verification_report.json") | {
        "verification_status": "pass",
        "recommended_answer_disposition": "limitation",
        "releaseable_claim_ids": ["claim-limit-1"],
    }
    report = VerificationReport.model_validate(payload)
    assert report.recommended_answer_disposition is AnswerDisposition.LIMITATION


def test_fail_with_no_disposition_or_releaseable_claims_is_valid(load_fixture) -> None:
    payload = load_fixture("verification_report.json") | {
        "verification_status": "fail",
        "recommended_answer_disposition": None,
        "releaseable_claim_ids": [],
    }

    report = VerificationReport.model_validate(payload)

    assert report.verification_status is VerificationStatus.FAIL
    assert report.recommended_answer_disposition is None
    assert report.releaseable_claim_ids == ()


@pytest.mark.parametrize(
    "payload_update",
    [
        {
            "verification_status": "pass",
            "recommended_answer_disposition": None,
        },
        {
            "verification_status": "fail",
            "recommended_answer_disposition": "answer",
            "releaseable_claim_ids": [],
        },
        {
            "verification_status": "fail",
            "recommended_answer_disposition": None,
            "releaseable_claim_ids": ["claim-rank-1"],
        },
    ],
)
def test_verification_state_axes_reject_inconsistent_combinations(
    load_fixture, payload_update: dict[str, object]
) -> None:
    payload = load_fixture("verification_report.json") | payload_update

    with pytest.raises(ValidationError):
        VerificationReport.model_validate(payload)


def test_releaseable_and_rejected_claims_must_be_disjoint(load_fixture) -> None:
    payload = load_fixture("verification_report.json")
    payload["rejected_claims"] = [
        {"claim_id": "claim-rank-1", "reason_code": "SOURCE_INVALID"}
    ]
    with pytest.raises(ValidationError):
        VerificationReport.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["claim_checks"].append(
            deepcopy(payload["claim_checks"][0])
        ),
        lambda payload: payload["calculation_checks"].append(
            deepcopy(payload["calculation_checks"][0])
        ),
        lambda payload: payload["calculation_checks"][0].update(
            check_id=payload["claim_checks"][0]["check_id"]
        ),
        lambda payload: payload["subtask_coverage"].append(
            deepcopy(payload["subtask_coverage"][0])
        ),
        lambda payload: payload.update(
            releaseable_claim_ids=["claim-rank-1", "claim-rank-1"]
        ),
        lambda payload: payload.update(
            rejected_claims=[
                {"claim_id": "claim-rejected-1", "reason_code": "SOURCE_INVALID"},
                {"claim_id": "claim-rejected-1", "reason_code": "CUTOFF_INVALID"},
            ]
        ),
        lambda payload: payload.update(warnings=["warning-1", "warning-1"]),
        lambda payload: payload.update(
            disposition_reasons=[
                {
                    "reason_code": "reason-1",
                    "related_claim_ids": ["claim-rank-1", "claim-rank-1"],
                }
            ]
        ),
        lambda payload: payload.update(
            repair_actions=[
                {
                    "action_id": "repair-1",
                    "action_type": "ledger_rebuild",
                    "target_id": "bundle-syn-001",
                },
                {
                    "action_id": "repair-1",
                    "action_type": "llm_repair",
                    "target_id": "plan-syn-001",
                },
            ]
        ),
    ],
)
def test_verification_report_rejects_duplicate_ids(load_fixture, mutation) -> None:
    payload = load_fixture("verification_report.json")
    mutation(payload)

    with pytest.raises(ValidationError):
        VerificationReport.model_validate(payload)


def test_answer_plan_contains_ids_but_no_factual_content_fields(load_fixture) -> None:
    plan = AnswerPlan.model_validate(load_fixture("answer_plan.json"))
    schema = AnswerPlan.model_json_schema()
    property_names: set[str] = set()

    def collect_property_names(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                property_names.update(properties)
            for value in node.values():
                collect_property_names(value)
        elif isinstance(node, list):
            for value in node:
                collect_property_names(value)

    collect_property_names(schema)

    assert plan.blocks[0].template_id == "ranking.intro.v1"
    assert property_names.isdisjoint(
        {
            "text",
            "title",
            "value",
            "product_name_value",
            "source_name",
            "rendered_value",
            "markdown",
            "html",
        }
    )


def test_answer_plan_exposes_exact_approved_structural_fields() -> None:
    assert set(AnswerPlan.model_fields) == {
        "schema_version",
        "request_key",
        "run_id",
        "dataset_version",
        "cutoff_date",
        "producer",
        "created_at",
        "verification_report_id",
        "answer_disposition",
        "renderer_profile_id",
        "blocks",
        "source_display",
        "plan_hash",
    }
    assert set(ClaimSlot.model_fields) == {"slot_id", "claim_id"}
    assert set(AnswerRow.model_fields) == {"cells"}
    assert set(AnswerBlock.model_fields) == {
        "block_id",
        "block_type",
        "template_id",
        "claim_slots",
        "columns",
        "rows",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["blocks"].append(deepcopy(payload["blocks"][0])),
        lambda payload: payload["blocks"][0]["claim_slots"].append(
            deepcopy(payload["blocks"][0]["claim_slots"][0])
        ),
        lambda payload: payload["blocks"][1]["rows"][0]["cells"].append(
            deepcopy(payload["blocks"][1]["rows"][0]["cells"][0])
        ),
    ],
)
def test_answer_plan_rejects_duplicate_block_or_slot_ids(
    load_fixture, mutation
) -> None:
    payload = load_fixture("answer_plan.json")
    mutation(payload)

    with pytest.raises(ValidationError):
        AnswerPlan.model_validate(payload)


def test_released_answer_preserves_exact_rendered_strings_and_bindings() -> None:
    released = ReleasedAnswer(
        schema_version="1.0",
        request_key=(
            "5fb658a65798ff794b8f3ac0414da936e"
            "cd806469109317e2a27c11e513d78b4"
        ),
        run_id="run-syn-001",
        dataset_version="2026-07-11-v1",
        cutoff_date="2026-07-11",
        producer="renderer",
        created_at="2026-08-17T00:00:00Z",
        answer_disposition="answer",
        answer_text="합성 ETF의 AUM 순위는 1위입니다. [1]",
        retrieved_context_text="[SOURCE-1] 합성 ETF AUM 근거",
        think_trace_text="[의도] AUM 순위 조회 및 검증",
        claim_bindings=(
            {
                "output_locator": "answer:block-summary:slot-ranking",
                "claim_ids": ("claim-rank-1",),
                "evidence_ids": ("evidence-aum-1",),
            },
        ),
        response_hash="1" * 64,
    )

    assert released.answer_text == "합성 ETF의 AUM 순위는 1위입니다. [1]"
    assert released.retrieved_context_text == "[SOURCE-1] 합성 ETF AUM 근거"
    assert released.think_trace_text == "[의도] AUM 순위 조회 및 검증"
    assert released.claim_bindings[0].claim_ids == ("claim-rank-1",)
    assert released.claim_bindings[0].evidence_ids == ("evidence-aum-1",)
    assert released.response_hash == "1" * 64


def test_api_response_has_exactly_five_string_fields() -> None:
    response = EvaluationApiResponse(
        question_id="Q-001",
        question="합성 질문",
        retrieved_context="[SOURCE-1] 합성 근거",
        think_trace="[의도] 합성 조회",
        answer="합성 답변",
    )
    assert set(response.model_dump()) == {
        "question_id",
        "question",
        "retrieved_context",
        "think_trace",
        "answer",
    }
    assert all(isinstance(value, str) for value in response.model_dump().values())


def test_api_response_rejects_missing_or_extra_fields() -> None:
    valid = {
        "question_id": "Q-001",
        "question": "합성 질문",
        "retrieved_context": "[SOURCE-1] 합성 근거",
        "think_trace": "[의도] 합성 조회",
        "answer": "합성 답변",
    }

    with pytest.raises(ValidationError):
        EvaluationApiResponse.model_validate(valid | {"status": "ok"})
    with pytest.raises(ValidationError):
        EvaluationApiResponse.model_validate(
            {key: value for key, value in valid.items() if key != "answer"}
        )
