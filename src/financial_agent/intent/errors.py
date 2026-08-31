"""Stable failures for the bounded CLOVA intent adapter."""

from __future__ import annotations


MODEL_TIMEOUT = "MODEL_TIMEOUT"
MODEL_RATE_LIMITED = "MODEL_RATE_LIMITED"
MODEL_PROVIDER_UNAVAILABLE = "MODEL_PROVIDER_UNAVAILABLE"
MODEL_CONFIGURATION_INVALID = "MODEL_CONFIGURATION_INVALID"
MODEL_SCHEMA_INVALID = "MODEL_SCHEMA_INVALID"


class ResolverContractError(RuntimeError):
    """A stable resolver failure that is safe to expose to orchestration."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ModelInvocationError(ResolverContractError):
    """A provider-boundary failure with no provider payload attached."""
