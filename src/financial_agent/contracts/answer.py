from typing import Literal

from pydantic import model_validator

from .base import ContractModel, Identifier, RuntimeArtifact, Sha256Hex
from .enums import (
    AnswerDisposition,
    BlockType,
    SubtaskImportance,
    VerificationStatus,
)
from .evidence import CheckResult
from .validation import require_unique_ids


class SubtaskCoverage(ContractModel):
    subtask_id: Identifier
    importance: SubtaskImportance
    answered: bool
    reason_code: Identifier | None = None


class RejectedClaim(ContractModel):
    claim_id: Identifier
    reason_code: Identifier


class DispositionReason(ContractModel):
    reason_code: Identifier
    related_claim_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_related_claim_ids(self) -> "DispositionReason":
        require_unique_ids(self.related_claim_ids, label="related claims")
        return self


class RepairAction(ContractModel):
    action_id: Identifier
    action_type: Literal["ledger_rebuild", "llm_repair"]
    target_id: Identifier


class VerificationReport(RuntimeArtifact):
    verification_report_id: Identifier
    verification_status: VerificationStatus
    recommended_answer_disposition: AnswerDisposition | None
    claim_checks: tuple[CheckResult, ...]
    calculation_checks: tuple[CheckResult, ...]
    subtask_coverage: tuple[SubtaskCoverage, ...]
    releaseable_claim_ids: tuple[Identifier, ...]
    rejected_claims: tuple[RejectedClaim, ...] = ()
    warnings: tuple[Identifier, ...] = ()
    disposition_reasons: tuple[DispositionReason, ...] = ()
    repair_actions: tuple[RepairAction, ...] = ()

    @model_validator(mode="after")
    def validate_report(self) -> "VerificationReport":
        require_unique_ids(
            (
                *(check.check_id for check in self.claim_checks),
                *(check.check_id for check in self.calculation_checks),
            ),
            label="checks",
        )
        require_unique_ids(
            (coverage.subtask_id for coverage in self.subtask_coverage),
            label="subtask coverage",
        )
        require_unique_ids(self.releaseable_claim_ids, label="releaseable claims")
        require_unique_ids(
            (claim.claim_id for claim in self.rejected_claims),
            label="rejected claims",
        )
        require_unique_ids(self.warnings, label="warnings")
        require_unique_ids(
            (action.action_id for action in self.repair_actions),
            label="repair actions",
        )

        rejected_claim_ids = {claim.claim_id for claim in self.rejected_claims}
        if set(self.releaseable_claim_ids) & rejected_claim_ids:
            raise ValueError("releaseable and rejected claims must not overlap")

        if self.verification_status is VerificationStatus.PASS:
            if self.recommended_answer_disposition is None:
                raise ValueError("passing verification requires an answer disposition")
        elif self.recommended_answer_disposition is not None:
            raise ValueError("failed verification must not have an answer disposition")
        elif self.releaseable_claim_ids:
            raise ValueError("failed verification must not release claims")
        return self


class ClaimSlot(ContractModel):
    slot_id: Identifier
    claim_id: Identifier


class AnswerRow(ContractModel):
    cells: tuple[ClaimSlot, ...]

    @model_validator(mode="after")
    def validate_cells(self) -> "AnswerRow":
        require_unique_ids(
            (cell.slot_id for cell in self.cells),
            label="row slots",
        )
        return self


class AnswerBlock(ContractModel):
    block_id: Identifier
    block_type: BlockType
    template_id: Identifier
    claim_slots: tuple[ClaimSlot, ...] = ()
    columns: tuple[Identifier, ...] = ()
    rows: tuple[AnswerRow, ...] = ()

    @model_validator(mode="after")
    def validate_claim_slots(self) -> "AnswerBlock":
        require_unique_ids(
            (slot.slot_id for slot in self.claim_slots),
            label="block slots",
        )
        return self


class AnswerPlan(RuntimeArtifact):
    verification_report_id: Identifier
    answer_disposition: AnswerDisposition
    renderer_profile_id: Identifier
    blocks: tuple[AnswerBlock, ...]
    source_display: Literal["inline_numbered"] = "inline_numbered"
    plan_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_blocks(self) -> "AnswerPlan":
        require_unique_ids(
            (block.block_id for block in self.blocks),
            label="answer blocks",
        )
        return self


class ClaimBinding(ContractModel):
    output_locator: str
    claim_ids: tuple[Identifier, ...]
    evidence_ids: tuple[Identifier, ...]


class ReleasedAnswer(RuntimeArtifact):
    answer_disposition: AnswerDisposition
    answer_text: str
    retrieved_context_text: str
    think_trace_text: str
    claim_bindings: tuple[ClaimBinding, ...]
    response_hash: Sha256Hex


class EvaluationApiResponse(ContractModel):
    question_id: str
    question: str
    retrieved_context: str
    think_trace: str
    answer: str
