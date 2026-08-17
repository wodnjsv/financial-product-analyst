import hashlib
import json
import unicodedata
from collections.abc import Collection, Mapping
from typing import Any

from pydantic import BaseModel


def normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question)
    return " ".join(normalized.split())


def canonical_json_bytes(
    value: BaseModel | Mapping[str, Any],
    *,
    exclude_fields: Collection[str] = (),
) -> bytes:
    payload = (
        value.model_dump(mode="json", exclude=set(exclude_fields))
        if isinstance(value, BaseModel)
        else dict(value)
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(
    value: BaseModel | Mapping[str, Any],
    *,
    exclude_fields: Collection[str] = (),
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(value, exclude_fields=exclude_fields)
    ).hexdigest()


def build_request_key(
    question_id: str,
    question: str,
    dataset_version: str,
    schema_version: str,
) -> str:
    payload = {
        "dataset_version": dataset_version,
        "question": normalize_question(question),
        "question_id": question_id,
        "schema_version": schema_version,
    }
    return canonical_sha256(payload)
