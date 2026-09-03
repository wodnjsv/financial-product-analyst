from __future__ import annotations

import pytest
from pydantic import ValidationError

from financial_agent.intent.hybrid_proposal import (
    FrameSemanticCoverageV3,
    ProposedIntentFrameV3,
    ProposedSemanticLinkV3,
)
from financial_agent.intent.proposal import ProposedAxisChoice


def _choice() -> ProposedAxisChoice:
    return ProposedAxisChoice(
        state="selected",
        selected_ids=("lookup",),
        evidence_ids=(),
        reason_code="explicit",
    )


def _frame(**changes: object) -> ProposedIntentFrameV3:
    values: dict[str, object] = {
        "segment_ids": ("s1",),
        "action_choice": _choice(),
        "product_family_choice": _choice(),
        "entity_type_ids": (),
        "semantic_links": (),
        "unmapped_mention_ids": (),
        "semantic_coverage": FrameSemanticCoverageV3(state="covered", reason="none"),
        "entity_hints": (),
        "produced_result_hints": (),
    }
    values.update(changes)
    return ProposedIntentFrameV3(**values)


def test_selected_semantic_link_requires_one_catalog_id() -> None:
    """Catches accepting a selected mention linked to multiple meanings."""
    with pytest.raises(ValidationError):
        ProposedSemanticLinkV3(
            mention_id="mention-1",
            state="selected",
            semantic_ids=("fee_rate", "aum"),
            reason_code="explicit",
        )


def test_ambiguous_semantic_link_requires_multiple_catalog_ids() -> None:
    """Catches accepting a false ambiguity that names only one meaning."""
    with pytest.raises(ValidationError):
        ProposedSemanticLinkV3(
            mention_id="mention-1",
            state="ambiguous",
            semantic_ids=("fee_rate",),
            reason_code="ambiguous",
        )


def test_ambiguous_semantic_link_rejects_repeated_catalog_id() -> None:
    """Catches duplicate IDs satisfying the ambiguous-link count accidentally."""
    with pytest.raises(ValidationError):
        ProposedSemanticLinkV3(
            mention_id="mention-1",
            state="ambiguous",
            semantic_ids=("fee_rate", "fee_rate"),
            reason_code="ambiguous",
        )


def test_frame_rejects_mention_that_is_linked_and_unmapped() -> None:
    """Catches one source mention being represented as both grounded and OOD."""
    with pytest.raises(ValidationError):
        _frame(
            semantic_links=(
                ProposedSemanticLinkV3(
                    mention_id="mention-1",
                    state="selected",
                    semantic_ids=("fee_rate",),
                    reason_code="explicit",
                ),
            ),
            unmapped_mention_ids=("mention-1",),
        )


def test_covered_frame_requires_none_reason_and_no_unmapped_mentions() -> None:
    """Catches a covered frame retaining an OOD reason or mention."""
    with pytest.raises(ValidationError):
        _frame(
            unmapped_mention_ids=("mention-1",),
            semantic_coverage=FrameSemanticCoverageV3(
                state="covered", reason="none"
            ),
        )


def test_covered_frame_rejects_non_none_reason() -> None:
    """Catches a covered frame being marked with an unresolved semantic reason."""
    with pytest.raises(ValidationError):
        _frame(
            semantic_coverage=FrameSemanticCoverageV3(
                state="covered", reason="lexical_ood"
            )
        )


def test_uncovered_frame_requires_reason_and_unmapped_mention() -> None:
    """Catches an uncovered frame that omits the source evidence for the gap."""
    with pytest.raises(ValidationError):
        _frame(
            semantic_coverage=FrameSemanticCoverageV3(
                state="partial", reason="lexical_ood"
            ),
        )
