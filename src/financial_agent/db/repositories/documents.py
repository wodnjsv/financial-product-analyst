from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from financial_agent.db.schema.catalog import entity
from financial_agent.db.schema.document import (
    document_chunk,
    document_coverage,
    document_entity_binding,
    document_profile,
    document_record,
)
from financial_agent.db.schema.operations import dataset_version
from financial_agent.documents import (
    CoverageStatus,
    DocumentChunkDraft,
    DocumentCoverageDraft,
    DocumentRole,
    PublisherRole,
    SectionType,
)


BindingRole = Literal["subject_product", "subject_index", "subject_policy"]
SourceArtifactRetentionDisposition = Literal[
    "pending_delete",
    "delete_authorized",
    "metadata_only_deleted",
    "quarantined",
]


@dataclass(frozen=True, slots=True)
class DocumentProfileRecord:
    dataset_version: str
    document_id: str
    document_version: str
    publisher_role: PublisherRole
    jurisdiction: str
    original_language: str
    effective_from: date
    effective_to: date | None
    amends_document_id: str | None
    extraction_method: str
    cutoff_eligible: bool
    record_hash: str


@dataclass(frozen=True, slots=True)
class DocumentEntityBindingRecord:
    dataset_version: str
    binding_id: str
    document_id: str
    entity_id: str
    binding_role: BindingRole
    record_hash: str


@dataclass(frozen=True, slots=True)
class DocumentSourceArtifactRecord:
    dataset_version: str
    source_artifact_id: str
    source_id: str
    document_id: str
    receipt_id: str
    original_filename: str
    filing_locator: str
    attachment_locator: str
    media_type: str
    byte_count: int
    source_checksum: str
    text_checksum: str
    page_count: int
    extraction_version: str
    retention_disposition: SourceArtifactRetentionDisposition
    downloaded_at: datetime
    persisted_at: datetime
    verified_at: datetime | None
    discarded_at: datetime | None
    record_hash: str


@dataclass(frozen=True, slots=True)
class DocumentCorpusRecord:
    dataset_version: str
    document_id: str
    source_id: str
    document_title: str
    document_type: str
    object_key: str
    content_checksum: str
    published_at: datetime | None
    available_at: datetime | None
    profile: DocumentProfileRecord
    entity_bindings: tuple[DocumentEntityBindingRecord, ...]
    chunks: tuple[DocumentChunkDraft, ...]
    required_document_role: DocumentRole
    coverage: DocumentCoverageDraft


class DocumentCorpusError(RuntimeError):
    code = "DOCUMENT_CORPUS_ERROR"

    def __init__(self, detail: str | None = None) -> None:
        message = self.code if detail is None else f"{self.code}: {detail}"
        super().__init__(message)


class DocumentCorpusConflict(DocumentCorpusError):
    code = "DOCUMENT_CORPUS_CONFLICT"


class DocumentCorpusStateError(DocumentCorpusError):
    code = "DOCUMENT_DATASET_NOT_BUILDING"


class DocumentCorpusValidationError(DocumentCorpusError, ValueError):
    code = "DOCUMENT_CORPUS_INVALID"


class DocumentCorpusNotFound(DocumentCorpusError, LookupError):
    code = "DOCUMENT_CORPUS_NOT_FOUND"


