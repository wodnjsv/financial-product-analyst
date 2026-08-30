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
from .dart_batch import (
    DartBatchDiscoveryResult,
    DartTargetDiscoveryDisposition,
    discover_dart_candidates_by_publisher,
)
from .dart_publishers import (
    DartPublisherBinding,
    DartPublisherDataError,
    DartPublisherFailure,
    DartPublisherReconciliation,
    fetch_dart_corporation_codes,
    reconcile_dart_publishers,
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
    "DartBatchDiscoveryResult",
    "DartPublisherBinding",
    "DartPublisherDataError",
    "DartPublisherFailure",
    "DartPublisherReconciliation",
    "DartTargetDiscoveryDisposition",
    "OrganizerDartInventory",
    "OrganizerDartProductRow",
    "OrganizerDartTarget",
    "assemble_captured_corpus",
    "build_organizer_dart_inventory",
    "discover_dart_candidates_by_publisher",
    "fetch_dart_corporation_codes",
    "process_dart_prospectus",
    "reconcile_dart_publishers",
    "HttpStatusError",
    "MissingRequiredEnvironmentError",
    "NoRedirectHttpOpener",
    "SourceAdapterResult",
    "classify_access_error",
    "sanitize_public_locator",
]
