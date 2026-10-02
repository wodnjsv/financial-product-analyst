"""Output-contract checks for local search experiments, not production release."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from .local_document_text import document_answer_text


class _Answer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    answer: str
    citations: list[str]
    quotes: list[Any]


class _Quote(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    ref_id: str
    quote: str


def validate_local_search_answer(
    plan_id: str, rows: object, answer: object
) -> tuple[str, ...]:
    """Return rejection codes; an empty tuple means this contract passed only."""
    if plan_id not in ("rank_return", "holding_weight", "document_risk"):
        return ("UNKNOWN_PLAN",)
    document = plan_id == "document_risk"
    if not isinstance(rows, list) or not rows:
        return ("SEARCH_ROWS_INVALID",)
    sources: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            return ("SEARCH_ROWS_INVALID",)
        ref = row.get("ref_id")
        if not isinstance(ref, str) or not re.fullmatch(r"[RHD][1-9][0-9]*", ref):
            return ("SEARCH_ROWS_INVALID",)
        if ref in sources:
            return ("DUPLICATE_SOURCE_REF",)
        if document and (
            not isinstance(row.get("excerpt"), str) or not row["excerpt"].strip()
        ):
            return ("DOCUMENT_EXCERPT_INVALID",)
        sources[ref] = row
    try:
        draft = _Answer.model_validate(answer)
    except ValidationError:
        return ("ANSWER_SCHEMA_INVALID",)

    errors: list[str] = []
    if not draft.answer.strip():
        errors.append("ANSWER_EMPTY")
    if len(draft.citations) != len(set(draft.citations)):
        errors.append("DUPLICATE_CITATION")
    if set(draft.citations) != set(sources):
        errors.append("CITATION_REFS_MISMATCH")
    if not document and set(re.findall(r"\[([RHD][0-9]+)\]", draft.answer)) != set(sources):
        errors.append("INLINE_REFS_MISMATCH")

    # SQL results have no excerpt. Reject quotes before any document access.
    if not document:
        if draft.quotes:
            errors.append("SQL_QUOTES_MUST_BE_EMPTY")
        return tuple(errors)

    # Compare the complete source-owned body, so literal reference-like text
    # inside sources is preserved and arbitrary model prose cannot be released.
    try:
        expected = document_answer_text(rows)
    except ValueError as exc:
        return tuple(dict.fromkeys([*errors, str(exc)]))
    if draft.answer != expected:
        errors.append("DOCUMENT_BODY_UNGROUNDED")

    quoted_refs: set[str] = set()
    for value in draft.quotes:
        try:
            quote = _Quote.model_validate(value)
        except ValidationError:
            errors.append("QUOTE_SCHEMA_INVALID")
            continue
        if quote.ref_id not in sources:
            errors.append("QUOTE_REF_UNKNOWN")
            continue
        if quote.ref_id in quoted_refs:
            errors.append("DUPLICATE_QUOTE_REF")
        quoted_refs.add(quote.ref_id)
        if not quote.quote.strip() or quote.quote not in sources[quote.ref_id]["excerpt"]:
            errors.append("QUOTE_NOT_VERBATIM")
        elif quote.quote != sources[quote.ref_id]["excerpt"]:
            errors.append("QUOTE_NOT_COMPLETE_EXCERPT")
    if quoted_refs != set(sources):
        errors.append("DOCUMENT_QUOTES_INCOMPLETE")
    return tuple(dict.fromkeys(errors))
