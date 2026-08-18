import hashlib
import json
import unicodedata
from collections.abc import Collection, Mapping
from enum import Enum
from typing import Any

from pydantic import BaseModel


def normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question)
    return " ".join(normalized.split())


def _json_native(value: object) -> object:
    if isinstance(value, Enum):
        raise TypeError("schema-less mappings cannot contain Enum values")
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [_json_native(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical mapping keys must be strings")
        return {key: _json_native(item) for key, item in value.items()}
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(
    value: BaseModel | Mapping[str, Any],
    *,
    exclude_fields: Collection[str] = (),
) -> bytes:
    serialized = (
        value.model_dump(mode="json", exclude=set(exclude_fields))
        if isinstance(value, BaseModel)
        else dict(value)
    )
    payload = _json_native(serialized)
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
