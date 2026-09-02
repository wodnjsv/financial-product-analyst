"""Exceptional offered-ID-only HCX judge for complete query contracts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Iterable

from financial_agent.contracts.base import ContractModel, Identifier

from .clova import ModelInvocationResult
from .errors import MODEL_SCHEMA_INVALID, MODEL_TIMEOUT, ModelInvocationError
from .query_contract_solver import QueryContractCandidate
from .query_contracts import ContractReadiness, ContractReadinessRecordV2
from .resolution import ValidatedIntentFrameV2
from .view import ResolverView


JUDGE_PROMPT_VERSION = "query-contract-judge-ko-v1"
JUDGE_SCHEMA_VERSION = "query-contract-judge-response-v1"
_SYSTEM_MESSAGE = (
    "You are a bounded semantic query-contract judge. Select exactly one offered "
    "candidate_id that best matches the Korean question and frame evidence. "
    "Return only the JSON object required by the response schema. Never add, alter, "
    "or explain an identifier and never produce executable query text."
)


class QueryContractJudgeResponse(ContractModel):
    candidate_id: Identifier


@dataclass(frozen=True, slots=True)
class QueryContractJudgePromptEnvelope:
    system_message: str
    user_message: str
    response_schema: dict[str, object]


class QueryContractJudgeResult(ContractModel):
    candidate_id: Identifier | None = None
    contract_readiness: ContractReadinessRecordV2
    usage: dict[str, int]


def build_query_contract_judge_envelope(
    *,
    question: str,
    frame: ValidatedIntentFrameV2,
    view: ResolverView,
    candidates: tuple[QueryContractCandidate, ...],
) -> QueryContractJudgePromptEnvelope:
    """Expose only evidence-bearing semantic summaries and offered IDs."""

    if len(candidates) < 2:
        raise ValueError("JUDGE_REQUIRES_AMBIGUOUS_CANDIDATES")
    offered_ids = tuple(item.candidate_id for item in candidates)
    if len(set(offered_ids)) != len(offered_ids):
        raise ValueError("DUPLICATE_CANDIDATE_ID")
    return QueryContractJudgePromptEnvelope(
        system_message=_SYSTEM_MESSAGE,
        user_message=json.dumps(
            {
                "prompt_version": JUDGE_PROMPT_VERSION,
                "question": question,
                "frame": {
                    "frame_id": frame.frame_id,
                    "segment_ids": list(frame.segment_ids),
                    "evidence_span_ids": list(frame.evidence_span_ids),
                    "action_label": frame.action_choice.selected_ids[0].value,
                    "family_labels": [item.value for item in frame.product_family_choice.selected_ids],
                    "evidence": [
                        {
                            "segment_id": item.segment_id,
                            "start_char": item.start_char,
                            "end_char": item.end_char,
                            "text": item.text,
                        }
                        for item in sorted(
                            (
                                evidence
                                for evidence in view.evidence_candidates
                                if evidence.segment_id in frame.segment_ids
                            ),
                            key=lambda evidence: (
                                frame.segment_ids.index(evidence.segment_id),
                                evidence.start_char,
                                evidence.end_char,
                                evidence.evidence_id,
                            ),
                        )
                    ],
                },
                "candidates": [
                    {
                        "candidate_id": item.candidate_id,
                        "semantic_summary": _semantic_summary(item),
                    }
                    for item in candidates
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        response_schema={
            "title": JUDGE_SCHEMA_VERSION,
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "enum": list(offered_ids)}
            },
            "required": ["candidate_id"],
            "additionalProperties": False,
        },
    )


class QueryContractJudge:
    """Invoke the existing structured-output transport at most once."""

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def select_offered_id(
        self,
        *,
        question: str,
        frame: ValidatedIntentFrameV2,
        view: ResolverView,
        candidates: tuple[QueryContractCandidate, ...],
        timeout_seconds: float,
        repair_used: bool = False,
    ) -> QueryContractJudgeResult:
        if repair_used:
            return _result(
                None,
                ContractReadiness.AMBIGUOUS,
                "EXTRA_MODEL_ALLOWANCE_ALREADY_USED",
            )
        if not candidates:
            return _result(None, ContractReadiness.BLOCKED, "NO_COMPLETE_CANDIDATE")
        if len(candidates) == 1:
            return _result(candidates[0].candidate_id, ContractReadiness.COMPLETE)
        if timeout_seconds <= 0:
            return _result(None, ContractReadiness.AMBIGUOUS, MODEL_TIMEOUT)

        envelope = build_query_contract_judge_envelope(
            question=question,
            frame=frame,
            view=view,
            candidates=candidates,
        )
        try:
            invocation = await self._adapter.invoke(envelope, timeout_seconds)
        except ModelInvocationError as error:
            return _result(None, ContractReadiness.AMBIGUOUS, error.code)

        offered = {item.candidate_id for item in candidates}
        try:
            payload = _strict_json_loads(invocation.content)
            response = QueryContractJudgeResponse.model_validate(payload)
        except (TypeError, ValueError):
            return _result(
                None,
                ContractReadiness.AMBIGUOUS,
                "JUDGE_SCHEMA_INVALID",
                invocation,
            )
        if response.candidate_id not in offered:
            return _result(
                None,
                ContractReadiness.AMBIGUOUS,
                "JUDGE_UNKNOWN_CANDIDATE_ID",
                invocation,
            )
        return _result(
            response.candidate_id,
            ContractReadiness.COMPLETE,
            invocation=invocation,
        )


def _semantic_summary(candidate: QueryContractCandidate) -> dict[str, object]:
    contract = candidate.contract
    summary: dict[str, object] = {
        "action": contract.action_id.value,
        "families": [item.value for item in contract.scope.product_family_ids],
        "entity_refs": list(contract.scope.entity_refs),
        "prior_result": contract.scope.prior_result_binding,
        "qualifiers": contract.qualifiers.model_dump(mode="json"),
        "result_shape": contract.result_shape.value,
    }
    for component in (
        "projections",
        "predicate",
        "ordering",
        "limit",
        "limit_policy_id",
        "comparison",
        "aggregation",
        "calculation",
        "similarity",
        "explanation",
    ):
        if hasattr(contract, component):
            value = getattr(contract, component)
            if isinstance(value, ContractModel):
                value = value.model_dump(mode="json")
            elif isinstance(value, tuple):
                value = [
                    item.model_dump(mode="json") if isinstance(item, ContractModel) else item
                    for item in value
                ]
            summary[component] = value
    return summary


def _result(
    candidate_id: str | None,
    readiness: ContractReadiness,
    reason_code: str | None = None,
    invocation: ModelInvocationResult | None = None,
) -> QueryContractJudgeResult:
    return QueryContractJudgeResult(
        candidate_id=candidate_id,
        contract_readiness=ContractReadinessRecordV2(
            readiness=readiness,
            reason_codes=(reason_code,) if reason_code else (),
        ),
        usage=dict(invocation.usage) if invocation else {},
    )


def _strict_json_loads(payload: str) -> object:
    return json.loads(payload, object_pairs_hook=_reject_duplicate_keys)


def _reject_duplicate_keys(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(MODEL_SCHEMA_INVALID)
        result[key] = value
    return result
