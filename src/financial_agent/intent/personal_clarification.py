"""Source-grounded scope checks and clarification text for personal requests."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .types import ChoiceState, EntitySemanticRole

if TYPE_CHECKING:
    from financial_agent.contracts.request import RequestContext
    from .personal import PersonalIntentResult
    from .service import QueryContractResolutionAttemptV3


def ambiguous_product_family_frames(
    attempt: QueryContractResolutionAttemptV3,
) -> tuple[str, ...]:
    """Require source authority before accepting the model's listing family.

    Exact listing-family phrases and exact subject-product identities resolve
    this ambiguity. This does not infer a family from investment geography.
    """
    view = attempt.view
    if view is None:
        return ()
    mentions = {item.mention_id: item for item in view.mention_spans.items}
    entities = {item.entity_id: item for group in view.entity_candidates for item in group.items}
    hints = {item.entity_hint_id: item for item in attempt.resolution.entity_hints}
    groups = {group.frame_id: group for group in attempt.candidates.frames}
    accepted_families: dict[str, set[str]] = {}
    blocked = []
    for frame in attempt.resolution.canonical_frames:
        selected = {item.value for item in frame.product_family_choice.selected_ids}
        explicit = {item.canonical_semantic_id for item in view.exact_lock_projections
                    if item.role == "product_family"
                    and mentions[item.mention_id].segment_id in frame.segment_ids}
        subjects = {entities[hints[hint_id].selected_candidate_ids[0]].product_family
                    for hint_id in frame.entity_hint_ids
                    if hints[hint_id].semantic_role is EntitySemanticRole.FRAME_SUBJECT
                    and len(hints[hint_id].selected_candidate_ids) == 1
                    and entities[hints[hint_id].selected_candidate_ids[0]].match_kind
                    in {"exact_name", "exact_alias", "exact_identifier"}}
        candidates = groups[frame.frame_id].complete_candidates
        inherited = accepted_families.get(candidates[0].contract.scope.prior_result_binding, set()) \
                    if len(candidates) == 1 else set()
        if selected and (selected <= explicit or selected <= subjects or selected <= inherited):
            accepted_families[frame.frame_id] = selected
        else:
            blocked.append(frame.frame_id)
    return tuple(blocked)


def unsupported_boolean_frames(
    context: RequestContext, attempt: QueryContractResolutionAttemptV3,
) -> tuple[str, ...]:
    """Do not execute explicit source disjunctions as conjunctive predicates."""
    texts = {}
    for segment in context.segments:
        text = list(segment.text)
        for mention in context.named_entities:
            if mention.segment_id == segment.segment_id and mention.start_char is not None:
                text[mention.start_char:mention.end_char] = " " * (mention.end_char - mention.start_char)
        texts[segment.segment_id] = "".join(text)
    return tuple(frame.frame_id for frame in attempt.resolution.canonical_frames
                 if any(re.search(r"또는|혹은|거나|아니면|(?<!\w)OR(?!\w)", texts[segment_id], re.IGNORECASE)
                        for segment_id in frame.segment_ids))


def personal_clarifications(result: PersonalIntentResult) -> tuple[dict[str, str], ...]:
    """Describe unresolved validated inputs without choosing a replacement query."""
    if result.compilation and result.compilation.logical_query_plan:
        return ()
    resolution = result.attempt.resolution
    codes = set(result.issue_codes) | {issue.code for issue in resolution.issues}
    rejections = result.attempt.candidates.rejections
    messages: dict[str, str] = {}
    if {"REFERENCE_UNRESOLVED", "REFERENCE_AMBIGUOUS"} & codes:
        messages["FOLLOWUP_SCOPE_REQUIRED"] = (
            "이전 대화 결과를 자동으로 이어받지 않습니다. 대상 상품명·상품군과 유지할 조건을 이번 질문에 다시 적어 주세요."
        )
    if "AMBIGUOUS_PRODUCT_FAMILY" in codes or any(
        frame.product_family_choice.state is ChoiceState.AMBIGUOUS
        for frame in resolution.canonical_frames
    ):
        messages["AMBIGUOUS_PRODUCT_FAMILY"] = (
            "상품군을 확정할 수 없습니다. 국내 상장 ETF인지 해외 상장 ETF인지 등 조회할 상품군을 명시해 주세요."
        )
    grounded = {hint.mention_id[0] for hint in resolution.entity_hints
                if hint.mention_id and len(hint.selected_candidate_ids) == 1}
    if "ENTITY_SCOPE_UNRESOLVED" in codes or any(
        mention.mention_id not in grounded for mention in result.context.named_entities
    ):
        messages["ENTITY_NAME_UNRESOLVED"] = (
            "상품·종목·운용사 이름을 확정할 수 없습니다. 오타를 확인하고 정확한 이름이나 식별자를 적어 주세요."
        )
    qualifier_labels = {"period": "기간", "as_of": "기준일", "currency": "통화", "unit": "단위"}
    for rejection in rejections:
        if rejection.reason_code not in {"REQUIRED_QUALIFIER_MISSING", "REQUIRED_QUALIFIER_AMBIGUOUS"}:
            continue
        qualifier = rejection.role_id.rsplit(".qualifier.", 1)[-1]
        if qualifier not in qualifier_labels:
            continue
        kind = "AMBIGUOUS" if rejection.reason_code.endswith("AMBIGUOUS") else "MISSING"
        code = f"{qualifier.upper()}_{kind}"
        messages[code] = f"요청한 지표의 {qualifier_labels[qualifier]} 정보가 확정되지 않았습니다. 원하는 {qualifier_labels[qualifier]} 정보를 명시해 주세요."
    if "REQUESTED_FIELD_ROLE_MISSING" in codes or any(
        rejection.reason_code == "REQUESTED_FIELD_ROLE_MISSING" for rejection in rejections
    ):
        messages["REQUEST_REQUIREMENTS_INCOMPLETE"] = (
            "요청한 지표·조건을 모두 담은 조회 계획을 만들지 못했습니다. 필요한 지표와 각 조건을 명확히 적어 주세요."
        )
    if not messages and {"SEMANTIC_CONCEPT_UNMAPPED", "SEMANTIC_CRITICAL_SLOT_MISSING",
                         "AMBIGUITY_UNRESOLVED", "QUERY_CONTRACT_NOT_COMPLETE"} & codes:
        messages["REQUEST_MEANING_UNRESOLVED"] = (
            "질문의 뜻을 확정할 수 없습니다. 상품명(오타 포함), 상품군, 지표와 조건을 확인해 다시 적어 주세요."
        )
    return tuple({"code": code, "message": message} for code, message in messages.items())
