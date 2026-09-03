"""Promote one revalidated document candidate into immutable Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import (
    CutoffStatus,
    EvidenceKind,
    EvidenceRecord,
    SourceLocator,
    canonical_sha256,
    encode_contract_value,
)
from financial_agent.db.repositories.evidence import (
    EvidenceLedgerRepository,
    OriginReference,
)
from financial_agent.db.schema.document import (
    document_chunk,
    document_coverage,
    document_entity_binding,
    document_profile,
    document_record,
    document_source_artifact,
)
from financial_agent.db.schema.evidence import source_record
from financial_agent.db.schema.operations import dataset_version
from financial_agent.documents import (
    DocumentRole,
    PublisherRole,
    binding_roles_for_document_role,
    document_types_for_role,
    publisher_roles_for_document_role,
)
from financial_agent.retrieval.documents import (
    ClaimAuthorityRule,
    DocumentCandidateHit,
    claim_authority_rules,
)


_SEOUL = ZoneInfo("Asia/Seoul")
_SEARCHABLE_DATASET_STATUSES = frozenset({"building", "validated", "active"})
_PROMOTABLE_RETENTION_STATES = frozenset(
    {"delete_authorized", "metadata_only_deleted"}
)
_MAPPING_VERSION = "document-evidence-v1"


class DocumentEvidencePromotionError(ValueError):
    code = "DOCUMENT_EVIDENCE_PROMOTION_FAILED"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{self.code}: {reason}")


@dataclass(frozen=True, slots=True)
class PromotedDocumentEvidence:
    candidate: DocumentCandidateHit
    evidence: EvidenceRecord


class DocumentEvidencePromoter:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._ledger = EvidenceLedgerRepository(engine)

    async def promote(
        self,
        candidate: DocumentCandidateHit,
        *,
        claim_type: str,
    ) -> PromotedDocumentEvidence:
        rules = claim_authority_rules(claim_type)
        row, binding_roles, coverage_roles = await self._read_authority(candidate)
        self._validate(candidate, rules, row, binding_roles, coverage_roles)
        evidence = _build_evidence(candidate, claim_type, row)
        await self._ledger.append_evidence(
            evidence,
            origin=OriginReference(
                origin_kind="document_chunk",
                dataset_version=candidate.dataset_version,
                record_id=candidate.chunk_id,
            ),
        )
        return PromotedDocumentEvidence(candidate=candidate, evidence=evidence)

    async def _read_authority(
        self, candidate: DocumentCandidateHit
    ) -> tuple[sa.RowMapping, frozenset[str], frozenset[str]]:
        joined = (
            document_chunk.join(
                document_record,
                sa.and_(
                    document_record.c.dataset_version
                    == document_chunk.c.dataset_version,
                    document_record.c.document_id == document_chunk.c.document_id,
                ),
            )
            .join(
                document_profile,
                sa.and_(
                    document_profile.c.dataset_version
                    == document_chunk.c.dataset_version,
                    document_profile.c.document_id == document_chunk.c.document_id,
                ),
            )
            .join(
                source_record,
                sa.and_(
                    source_record.c.dataset_version == document_record.c.dataset_version,
                    source_record.c.source_id == document_record.c.source_id,
                ),
            )
            .join(
                dataset_version,
                dataset_version.c.dataset_version == document_chunk.c.dataset_version,
            )
            .outerjoin(
                document_source_artifact,
                sa.and_(
                    document_source_artifact.c.dataset_version
                    == document_record.c.dataset_version,
                    document_source_artifact.c.document_id
                    == document_record.c.document_id,
                    document_source_artifact.c.source_id == document_record.c.source_id,
                ),
            )
        )
        statement = (
            sa.select(
                document_chunk,
                document_record.c.source_id,
                document_record.c.document_type,
                document_record.c.object_key,
                document_record.c.published_at,
                document_record.c.available_at,
                document_profile.c.document_version,
                document_profile.c.publisher_role,
                document_profile.c.effective_from,
                document_profile.c.effective_to,
                document_profile.c.cutoff_eligible,
                source_record.c.publisher_type,
                source_record.c.source_type,
                source_record.c.authority_tier,
                source_record.c.source_locator_root,
                source_record.c.eligible_for_claim,
                dataset_version.c.status.label("dataset_status"),
                dataset_version.c.cutoff_date,
                document_source_artifact.c.source_artifact_id,
                document_source_artifact.c.attachment_locator,
                document_source_artifact.c.extraction_version,
                document_source_artifact.c.retention_disposition,
                document_source_artifact.c.verified_at,
                document_source_artifact.c.discarded_at,
            )
            .select_from(joined)
            .where(
                document_chunk.c.dataset_version == candidate.dataset_version,
                document_chunk.c.document_id == candidate.document_id,
                document_chunk.c.chunk_id == candidate.chunk_id,
            )
        )
        binding_statement = sa.select(document_entity_binding.c.binding_role).where(
            document_entity_binding.c.dataset_version == candidate.dataset_version,
            document_entity_binding.c.document_id == candidate.document_id,
            document_entity_binding.c.entity_id == candidate.entity_id,
        )
        coverage_statement = sa.select(
            document_coverage.c.required_document_role
        ).where(
            document_coverage.c.dataset_version == candidate.dataset_version,
            document_coverage.c.document_id == candidate.document_id,
            document_coverage.c.entity_id == candidate.entity_id,
            document_coverage.c.coverage_status == "indexed",
        )
        async with self._engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(
                    sa.text(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                )
                row = (await connection.execute(statement)).mappings().one_or_none()
                if row is None:
                    raise DocumentEvidencePromotionError(
                        "authoritative_document_chunk_not_found"
                    )
                binding_roles = frozenset(
                    (await connection.execute(binding_statement)).scalars().all()
                )
                coverage_roles = frozenset(
                    (await connection.execute(coverage_statement)).scalars().all()
                )
            finally:
                if transaction.is_active:
                    await transaction.rollback()
        return row, binding_roles, coverage_roles

    @staticmethod
    def _validate(
        candidate: DocumentCandidateHit,
        rules: tuple[ClaimAuthorityRule, ...],
        row: sa.RowMapping,
        binding_roles: frozenset[str],
        coverage_roles: frozenset[str],
    ) -> None:
        if not binding_roles:
            raise DocumentEvidencePromotionError("entity_binding_not_found")
        if row["dataset_status"] not in _SEARCHABLE_DATASET_STATUSES:
            raise DocumentEvidencePromotionError("dataset_not_searchable")
        if not row["eligible_for_claim"]:
            raise DocumentEvidencePromotionError("source_not_claim_eligible")
        if row["source_artifact_id"] is None:
            raise DocumentEvidencePromotionError("source_artifact_not_found")
        if (
            row["retention_disposition"] not in _PROMOTABLE_RETENTION_STATES
            or row["verified_at"] is None
            or (
                row["retention_disposition"] == "metadata_only_deleted"
                and row["discarded_at"] is None
            )
        ):
            raise DocumentEvidencePromotionError("source_artifact_not_verified")
        if not _authorized(rules, row, binding_roles, coverage_roles):
            raise DocumentEvidencePromotionError("claim_authority_mismatch")

        cutoff_date = row["cutoff_date"]
        if (
            row["published_at"] is None
            or row["available_at"] is None
            or _seoul_date(row["published_at"]) > cutoff_date
            or _seoul_date(row["available_at"]) > cutoff_date
            or row["effective_from"] > cutoff_date
            or (
                row["effective_to"] is not None
                and row["effective_to"] < cutoff_date
            )
            or not row["cutoff_eligible"]
        ):
            raise DocumentEvidencePromotionError("document_not_eligible_at_cutoff")

        expected_metadata = {
            "section_type": row["section_type"],
            "exact_text": row["exact_text"],
            "source_id": row["source_id"],
            "source_locator": _candidate_source_locator(row),
            "published_at": row["published_at"],
            "available_at": row["available_at"],
            "effective_from": row["effective_from"],
            "effective_to": row["effective_to"],
            "document_version": row["document_version"],
            "cutoff_eligible": True,
            "publisher_approved": True,
        }
        for field, expected in expected_metadata.items():
            actual = getattr(candidate, field)
            actual = actual.value if field == "section_type" else actual
            if actual != expected:
                raise DocumentEvidencePromotionError(
                    f"candidate_metadata_mismatch:{field}"
                )
        if sha256(candidate.exact_text.encode("utf-8")).hexdigest() != row["content_hash"]:
            raise DocumentEvidencePromotionError("candidate_content_hash_mismatch")


def _authorized(
    rules: tuple[ClaimAuthorityRule, ...],
    row: sa.RowMapping,
    binding_roles: frozenset[str],
    coverage_roles: frozenset[str],
) -> bool:
    for rule in rules:
        if rule.required_role.value not in coverage_roles:
            continue
        if row["document_type"] not in document_types_for_role(rule.required_role):
            continue
        allowed_bindings = (
            binding_roles_for_document_role(rule.required_role)
            if rule.binding_roles is None
            else rule.binding_roles
        )
        for binding_role in binding_roles & allowed_bindings:
            publishers = publisher_roles_for_document_role(
                rule.required_role, binding_role
            )
            if row["publisher_role"] in {item.value for item in publishers}:
                return True
            if (
                rule.required_role
                in {DocumentRole.PRODUCT_SUMMARY, DocumentRole.PRODUCT_FULL}
                and row["publisher_role"] == PublisherRole.ASSET_MANAGER.value
                and row["publisher_type"] == "regulator"
                and row["source_type"] == "filing"
                and row["authority_tier"] == "official_primary"
                and row["source_locator_root"].startswith(
                    "https://dart.fss.or.kr/"
                )
            ):
                return True
    return False


def _candidate_source_locator(row: sa.RowMapping) -> str:
    if row["page_start"] is None:
        page = "unknown"
    elif row["page_end"] == row["page_start"]:
        page = str(row["page_start"])
    else:
        page = f'{row["page_start"]}-{row["page_end"]}'
    return (
        f'{row["source_locator_root"]}#{row["object_key"]}'
        f';document={row["document_id"]};chunk={row["chunk_id"]}'
        f';page={page};section={row["section_path"]}'
        f';characters={row["character_start"]}-{row["character_end"]}'
    )


def _build_evidence(
    candidate: DocumentCandidateHit,
    claim_type: str,
    row: sa.RowMapping,
) -> EvidenceRecord:
    identity_hash = canonical_sha256(
        {
            "dataset_version": candidate.dataset_version,
            "entity_id": candidate.entity_id,
            "document_id": candidate.document_id,
            "chunk_id": candidate.chunk_id,
            "claim_type": claim_type,
        }
    )
    evidence = EvidenceRecord(
        evidence_id=f"document-span:{identity_hash}",
        evidence_kind=EvidenceKind.DOCUMENT_SPAN,
        source_id=row["source_id"],
        dataset_version=candidate.dataset_version,
        subject_id=candidate.entity_id,
        predicate_id=claim_type,
        value_or_object_id=encode_contract_value(candidate.chunk_id),
        normalized_value=encode_contract_value(candidate.chunk_id),
        unit=None,
        currency=None,
        applicable_date=row["effective_from"],
        valid_from=row["effective_from"],
        valid_to=row["effective_to"],
        published_at=_utc(row["published_at"]),
        available_at=_utc(row["available_at"]),
        vintage_date=None,
        source_locator=SourceLocator(
            locator_type="document_span",
            uri_or_object_key=row["attachment_locator"],
            record_key=row["source_artifact_id"],
            page=row["page_start"],
            section=row["section_path"],
            sentence_start=row["sentence_start"],
            sentence_end=row["sentence_end"],
        ),
        raw_value_repr=row["exact_text"],
        parser_version=row["extraction_version"],
        mapping_version=_MAPPING_VERSION,
        cutoff_status=CutoffStatus.ELIGIBLE,
        record_hash="0" * 64,
        scope_completeness=None,
    )
    return evidence.model_copy(
        update={
            "record_hash": canonical_sha256(
                evidence, exclude_fields={"record_hash"}
            )
        }
    )


def _seoul_date(value: datetime) -> date:
    return value.astimezone(_SEOUL).date()


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)
