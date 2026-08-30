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
from .dart_targets import (
    OrganizerDartInventory,
    OrganizerDartProductRow,
    OrganizerDartTarget,
    build_organizer_dart_inventory,
)

__all__ = [
    "DocumentDiscoveryContext",
    "DocumentSourceAccessError",
    "DocumentSourceAccessErrorCode",
    "DocumentSourceAdapter",
    "DartProspectusContext",
    "DartProspectusProcessingResult",
    "DartProspectusQualityReport",
    "OrganizerDartInventory",
    "OrganizerDartProductRow",
    "OrganizerDartTarget",
    "assemble_captured_corpus",
    "build_organizer_dart_inventory",
    "process_dart_prospectus",
    "HttpStatusError",
    "MissingRequiredEnvironmentError",
    "NoRedirectHttpOpener",
    "SourceAdapterResult",
    "classify_access_error",
    "sanitize_public_locator",
]
