"""Configuration for the approved NVIDIA hosted intent provider."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from pydantic import SecretStr

from .errors import MODEL_CONFIGURATION_INVALID, ModelInvocationError


@dataclass(frozen=True, slots=True)
class NvidiaResolverConfig:
    api_key: SecretStr = field(repr=False)
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model_id: str = "z-ai/glm-5.3-flash"
    max_completion_tokens: int = 4096
    temperature: float = 0.0

    def __post_init__(self) -> None:
        try:
            parsed = urlparse(self.base_url)
            destination_valid = (
                parsed.scheme == "https"
                and parsed.hostname == "integrate.api.nvidia.com"
                and parsed.port in (None, 443)
                and parsed.username is None
                and parsed.password is None
                and parsed.path.rstrip("/") == "/v1"
                and not parsed.query
                and not parsed.fragment
            )
        except (TypeError, ValueError):
            destination_valid = False
        if not destination_valid:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        if (
            not isinstance(self.api_key, SecretStr)
            or not self.api_key.get_secret_value().strip()
            or not self.api_key.get_secret_value().isascii()
            or not self.api_key.get_secret_value().isprintable()
            or any(character.isspace() for character in self.api_key.get_secret_value())
            or not isinstance(self.model_id, str)
            or len(self.model_id) > 128
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", self.model_id) is None
            or type(self.max_completion_tokens) is not int
            or not 0 < self.max_completion_tokens <= 32_768
            or type(self.temperature) not in (int, float)
            or not math.isfinite(self.temperature)
            or not 0.0 <= self.temperature <= 1.0
        ):
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)

    @classmethod
    def from_env(cls) -> "NvidiaResolverConfig":
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key:
            raise ModelInvocationError(MODEL_CONFIGURATION_INVALID)
        return cls(
            api_key=SecretStr(api_key),
            model_id=os.environ.get(
                "FINANCIAL_AGENT_INTENT_MODEL_ID", "z-ai/glm-5.3-flash"
            ),
        )