def _sha256(text_value: str) -> str:
    return hashlib.sha256(text_value.encode()).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _utc_datetime(value: datetime, field_name: str = "datetime") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DocumentCorpusValidationError(field_name)
    return value.astimezone(UTC)


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _utc_datetime(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _profile_payload(profile: DocumentProfileRecord) -> dict[str, object]:
    return asdict(profile)


def _binding_payload(binding: DocumentEntityBindingRecord) -> dict[str, object]:
    return asdict(binding)


def _chunk_payload(chunk: DocumentChunkDraft) -> dict[str, object]:
    payload = asdict(chunk)
    payload.pop("embedding_text")
    return payload


def _chunk_hash_payload(chunk: DocumentChunkDraft) -> dict[str, object]:
    payload = _chunk_payload(chunk)
    payload.pop("record_hash")
    return payload


def _coverage_payload(coverage: DocumentCoverageDraft) -> dict[str, object]:
    return asdict(coverage)


def _source_artifact_payload(
    artifact: DocumentSourceArtifactRecord,
) -> dict[str, object]:
    return asdict(artifact)


def _source_artifact_record_hash(
    artifact: DocumentSourceArtifactRecord,
) -> str:
    payload = _source_artifact_payload(artifact)
    payload.pop("record_hash")
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _corpus_payload(corpus: DocumentCorpusRecord) -> dict[str, object]:
    return {
        "dataset_version": corpus.dataset_version,
        "document_id": corpus.document_id,
        "source_id": corpus.source_id,
        "document_title": corpus.document_title,
        "document_type": corpus.document_type,
        "object_key": corpus.object_key,
        "content_checksum": corpus.content_checksum,
        "published_at": corpus.published_at,
        "available_at": corpus.available_at,
        "profile": _profile_payload(corpus.profile),
        "entity_bindings": [
            _binding_payload(binding)
            for binding in sorted(
                corpus.entity_bindings, key=lambda item: item.binding_id
            )
        ],
        "chunks": [
            _chunk_payload(chunk)
            for chunk in sorted(corpus.chunks, key=lambda item: item.ordinal)
        ],
        "required_document_role": corpus.required_document_role,
        "coverage": _coverage_payload(corpus.coverage),
    }


def _corpus_bytes(corpus: DocumentCorpusRecord) -> bytes:
    return _canonical_bytes(_corpus_payload(corpus))


def _coverage_bytes(coverage: DocumentCoverageDraft) -> bytes:
    return _canonical_bytes(_coverage_payload(coverage))


def _document_record_hash(corpus: DocumentCorpusRecord) -> str:
    payload = {
        "dataset_version": corpus.dataset_version,
        "document_id": corpus.document_id,
        "source_id": corpus.source_id,
        "document_title": corpus.document_title,
        "document_type": corpus.document_type,
        "object_key": corpus.object_key,
        "content_checksum": corpus.content_checksum,
        "published_at": corpus.published_at,
        "available_at": corpus.available_at,
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


class DocumentCorpusRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @staticmethod
    def validate_corpus(corpus: DocumentCorpusRecord) -> None:
        for label, value in (
            ("dataset_version", corpus.dataset_version),
            ("document_id", corpus.document_id),
            ("source_id", corpus.source_id),
            ("document_title", corpus.document_title),
            ("document_type", corpus.document_type),
            ("object_key", corpus.object_key),
        ):
            if not value.strip():
                raise DocumentCorpusValidationError(label)
        if not _is_sha256(corpus.content_checksum):
            raise DocumentCorpusValidationError("content_checksum")
        for field_name, value in (
            ("published_at", corpus.published_at),
            ("available_at", corpus.available_at),
        ):
            if value is not None:
                _utc_datetime(value, field_name)
        if corpus.profile.dataset_version != corpus.dataset_version:
            raise DocumentCorpusValidationError("profile dataset_version")
        if corpus.profile.document_id != corpus.document_id:
            raise DocumentCorpusValidationError("profile document_id")
        if not isinstance(corpus.profile.document_version, str) or not (
            corpus.profile.document_version.strip()
        ):
            raise DocumentCorpusValidationError("profile document_version")
        if not corpus.entity_bindings:
            raise DocumentCorpusValidationError("entity_bindings")
        if not corpus.chunks:
            raise DocumentCorpusValidationError("chunks")
        for binding in corpus.entity_bindings:
            if binding.dataset_version != corpus.dataset_version:
                raise DocumentCorpusValidationError("binding dataset_version")
            if binding.document_id != corpus.document_id:
                raise DocumentCorpusValidationError("binding document_id")
            if binding.binding_role not in {
                "subject_product",
                "subject_index",
                "subject_policy",
            }:
                raise DocumentCorpusValidationError("binding_role")
            if not _is_sha256(binding.record_hash):
                raise DocumentCorpusValidationError("binding record_hash")
        ordinals: set[int] = set()
        chunk_ids: set[str] = set()
        for chunk in corpus.chunks:
            if chunk.dataset_version != corpus.dataset_version:
                raise DocumentCorpusValidationError("chunk dataset_version")
            if chunk.document_id != corpus.document_id:
                raise DocumentCorpusValidationError("chunk document_id")
            if chunk.ordinal < 0 or chunk.ordinal in ordinals:
                raise DocumentCorpusValidationError("chunk ordinal")
            if not chunk.chunk_id.strip() or chunk.chunk_id in chunk_ids:
                raise DocumentCorpusValidationError("chunk_id")
            ordinals.add(chunk.ordinal)
            chunk_ids.add(chunk.chunk_id)
            if (chunk.page_start is None) != (chunk.page_end is None):
                raise DocumentCorpusValidationError("chunk page range")
            if chunk.page_start is not None and (
                chunk.page_start < 1 or chunk.page_end < chunk.page_start
            ):
                raise DocumentCorpusValidationError("chunk page range")
            if (
                chunk.character_start < 0
                or chunk.character_end < chunk.character_start
                or chunk.character_end - chunk.character_start != len(chunk.exact_text)
            ):
                raise DocumentCorpusValidationError("chunk character range")
            if not chunk.exact_text or not chunk.section_path.strip():
                raise DocumentCorpusValidationError("chunk text locator")
            if chunk.content_hash != _sha256(chunk.exact_text):
                raise DocumentCorpusValidationError("chunk content_hash")
            expected_record_hash = hashlib.sha256(
                _canonical_bytes(_chunk_hash_payload(chunk))
            ).hexdigest()
            if chunk.record_hash != expected_record_hash:
                raise DocumentCorpusValidationError("chunk record_hash")
        coverage = corpus.coverage
        if coverage.dataset_version != corpus.dataset_version:
            raise DocumentCorpusValidationError("coverage dataset_version")
        if coverage.document_id != corpus.document_id:
            raise DocumentCorpusValidationError("coverage document_id")
        if coverage.required_document_role is not corpus.required_document_role:
            raise DocumentCorpusValidationError("coverage document role")
        if coverage.coverage_status is not CoverageStatus.INDEXED:
            raise DocumentCorpusValidationError("corpus coverage must be indexed")
        if coverage.entity_id not in {
            binding.entity_id for binding in corpus.entity_bindings
        }:
            raise DocumentCorpusValidationError("coverage entity binding")
        if not _is_sha256(corpus.profile.record_hash):
            raise DocumentCorpusValidationError("profile record_hash")
        if not _is_sha256(coverage.record_hash):
            raise DocumentCorpusValidationError("coverage record_hash")

    @staticmethod
    def validate_source_artifact(artifact: DocumentSourceArtifactRecord) -> None:
        for label, value in (
            ("dataset_version", artifact.dataset_version),
            ("source_artifact_id", artifact.source_artifact_id),
            ("source_id", artifact.source_id),
            ("document_id", artifact.document_id),
            ("original_filename", artifact.original_filename),
            ("extraction_version", artifact.extraction_version),
        ):
            if not value.strip():
                raise DocumentCorpusValidationError(label)
        if len(artifact.receipt_id) != 14 or not artifact.receipt_id.isdigit():
            raise DocumentCorpusValidationError("receipt_id")
        for field_name, locator, receipt_parameter in (
            ("filing_locator", artifact.filing_locator, "rcpNo"),
            ("attachment_locator", artifact.attachment_locator, "rcp_no"),
        ):
            parsed = urlsplit(locator)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "dart.fss.or.kr"
                or parsed.port is not None
                or parsed.username is not None
                or parsed.password is not None
                or parse_qs(parsed.query).get(receipt_parameter)
                != [artifact.receipt_id]
            ):
                raise DocumentCorpusValidationError(field_name)
        if artifact.media_type != "application/pdf":
            raise DocumentCorpusValidationError("media_type")
        for field_name, value in (
            ("byte_count", artifact.byte_count),
            ("page_count", artifact.page_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise DocumentCorpusValidationError(field_name)
        for field_name, value in (
            ("source_checksum", artifact.source_checksum),
            ("text_checksum", artifact.text_checksum),
        ):
            if not _is_sha256(value):
                raise DocumentCorpusValidationError(field_name)
        downloaded_at = _utc_datetime(artifact.downloaded_at, "downloaded_at")
        persisted_at = _utc_datetime(artifact.persisted_at, "persisted_at")
        verified_at = (
            _utc_datetime(artifact.verified_at, "verified_at")
            if artifact.verified_at is not None
            else None
        )
        discarded_at = (
            _utc_datetime(artifact.discarded_at, "discarded_at")
            if artifact.discarded_at is not None
            else None
        )
        if persisted_at < downloaded_at:
            raise DocumentCorpusValidationError("persisted_at")
        if verified_at is not None and verified_at < persisted_at:
            raise DocumentCorpusValidationError("verified_at")
        valid_state = (
            artifact.retention_disposition == "pending_delete"
            and verified_at is None
            and discarded_at is None
        ) or (
            artifact.retention_disposition == "delete_authorized"
            and verified_at is not None
            and discarded_at is None
        ) or (
            artifact.retention_disposition == "metadata_only_deleted"
            and verified_at is not None
            and discarded_at is not None
        ) or (
            artifact.retention_disposition == "quarantined"
            and discarded_at is None
        )
        if not valid_state:
            raise DocumentCorpusValidationError("retention state")
        if discarded_at is not None:
            assert verified_at is not None
            if discarded_at < verified_at:
                raise DocumentCorpusValidationError("discarded_at")
        if artifact.record_hash != _source_artifact_record_hash(artifact):
            raise DocumentCorpusValidationError("record_hash")

    @staticmethod
    def validate_standalone_coverage(coverage: DocumentCoverageDraft) -> None:
        if coverage.coverage_status is CoverageStatus.INDEXED:
            raise DocumentCorpusValidationError(
                "standalone coverage must be documentless negative coverage"
            )
        if not coverage.dataset_version.strip() or not coverage.entity_id.strip():
            raise DocumentCorpusValidationError("coverage identity")
        if not _is_sha256(coverage.record_hash):
            raise DocumentCorpusValidationError("coverage record_hash")

    async def append_corpus(self, corpus: DocumentCorpusRecord) -> None:
        self.validate_corpus(corpus)
        created_at = datetime.now(UTC)
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await self._require_building_dataset(
                        connection, corpus.dataset_version
                    )
                    await self._validate_embedding_context(connection, corpus)
                    await connection.execute(
                        sa.insert(document_record).values(
                            dataset_version=corpus.dataset_version,
                            document_id=corpus.document_id,
                            source_id=corpus.source_id,
                            document_title=corpus.document_title,
                            document_type=corpus.document_type,
                            object_key=corpus.object_key,
                            content_checksum=corpus.content_checksum,
                            published_at=(
                                _utc_datetime(corpus.published_at, "published_at")
                                if corpus.published_at is not None
                                else None
                            ),
                            available_at=(
                                _utc_datetime(corpus.available_at, "available_at")
                                if corpus.available_at is not None
                                else None
                            ),
                            record_hash=_document_record_hash(corpus),
                            created_at=created_at,
                        )
                    )
                    await connection.execute(
                        sa.insert(document_profile).values(
                            **_profile_payload(corpus.profile),
                            created_at=created_at,
                        )
                    )
                    for binding in sorted(
                        corpus.entity_bindings, key=lambda item: item.binding_id
                    ):
                        await connection.execute(
                            sa.insert(document_entity_binding).values(
                                **_binding_payload(binding),
                                created_at=created_at,
                            )
                        )
                    for chunk in sorted(corpus.chunks, key=lambda item: item.ordinal):
                        await connection.execute(
                            sa.insert(document_chunk).values(
                                **_chunk_payload(chunk),
                                parent_chunk_id=None,
                                section=chunk.section_path,
                                sentence_start=None,
                                sentence_end=None,
                                created_at=created_at,
                            )
                        )
                    await connection.execute(
                        sa.insert(document_coverage).values(
                            **_coverage_payload(corpus.coverage),
                            created_at=created_at,
                        )
                    )
                    await self._force_constraints(connection)
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != "23505":
                raise
            existing = await self._find_corpus(
                corpus.dataset_version, corpus.document_id
            )
            if existing is not None and _corpus_bytes(existing) == _corpus_bytes(
                corpus
            ):
                return
            raise DocumentCorpusConflict() from error

    async def append_coverage(self, coverage: DocumentCoverageDraft) -> None:
        self.validate_standalone_coverage(coverage)
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await self._require_building_dataset(
                        connection, coverage.dataset_version
                    )
                    await connection.execute(
                        sa.insert(document_coverage).values(
                            **_coverage_payload(coverage),
                            created_at=datetime.now(UTC),
                        )
                    )
                    await self._force_constraints(connection)
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != "23505":
                raise
            existing = await self._find_coverage(
                coverage.dataset_version,
                coverage.entity_id,
                coverage.required_document_role,
            )
            if existing is not None and _coverage_bytes(existing) == _coverage_bytes(
                coverage
            ):
                return
            raise DocumentCorpusConflict() from error

    async def get_coverage(
        self,
        dataset_version_value: str,
        entity_id: str,
        required_document_role: DocumentRole,
    ) -> DocumentCoverageDraft:
        coverage = await self._find_coverage(
            dataset_version_value, entity_id, required_document_role
        )
        if coverage is None:
            raise DocumentCorpusNotFound()
        return coverage

    async def list_chunks(
        self,
        dataset_version_value: str,
        document_id: str,
    ) -> tuple[DocumentChunkDraft, ...]:
        async with self._engine.connect() as connection:
            return await self._list_chunks(
                connection, dataset_version_value, document_id
            )

    async def _find_corpus(
        self, dataset_version_value: str, document_id_value: str
    ) -> DocumentCorpusRecord | None:
        async with self._engine.connect() as connection:
            record = (
                await connection.execute(
                    sa.select(document_record).where(
                        document_record.c.dataset_version == dataset_version_value,
                        document_record.c.document_id == document_id_value,
                    )
                )
            ).mappings().one_or_none()
            if record is None:
                return None
            profile_row = (
                await connection.execute(
                    sa.select(document_profile).where(
                        document_profile.c.dataset_version == dataset_version_value,
                        document_profile.c.document_id == document_id_value,
                    )
                )
            ).mappings().one_or_none()
            binding_rows = (
                await connection.execute(
                    sa.select(document_entity_binding)
                    .where(
                        document_entity_binding.c.dataset_version
                        == dataset_version_value,
                        document_entity_binding.c.document_id == document_id_value,
                    )
                    .order_by(document_entity_binding.c.binding_id)
                )
            ).mappings().all()
            coverage_row = (
                await connection.execute(
                    sa.select(document_coverage).where(
                        document_coverage.c.dataset_version == dataset_version_value,
                        document_coverage.c.document_id == document_id_value,
                    )
                )
            ).mappings().one_or_none()
            if profile_row is None or not binding_rows or coverage_row is None:
                return None
            chunks = await self._list_chunks(
                connection, dataset_version_value, document_id_value
            )
        profile = DocumentProfileRecord(
            dataset_version=profile_row["dataset_version"],
            document_id=profile_row["document_id"],
            document_version=profile_row["document_version"],
            publisher_role=PublisherRole(profile_row["publisher_role"]),
            jurisdiction=profile_row["jurisdiction"],
            original_language=profile_row["original_language"],
            effective_from=profile_row["effective_from"],
            effective_to=profile_row["effective_to"],
            amends_document_id=profile_row["amends_document_id"],
            extraction_method=profile_row["extraction_method"],
            cutoff_eligible=profile_row["cutoff_eligible"],
            record_hash=profile_row["record_hash"],
        )
        bindings = tuple(
            DocumentEntityBindingRecord(
                dataset_version=row["dataset_version"],
                binding_id=row["binding_id"],
                document_id=row["document_id"],
                entity_id=row["entity_id"],
                binding_role=row["binding_role"],
                record_hash=row["record_hash"],
            )
            for row in binding_rows
        )
        coverage = self._coverage_from_row(coverage_row)
        return DocumentCorpusRecord(
            dataset_version=record["dataset_version"],
            document_id=record["document_id"],
            source_id=record["source_id"],
            document_title=record["document_title"],
            document_type=record["document_type"],
            object_key=record["object_key"],
            content_checksum=record["content_checksum"],
            published_at=record["published_at"],
            available_at=record["available_at"],
            profile=profile,
            entity_bindings=bindings,
            chunks=chunks,
            required_document_role=coverage.required_document_role,
            coverage=coverage,
        )

    async def _find_coverage(
        self,
        dataset_version_value: str,
        entity_id_value: str,
        required_document_role: DocumentRole,
    ) -> DocumentCoverageDraft | None:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.select(document_coverage).where(
                        document_coverage.c.dataset_version
                        == dataset_version_value,
                        document_coverage.c.entity_id == entity_id_value,
                        document_coverage.c.required_document_role
                        == required_document_role.value,
                    )
                )
            ).mappings().one_or_none()
        return None if row is None else self._coverage_from_row(row)

    async def _list_chunks(
        self,
        connection: AsyncConnection,
        dataset_version_value: str,
        document_id_value: str,
    ) -> tuple[DocumentChunkDraft, ...]:
        context = (
            await connection.execute(
                sa.select(
                    entity.c.canonical_name,
                    document_record.c.document_type,
                )
                .select_from(
                    document_coverage.join(
                        document_entity_binding,
                        sa.and_(
                            document_coverage.c.dataset_version
                            == document_entity_binding.c.dataset_version,
                            document_coverage.c.document_id
                            == document_entity_binding.c.document_id,
                            document_coverage.c.entity_id
                            == document_entity_binding.c.entity_id,
                        ),
                    ).join(
                        entity,
                        sa.and_(
                            document_entity_binding.c.dataset_version
                            == entity.c.dataset_version,
                            document_entity_binding.c.entity_id == entity.c.entity_id,
                        ),
                    ).join(
                        document_record,
                        sa.and_(
                            document_entity_binding.c.dataset_version
                            == document_record.c.dataset_version,
                            document_entity_binding.c.document_id
                            == document_record.c.document_id,
                        ),
                    )
                )
                .where(
                    document_coverage.c.dataset_version == dataset_version_value,
                    document_coverage.c.document_id == document_id_value,
                    document_coverage.c.coverage_status
                    == CoverageStatus.INDEXED.value,
                )
                .distinct()
            )
        ).one_or_none()
        rows = (
            await connection.execute(
                sa.select(document_chunk)
                .where(
                    document_chunk.c.dataset_version == dataset_version_value,
                    document_chunk.c.document_id == document_id_value,
                )
                .order_by(document_chunk.c.ordinal)
            )
        ).mappings().all()
        return tuple(
            DocumentChunkDraft(
                dataset_version=row["dataset_version"],
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                ordinal=row["ordinal"],
                page_start=row["page_start"],
                page_end=row["page_end"],
                section_type=SectionType(row["section_type"]),
                section_path=row["section_path"],
                character_start=row["character_start"],
                character_end=row["character_end"],
                exact_text=row["exact_text"],
                normalized_search_text=row["normalized_search_text"],
                embedding_text=(
                    "\n".join(
                        (
                            context.canonical_name,
                            context.document_type,
                            row["section_path"],
                            row["exact_text"],
                        )
                    )
                    if context is not None
                    else row["exact_text"]
                ),
                content_hash=row["content_hash"],
                record_hash=row["record_hash"],
            )
            for row in rows
        )

    @staticmethod
    def _coverage_from_row(row: sa.RowMapping) -> DocumentCoverageDraft:
        return DocumentCoverageDraft(
            coverage_id=row["coverage_id"],
            dataset_version=row["dataset_version"],
            entity_id=row["entity_id"],
            required_document_role=DocumentRole(row["required_document_role"]),
            coverage_status=CoverageStatus(row["coverage_status"]),
            document_id=row["document_id"],
            scope_evidence_id=row["scope_evidence_id"],
            reason_code=row["reason_code"],
            record_hash=row["record_hash"],
        )

    @staticmethod
    async def _validate_embedding_context(
        connection: AsyncConnection,
        corpus: DocumentCorpusRecord,
    ) -> None:
        canonical_name = await connection.scalar(
            sa.select(entity.c.canonical_name).where(
                entity.c.dataset_version == corpus.dataset_version,
                entity.c.entity_id == corpus.coverage.entity_id,
            )
        )
        if canonical_name is None:
            raise DocumentCorpusValidationError("embedding context entity")
        for chunk in corpus.chunks:
            expected = "\n".join(
                (
                    canonical_name,
                    corpus.document_type,
                    chunk.section_path,
                    chunk.exact_text,
                )
            )
            if chunk.embedding_text != expected:
                raise DocumentCorpusValidationError("chunk embedding_text")

    @staticmethod
    async def _require_building_dataset(
        connection: AsyncConnection, dataset_version_value: str
    ) -> None:
        status = await connection.scalar(
            sa.select(dataset_version.c.status)
            .where(dataset_version.c.dataset_version == dataset_version_value)
            .with_for_update(read=True)
        )
        if status != "building":
            raise DocumentCorpusStateError()

    @staticmethod
    async def _force_constraints(connection: AsyncConnection) -> None:
        await connection.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
