"""Publisher-batched DART filing discovery for a frozen organizer inventory."""

from __future__ import annotations

from dataclasses import dataclass

from financial_agent.documents import DocumentSourceCandidate, SourceAuditStatus

from .base import DocumentDiscoveryContext
from .dart import DartDocumentSourceAdapter, DartRejectedFiling
from .dart_publishers import DartPublisherBinding, DartPublisherReconciliation
from .dart_targets import OrganizerDartInventory, OrganizerDartTarget


@dataclass(frozen=True, slots=True)
class DartTargetDiscoveryDisposition:
    target_key: str
    member_entity_ids: tuple[str, ...]
    status: SourceAuditStatus
    reason_code: str | None
    candidates: tuple[DocumentSourceCandidate, ...]


@dataclass(frozen=True, slots=True)
class DartBatchDiscoveryResult:
    dispositions: tuple[DartTargetDiscoveryDisposition, ...]
    requested_publisher_codes: tuple[str, ...]
    rejected_filings: tuple[DartRejectedFiling, ...]

    @property
    def downloaded_ids(self) -> tuple[str, ...]:
        return ()

    @property
    def indexed_ids(self) -> tuple[str, ...]:
        return tuple(
            item.target_key
            for item in self.dispositions
            if item.status is SourceAuditStatus.ELIGIBLE and item.candidates
        )

    @property
    def failed_ids(self) -> tuple[str, ...]:
        indexed = set(self.indexed_ids)
        return tuple(
            item.target_key
            for item in self.dispositions
            if item.target_key not in indexed
        )


def discover_dart_candidates_by_publisher(
    *,
    inventory: OrganizerDartInventory,
    reconciliation: DartPublisherReconciliation,
    adapter: DartDocumentSourceAdapter,
    context: DocumentDiscoveryContext,
) -> DartBatchDiscoveryResult:
    if context.cutoff_date != inventory.cutoff_date:
        raise ValueError("DART batch cutoff does not match organizer inventory")
    bindings = {
        binding.manager_entity_id: binding
        for binding in reconciliation.bindings
    }
    failures = {
        failure.manager_entity_id: failure.reason_code
        for failure in reconciliation.failures
    }
    if set(bindings).intersection(failures):
        raise ValueError("publisher reconciliation is not disjoint")

    dispositions: dict[str, DartTargetDiscoveryDisposition] = {}
    targets_by_publisher: dict[str, list[OrganizerDartTarget]] = {}
    publisher_bindings: dict[str, DartPublisherBinding] = {}
    rejected_filings: set[DartRejectedFiling] = set()
    for target in inventory.targets:
        if not target.manager_bindings:
            dispositions[target.target_key] = _failure_disposition(
                target, "dart_manager_binding_missing"
            )
            continue
        if len(target.manager_bindings) != 1:
            dispositions[target.target_key] = _failure_disposition(
                target, "dart_manager_binding_ambiguous"
            )
            continue
        manager_id, _ = target.manager_bindings[0]
        binding = bindings.get(manager_id)
        if binding is None:
            dispositions[target.target_key] = _failure_disposition(
                target,
                failures.get(manager_id, "dart_publisher_not_reconciled"),
            )
            continue
        existing = publisher_bindings.setdefault(binding.corp_code, binding)
        if existing.corp_name != binding.corp_name:
            raise ValueError("DART corporation code has conflicting names")
        targets_by_publisher.setdefault(binding.corp_code, []).append(target)

    for corp_code, targets in sorted(targets_by_publisher.items()):
        binding = publisher_bindings[corp_code]
        requests = tuple(
            (
                target.target_key,
                target.canonical_name,
                target.representative_entity_id,
            )
            for target in sorted(targets, key=lambda item: item.target_key)
        )
        publisher_result = adapter.discover_publisher_targets(
            corp_code=corp_code,
            publisher_name=binding.corp_name,
            targets=requests,
            context=context,
        )
        discovered = dict(publisher_result.target_results)
        rejected_filings.update(publisher_result.rejected_filings)
        if set(discovered) != {target.target_key for target in targets}:
            raise ValueError("publisher discovery did not account for every target")
        for target in targets:
            result = discovered[target.target_key]
            dispositions[target.target_key] = DartTargetDiscoveryDisposition(
                target_key=target.target_key,
                member_entity_ids=target.member_entity_ids,
                status=result.status,
                reason_code=result.reason_code,
                candidates=result.candidates,
            )

    expected = {target.target_key for target in inventory.targets}
    if set(dispositions) != expected:
        raise ValueError("DART batch did not account for organizer inventory")
    ordered = tuple(dispositions[target_key] for target_key in sorted(expected))
    result = DartBatchDiscoveryResult(
        dispositions=ordered,
        requested_publisher_codes=tuple(sorted(targets_by_publisher)),
        rejected_filings=tuple(
            sorted(
                rejected_filings,
                key=lambda item: (item.receipt_id, item.reason_code),
            )
        ),
    )
    if set(result.indexed_ids).intersection(result.failed_ids):
        raise ValueError("DART batch dispositions overlap")
    return result


def _failure_disposition(
    target: OrganizerDartTarget,
    reason_code: str,
) -> DartTargetDiscoveryDisposition:
    return DartTargetDiscoveryDisposition(
        target_key=target.target_key,
        member_entity_ids=target.member_entity_ids,
        status=SourceAuditStatus.AMBIGUOUS_ENTITY_BINDING,
        reason_code=reason_code,
        candidates=(),
    )
