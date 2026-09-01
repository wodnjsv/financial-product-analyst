"""Configuration for one CLOVA Structured Outputs request."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from pydantic import SecretStr

from .errors import MODEL_CONFIGURATION_INVALID, ModelInvocationError


@dataclass(frozen=True, slots=True)
class ClovaResolverConfig:
    api_key: SecretStr = field(repr=False)
    base_url: str
    model_id: str
    max_completion_tokens: int = 4096
    temperature: float = 0.0
    top_p: float = 0.1
    top_k: int = 1
    repetition_penalty: float = 1.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or not self.model_id.strip():
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        if not 0 < self.max_completion_tokens <= 32_768:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        if not 0.0 <= self.temperature <= 1.0:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        if not 0.0 < self.top_p <= 1.0:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        if not 0 <= self.top_k <= 128:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        if not 0.0 < self.repetition_penalty <= 2.0:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)

    @classmethod
    def from_env(cls) -> "ClovaResolverConfig":
        api_key = os.environ.get("FINANCIAL_AGENT_CLOVA_API_KEY")
        base_url = os.environ.get("FINANCIAL_AGENT_CLOVA_BASE_URL")
        model_id = os.environ.get("FINANCIAL_AGENT_INTENT_MODEL_ID")
        if not api_key or not base_url or not model_id:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        return cls(
            api_key=SecretStr(api_key),
            base_url=base_url,
            model_id=model_id,
        )
