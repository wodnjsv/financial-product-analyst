"""Bounded discovery interfaces for approved official document sources."""

from .base import (
    DocumentDiscoveryContext,
    DocumentSourceAccessError,
    DocumentSourceAccessErrorCode,
    DocumentSourceAdapter,
    HttpStatusError,
    MissingRequiredEnvironmentError,
    NoRedirectHttpOpener,
    SourceAdapterResult,
    classify_access_error,
    sanitize_public_locator,
)
from .dart_pipeline import (
    DartProspectusContext,
    DartProspectusProcessingResult,
    DartProspectusQualityReport,
    assemble_captured_corpus,
    process_dart_prospectus,
)

__all__ = [
    "DocumentDiscoveryContext",
    "DocumentSourceAccessError",
    "DocumentSourceAccessErrorCode",
    "DocumentSourceAdapter",
    "DartProspectusContext",
    "DartProspectusProcessingResult",
    "DartProspectusQualityReport",
    "assemble_captured_corpus",
    "process_dart_prospectus",
    "HttpStatusError",
    "MissingRequiredEnvironmentError",
    "NoRedirectHttpOpener",
    "SourceAdapterResult",
    "classify_access_error",
    "sanitize_public_locator",
]
