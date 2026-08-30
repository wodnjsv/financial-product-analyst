"""Bounded discovery interfaces for approved official document sources."""

from .base import (
    DocumentDiscoveryContext,
    DocumentSourceAccessError,
    DocumentSourceAdapter,
    HttpStatusError,
    MissingRequiredEnvironmentError,
    SourceAdapterResult,
    classify_access_error,
    sanitize_public_locator,
)

__all__ = [
    "DocumentDiscoveryContext",
    "DocumentSourceAccessError",
    "DocumentSourceAdapter",
    "HttpStatusError",
    "MissingRequiredEnvironmentError",
    "SourceAdapterResult",
    "classify_access_error",
    "sanitize_public_locator",
]
