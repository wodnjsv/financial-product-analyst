"""Provider-neutral contracts for one bounded structured-output invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class StructuredOutputEnvelope(Protocol):
    system_message: str
    user_message: str
    response_schema: dict[str, object]


@dataclass(frozen=True, slots=True)
class ModelInvocationResult:
    content: str
    usage: Mapping[str, int]
