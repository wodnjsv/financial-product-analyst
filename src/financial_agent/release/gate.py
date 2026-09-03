"""Server-owned AnswerPlan registry and deterministic Claim Gate."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from financial_agent.contracts import (
    AnswerBlock,
    AnswerDisposition,
    AnswerPlan,
    BlockType,
    ClaimSlot,
    VerificationReport,
    VerificationStatus,
)
from financial_agent.contracts.canonical import canonical_sha256

from .claims import ClaimAssembly


_TEMPLATES: Mapping[str, tuple[BlockType, bool]] = MappingProxyType(
    {
        "fact-list.v1": (BlockType.FACT_LIST, True),
        "limitation.v1": (BlockType.LIMITATION, False),
        "abstention.v1": (BlockType.ABSTENTION, False),
    }
)
_RENDERER_PROFILES = frozenset({"competition-ko.v1"})


@dataclass(frozen=True, slots=True)
class ClaimGateDecision:
    plan: AnswerPlan
    report: VerificationReport
    authorized_claim_ids: tuple[str, ...]
    decision_hash: str


def build_default_answer_plan(report: VerificationReport) -> AnswerPlan:
    if report.verification_status is not VerificationStatus.PASS:
        raise ValueError("ANSWER_PLAN_REQUIRES_PASSING_REPORT")
    disposition = report.recommended_answer_disposition
    assert disposition is not None
    if report.releaseable_claim_ids:
        block = AnswerBlock(
            block_id="block-1",
            block_type=BlockType.FACT_LIST,
            template_id="fact-list.v1",
            claim_slots=tuple(
                ClaimSlot(slot_id=f"claim-{index}", claim_id=claim_id)
                for index, claim_id in enumerate(
                    report.releaseable_claim_ids, start=1
                )
            ),
        )
    elif disposition is AnswerDisposition.ABSTAIN:
        block = AnswerBlock(
            block_id="block-1",
            block_type=BlockType.ABSTENTION,
            template_id="abstention.v1",
        )
    else:
        block = AnswerBlock(
            block_id="block-1",
            block_type=BlockType.LIMITATION,
            template_id="limitation.v1",
        )
    draft = AnswerPlan(
        request_key=report.request_key,
        run_id=report.run_id,
        dataset_version=report.dataset_version,
        cutoff_date=report.cutoff_date,
        producer="default-answer-planner.v1",
        created_at=report.created_at,
        verification_report_id=report.verification_report_id,
        answer_disposition=disposition,
        renderer_profile_id="competition-ko.v1",
        blocks=(block,),
        plan_hash="0" * 64,
    )
    return draft.model_copy(
        update={
            "plan_hash": canonical_sha256(draft, exclude_fields=("plan_hash",))
        }
    )


class ClaimGate:
    def authorize(
        self,
        plan: AnswerPlan,
        report: VerificationReport,
        assembly: ClaimAssembly,
    ) -> ClaimGateDecision:
        if report.verification_status is not VerificationStatus.PASS:
            raise ValueError("CLAIM_GATE_VERIFICATION_NOT_PASSING")
        expected_report_id = "verification-report-" + canonical_sha256(
            report, exclude_fields=("verification_report_id",)
        )[:24]
        if report.verification_report_id != expected_report_id:
            raise ValueError("CLAIM_GATE_REPORT_HASH_MISMATCH")
        if plan.plan_hash != canonical_sha256(plan, exclude_fields=("plan_hash",)):
            raise ValueError("CLAIM_GATE_PLAN_HASH_MISMATCH")
        if (
            plan.request_key != report.request_key
            or plan.run_id != report.run_id
            or plan.dataset_version != report.dataset_version
            or plan.cutoff_date != report.cutoff_date
            or plan.created_at != report.created_at
            or assembly.bundle.run_id != report.run_id
            or assembly.bundle.dataset_version != report.dataset_version
        ):
            raise ValueError("CLAIM_GATE_PIN_MISMATCH")
        if plan.verification_report_id != report.verification_report_id:
            raise ValueError("CLAIM_GATE_REPORT_MISMATCH")
        if plan.answer_disposition is not report.recommended_answer_disposition:
            raise ValueError("CLAIM_GATE_DISPOSITION_MISMATCH")
        if plan.renderer_profile_id not in _RENDERER_PROFILES:
            raise ValueError("CLAIM_GATE_RENDERER_PROFILE_NOT_REGISTERED")
        if len(plan.blocks) != 1:
            raise ValueError("CLAIM_GATE_PLAN_SHAPE_INCOMPATIBLE")
        expected_block_type = (
            BlockType.FACT_LIST
            if report.releaseable_claim_ids
            else (
                BlockType.ABSTENTION
                if plan.answer_disposition is AnswerDisposition.ABSTAIN
                else BlockType.LIMITATION
            )
        )
        if plan.blocks[0].block_type is not expected_block_type:
            raise ValueError("CLAIM_GATE_PLAN_SHAPE_INCOMPATIBLE")

        claim_ids: list[str] = []
        for block in plan.blocks:
            registered = _TEMPLATES.get(block.template_id)
            if registered is None:
                raise ValueError("CLAIM_GATE_TEMPLATE_NOT_REGISTERED")
            block_type, requires_claims = registered
            if block.block_type is not block_type or block.columns or block.rows:
                raise ValueError("CLAIM_GATE_TEMPLATE_INCOMPATIBLE")
            if requires_claims != bool(block.claim_slots):
                raise ValueError("CLAIM_GATE_TEMPLATE_INCOMPATIBLE")
            for slot in block.claim_slots:
                if not slot.slot_id.startswith("claim-"):
                    raise ValueError("CLAIM_GATE_SLOT_NOT_REGISTERED")
                claim_ids.append(slot.claim_id)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("CLAIM_GATE_DUPLICATE_CLAIM")
        releaseable = tuple(report.releaseable_claim_ids)
        if any(claim_id not in releaseable for claim_id in claim_ids):
            raise ValueError("CLAIM_GATE_CLAIM_NOT_RELEASEABLE")
        if set(claim_ids) != set(releaseable):
            raise ValueError("CLAIM_GATE_RELEASEABLE_CLAIM_OMITTED")
        assembly_claim_ids = {item.claim_id for item in assembly.claims}
        if not set(claim_ids) <= assembly_claim_ids:
            raise ValueError("CLAIM_GATE_CLAIM_NOT_IN_LEDGER")

        decision_seed = {
            "plan_hash": plan.plan_hash,
            "verification_report_id": report.verification_report_id,
            "authorized_claim_ids": claim_ids,
            "registry": "claim-gate-registry.v1",
        }
        return ClaimGateDecision(
            plan=plan,
            report=report,
            authorized_claim_ids=tuple(claim_ids),
            decision_hash=canonical_sha256(decision_seed),
        )
