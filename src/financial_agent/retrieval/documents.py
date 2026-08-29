"""Metadata-first keyword and pgvector document candidate retrieval."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import math
from types import MappingProxyType

from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.db.schema.document import (
    document_chunk,
    document_coverage,
    document_entity_binding,
    document_profile,
    document_record,
)
from financial_agent.db.schema.evidence import source_record
from financial_agent.db.schema.operations import dataset_version
from financial_agent.db.schema.search import document_embedding, embedding_model
from financial_agent.documents import (
    DocumentRole,
    SEARCHABLE_SECTION_TYPES,
    SectionType,
    binding_roles_for_document_role,
    document_types_for_role,
    publisher_roles_for_document_role,
)


_MAX_TOP_K = 50
_SEARCHABLE_DATASET_STATUSES = ("building", "validated", "active")


class _CDBAdminVector(Vector):
    """Render the managed pgvector type with its owning schema."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        if self.dim is None:
            return "cdb_admin.vector"
        return f"cdb_admin.vector({self.dim})"


@dataclass(frozen=True, slots=True)
class _ClaimRule:
    required_role: DocumentRole
    binding_roles: frozenset[str] | None = None


ClaimAuthorityRule = _ClaimRule


_PRODUCT_DOCUMENT_RULES = (
    _ClaimRule(DocumentRole.PRODUCT_SUMMARY),
    _ClaimRule(DocumentRole.PRODUCT_FULL),
)
_INDEX_DOCUMENT_RULES = (_ClaimRule(DocumentRole.INDEX_METHODOLOGY),)
_POLICY_DOCUMENT_RULES = (_ClaimRule(DocumentRole.POLICY_BASE),)
_FUND_DOCUMENT_RULES = (
    *_PRODUCT_DOCUMENT_RULES,
    *_POLICY_DOCUMENT_RULES,
)
_FUND_UPDATE_RULES = (
    _ClaimRule(
        DocumentRole.OFFICIAL_UPDATE,
        frozenset({"subject_product"}),
    ),
    _ClaimRule(
        DocumentRole.OFFICIAL_UPDATE,
        frozenset({"subject_policy"}),
    ),
)
_INDEX_RELATION_RULES = (
    *_INDEX_DOCUMENT_RULES,
    _ClaimRule(
        DocumentRole.OFFICIAL_UPDATE,
        frozenset({"subject_index"}),
    ),
)
_CLAIM_RULES = MappingProxyType(
    {
        "product_investment_strategy": _PRODUCT_DOCUMENT_RULES,
        "product_strategy": _PRODUCT_DOCUMENT_RULES,
        "investment_strategy": _FUND_DOCUMENT_RULES,
        "product_risk_factor": _PRODUCT_DOCUMENT_RULES,
        "risk_factor": _PRODUCT_DOCUMENT_RULES,
        "concentration_risk": _PRODUCT_DOCUMENT_RULES,
        "market_and_liquidity_risk": _PRODUCT_DOCUMENT_RULES,
        "tracking_and_index_risk": _PRODUCT_DOCUMENT_RULES,
        "currency_risk": _PRODUCT_DOCUMENT_RULES,
        "derivatives_and_counterparty_risk": _PRODUCT_DOCUMENT_RULES,
        "index_methodology": _INDEX_DOCUMENT_RULES,
        "theme_definition": _INDEX_DOCUMENT_RULES,
        "selection_rules": _INDEX_DOCUMENT_RULES,
        "rebalancing": _INDEX_DOCUMENT_RULES,
        "weighting_and_rebalancing": _INDEX_DOCUMENT_RULES,
        "relation_history": _INDEX_RELATION_RULES,
        "theme_relation_evidence_span": _INDEX_RELATION_RULES,
        "structure": _FUND_DOCUMENT_RULES,
        "policy_structure": _POLICY_DOCUMENT_RULES,
        "policy_investment_strategy": _POLICY_DOCUMENT_RULES,
        "publisher_provenance": _FUND_DOCUMENT_RULES,
        "official_update": (_ClaimRule(DocumentRole.OFFICIAL_UPDATE),),
        "official_trend_or_update": _FUND_UPDATE_RULES,
        "policy_update": (
            _ClaimRule(
                DocumentRole.OFFICIAL_UPDATE,
                frozenset({"subject_policy"}),
            ),
        ),
        "product_official_update": (
            _ClaimRule(
                DocumentRole.OFFICIAL_UPDATE,
                frozenset({"subject_product"}),
            ),
        ),
        "index_official_update": (
            _ClaimRule(
                DocumentRole.OFFICIAL_UPDATE,
                frozenset({"subject_index"}),
            ),
        ),
        "policy_official_update": (
            _ClaimRule(
                DocumentRole.OFFICIAL_UPDATE,
                frozenset({"subject_policy"}),
            ),
        ),
    }
)


@dataclass(frozen=True, slots=True)
class DocumentSearchRequest:
    dataset_version: str
    entity_ids: tuple[str, ...]
    claim_type: str
    section_types: tuple[SectionType, ...]
    cutoff_date: date
    top_k: int = 5
    query_embedding: tuple[float, ...] | None = None
    model_id: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if not _has_text(self.dataset_version):
            raise ValueError("dataset_version must not be blank")
        if not isinstance(self.entity_ids, tuple):
            raise ValueError("entity_ids must be a tuple")
        if not self.entity_ids or any(not _has_text(value) for value in self.entity_ids):
            raise ValueError("entity_ids must contain nonblank identifiers")
        if len(set(self.entity_ids)) != len(self.entity_ids):
            raise ValueError("entity_ids must not contain duplicates")
        if not _has_text(self.claim_type):
            raise ValueError("claim_type must not be blank")
        if self.claim_type not in _CLAIM_RULES:
            raise ValueError(f"unsupported claim_type: {self.claim_type}")
        if not isinstance(self.section_types, tuple):
            raise ValueError("section_types must be a tuple")
        if not self.section_types or any(
            not isinstance(value, SectionType) for value in self.section_types
        ):
            raise ValueError("section_types must contain approved SectionType values")
        if any(value not in SEARCHABLE_SECTION_TYPES for value in self.section_types):
            raise ValueError("section_types must contain searchable SectionType values")
        if len(set(self.section_types)) != len(self.section_types):
            raise ValueError("section_types must not contain duplicates")
        if isinstance(self.cutoff_date, datetime) or not isinstance(
            self.cutoff_date, date
        ):
            raise ValueError("cutoff_date must be a date")
        _validate_top_k(self.top_k)

        vector_fields = (
            self.query_embedding,
            self.model_id,
            self.model_version,
        )
        if any(value is not None for value in vector_fields) and not all(
            value is not None for value in vector_fields
        ):
            raise ValueError("query embedding and model identity are all-or-none")
        if self.query_embedding is not None:
            if not isinstance(self.query_embedding, tuple):
                raise ValueError("query_embedding must be a tuple")
            if not self.query_embedding:
                raise ValueError("query_embedding must not be empty")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in self.query_embedding
            ):
                raise ValueError("query_embedding must contain finite numbers")
            if not _has_text(self.model_id) or not _has_text(self.model_version):
                raise ValueError("model identity must not be blank")


@dataclass(frozen=True, slots=True)
class DocumentCandidateHit:
    dataset_version: str
    entity_id: str
    document_id: str
    chunk_id: str
    section_type: SectionType
    exact_text: str
    source_id: str
    source_locator: str
    published_at: datetime
    available_at: datetime
    effective_from: date
    effective_to: date | None
    document_version: str
    cutoff_eligible: bool
    publisher_approved: bool
    keyword_rank: int | None
    vector_rank: int | None
    fused_score: float | None
    evidence_id: None = None

    def __post_init__(self) -> None:
        if self.evidence_id is not None:
            raise ValueError("document candidates cannot carry evidence_id")
        for rank in (self.keyword_rank, self.vector_rank):
            if rank is not None and (
                isinstance(rank, bool) or not isinstance(rank, int) or rank < 1
            ):
                raise ValueError("candidate ranks must be positive integers")
        if self.fused_score is not None and (
            not math.isfinite(self.fused_score) or self.fused_score < 0
        ):
            raise ValueError("fused_score must be finite and non-negative")


class DocumentCandidateRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def search_keyword(
        self, request: DocumentSearchRequest, query_text: str
    ) -> tuple[DocumentCandidateHit, ...]:
        if not _has_text(query_text):
            raise ValueError("query_text must not be blank")
        normalized_query = " ".join(query_text.split()).casefold()
        candidates = _metadata_candidates(request)
        similarity = sa.func.similarity(
            candidates.c.normalized_search_text,
            sa.bindparam("query_text"),
        ).label("retrieval_score")
        statement = (
            sa.select(candidates, similarity)
            .where(
                candidates.c.normalized_search_text.op("%")(
                    sa.bindparam("query_text")
                )
            )
            .order_by(
                sa.desc("retrieval_score"),
                candidates.c.document_id,
                candidates.c.chunk_id,
                candidates.c.entity_id,
            )
            .limit(request.top_k)
        )
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(statement, {"query_text": normalized_query})
            ).mappings().all()
        return tuple(
            _hit_from_row(row, keyword_rank=rank)
            for rank, row in enumerate(rows, start=1)
        )

    async def search_vector(
        self, request: DocumentSearchRequest
    ) -> tuple[DocumentCandidateHit, ...]:
        if (
            request.query_embedding is None
            or request.model_id is None
            or request.model_version is None
        ):
            raise ValueError("VECTOR_SEARCH_REQUIRES_MODEL")

        candidates = _vector_candidates(request)
        query_vector = sa.cast(
            sa.bindparam("query_embedding", type_=_CDBAdminVector()),
            _CDBAdminVector(),
        )
        distance = sa.case(
            (
                candidates.c.distance_metric == "cosine",
                candidates.c.embedding.op(
                    "OPERATOR(cdb_admin.<=>)", return_type=sa.Float
                )(query_vector),
            ),
            (
                candidates.c.distance_metric == "inner_product",
                candidates.c.embedding.op(
                    "OPERATOR(cdb_admin.<#>)", return_type=sa.Float
                )(query_vector),
            ),
            else_=candidates.c.embedding.op(
                "OPERATOR(cdb_admin.<->)", return_type=sa.Float
            )(query_vector),
        ).label("retrieval_distance")
        statement = (
            sa.select(candidates, distance)
            .order_by(
                sa.asc("retrieval_distance"),
                candidates.c.document_id,
                candidates.c.chunk_id,
                candidates.c.entity_id,
            )
            .limit(request.top_k)
        )
        parameters = {
            # Keep the request tuple immutable; adapt it only at the database boundary.
            "query_embedding": [float(value) for value in request.query_embedding]
        }
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement, parameters)).mappings().all()
        return tuple(
            _hit_from_row(row, vector_rank=rank)
            for rank, row in enumerate(rows, start=1)
        )


def claim_authority_rules(claim_type: str) -> tuple[ClaimAuthorityRule, ...]:
    """Return the immutable planner authority rules used by candidate search."""

    try:
        return _CLAIM_RULES[claim_type]
    except KeyError as error:
        raise ValueError(f"unsupported claim_type: {claim_type}") from error


def reciprocal_rank_fusion(
    keyword_hits: tuple[DocumentCandidateHit, ...],
    vector_hits: tuple[DocumentCandidateHit, ...],
    *,
    rrf_k: int = 60,
    top_k: int = 5,
) -> tuple[DocumentCandidateHit, ...]:
    """Fuse two evaluation lists without creating Evidence, relations, or Claims."""

    if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k < 1:
        raise ValueError("rrf_k must be a positive integer")
    _validate_top_k(top_k)
    by_identity: dict[tuple[str, str, str, str], DocumentCandidateHit] = {}
    scores: dict[tuple[str, str, str, str], float] = {}
    keyword_ranks: dict[tuple[str, str, str, str], int] = {}
    vector_ranks: dict[tuple[str, str, str, str], int] = {}

    for mode, hits in (("keyword", keyword_hits), ("vector", vector_hits)):
        seen: set[tuple[str, str, str, str]] = set()
        for position, hit in enumerate(hits, start=1):
            identity = _hit_identity(hit)
            if identity in seen:
                raise ValueError(f"duplicate {mode} candidate identity")
            seen.add(identity)
            rank = (
                hit.keyword_rank if mode == "keyword" else hit.vector_rank
            ) or position
            existing = by_identity.get(identity)
            if existing is not None and _metadata_only(existing) != _metadata_only(hit):
                raise ValueError("candidate metadata differs across retrieval modes")
            by_identity.setdefault(identity, hit)
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (rrf_k + rank)
            if mode == "keyword":
                keyword_ranks[identity] = rank
            else:
                vector_ranks[identity] = rank

    fused = tuple(
        replace(
            hit,
            keyword_rank=keyword_ranks.get(identity),
            vector_rank=vector_ranks.get(identity),
            fused_score=scores[identity],
            evidence_id=None,
        )
        for identity, hit in by_identity.items()
    )
    return tuple(
        sorted(
            fused,
            key=lambda hit: (
                -(hit.fused_score or 0.0),
                hit.document_id,
                hit.chunk_id,
                hit.entity_id,
                hit.dataset_version,
            ),
        )[:top_k]
    )


def _metadata_candidates(request: DocumentSearchRequest) -> sa.Subquery:
    binding_scope = (
        sa.select(
            document_entity_binding.c.dataset_version,
            document_entity_binding.c.document_id,
            document_entity_binding.c.entity_id,
        )
        .where(
            document_entity_binding.c.dataset_version == request.dataset_version,
            document_entity_binding.c.entity_id.in_(request.entity_ids),
        )
        .distinct()
        .subquery("requested_document_entities")
    )
    joined = (
        document_chunk.join(
            document_profile,
            sa.and_(
                document_chunk.c.dataset_version
                == document_profile.c.dataset_version,
                document_chunk.c.document_id == document_profile.c.document_id,
            ),
        )
        .join(
            binding_scope,
            sa.and_(
                document_chunk.c.dataset_version
                == binding_scope.c.dataset_version,
                document_chunk.c.document_id
                == binding_scope.c.document_id,
            ),
        )
        .join(
            document_record,
            sa.and_(
                document_chunk.c.dataset_version
                == document_record.c.dataset_version,
                document_chunk.c.document_id == document_record.c.document_id,
            ),
        )
        .join(
            source_record,
            sa.and_(
                document_record.c.dataset_version == source_record.c.dataset_version,
                document_record.c.source_id == source_record.c.source_id,
            ),
        )
        .join(
            dataset_version,
            document_chunk.c.dataset_version == dataset_version.c.dataset_version,
        )
    )
    cutoff_date = sa.bindparam("cutoff_date", value=request.cutoff_date)
    authority = _claim_authority_predicate(request, binding_scope)
    return (
        sa.select(
            document_chunk.c.dataset_version,
            binding_scope.c.entity_id,
            document_chunk.c.document_id,
            document_chunk.c.chunk_id,
            document_chunk.c.section_type,
            document_chunk.c.exact_text,
            document_chunk.c.normalized_search_text,
            document_chunk.c.content_hash,
            document_chunk.c.page_start,
            document_chunk.c.page_end,
            document_chunk.c.section_path,
            document_chunk.c.character_start,
            document_chunk.c.character_end,
            document_record.c.source_id,
            source_record.c.source_locator_root,
            document_record.c.object_key,
            document_record.c.published_at,
            document_record.c.available_at,
            document_profile.c.effective_from,
            document_profile.c.effective_to,
            document_profile.c.document_version,
            document_profile.c.cutoff_eligible,
            sa.literal(True).label("publisher_approved"),
        )
        .select_from(joined)
        .where(
            document_chunk.c.dataset_version == request.dataset_version,
            document_chunk.c.section_type.in_(
                tuple(section.value for section in request.section_types)
            ),
            document_chunk.c.section_type.in_(
                tuple(
                    sorted(section.value for section in SEARCHABLE_SECTION_TYPES)
                )
            ),
            authority,
            source_record.c.eligible_for_claim.is_(True),
            dataset_version.c.status.in_(_SEARCHABLE_DATASET_STATUSES),
            dataset_version.c.cutoff_date == cutoff_date,
            document_record.c.published_at.is_not(None),
            document_record.c.available_at.is_not(None),
            sa.cast(
                sa.func.timezone("Asia/Seoul", document_record.c.published_at),
                sa.Date,
            )
            <= cutoff_date,
            sa.cast(
                sa.func.timezone("Asia/Seoul", document_record.c.available_at),
                sa.Date,
            )
            <= cutoff_date,
            document_profile.c.effective_from <= cutoff_date,
            sa.func.btrim(document_profile.c.document_version) != "",
            sa.or_(
                document_profile.c.effective_to.is_(None),
                document_profile.c.effective_to >= cutoff_date,
            ),
            document_profile.c.cutoff_eligible.is_(True),
        )
        .subquery("eligible_document_candidates")
    )


def _vector_candidates(request: DocumentSearchRequest) -> sa.Subquery:
    metadata_candidates = _metadata_candidates(request)
    embedding_count = sa.func.count(document_embedding.c.embedding_id).over(
        partition_by=(
            document_embedding.c.dataset_version,
            document_embedding.c.document_id,
            document_embedding.c.chunk_id,
            document_embedding.c.chunk_content_hash,
            document_embedding.c.model_id,
            document_embedding.c.model_version,
        )
    ).label("embedding_count")
    registered_embeddings = (
        sa.select(
            document_embedding.c.dataset_version,
            document_embedding.c.document_id,
            document_embedding.c.chunk_id,
            document_embedding.c.chunk_content_hash,
            document_embedding.c.model_id,
            document_embedding.c.model_version,
            document_embedding.c.dimension,
            document_embedding.c.embedding,
            embedding_model.c.dimension.label("model_dimension"),
            embedding_model.c.distance_metric,
            embedding_model.c.approval_record_id,
            embedding_model.c.approved_at,
            embedding_count,
        )
        .select_from(
            document_embedding.join(
                embedding_model,
                sa.and_(
                    document_embedding.c.model_id == embedding_model.c.model_id,
                    document_embedding.c.model_version
                    == embedding_model.c.model_version,
                ),
            )
        )
        .where(
            document_embedding.c.model_id == request.model_id,
            document_embedding.c.model_version == request.model_version,
        )
        .subquery("registered_model_embeddings")
    )
    unique_embeddings = (
        sa.select(registered_embeddings)
        .where(
            registered_embeddings.c.embedding_count == 1,
            registered_embeddings.c.dimension
            == registered_embeddings.c.model_dimension,
            sa.func.cdb_admin.vector_dims(registered_embeddings.c.embedding)
            == registered_embeddings.c.model_dimension,
            registered_embeddings.c.approval_record_id != "",
            registered_embeddings.c.approved_at.is_not(None),
        )
        .subquery("unique_registered_embeddings")
    )
    joined = unique_embeddings.join(
        metadata_candidates,
        sa.and_(
            unique_embeddings.c.dataset_version
            == metadata_candidates.c.dataset_version,
            unique_embeddings.c.document_id == metadata_candidates.c.document_id,
            unique_embeddings.c.chunk_id == metadata_candidates.c.chunk_id,
            unique_embeddings.c.chunk_content_hash
            == metadata_candidates.c.content_hash,
        ),
    )
    return (
        sa.select(
            *metadata_candidates.c,
            unique_embeddings.c.embedding,
            unique_embeddings.c.distance_metric,
        )
        .select_from(joined)
        .subquery("eligible_vector_candidates")
    )


def _claim_authority_predicate(
    request: DocumentSearchRequest, binding_scope: sa.Subquery
) -> sa.ColumnElement[bool]:
    branches: list[sa.ColumnElement[bool]] = []
    for rule_index, rule in enumerate(_CLAIM_RULES[request.claim_type]):
        allowed_binding_roles = (
            binding_roles_for_document_role(rule.required_role)
            if rule.binding_roles is None
            else rule.binding_roles
        )
        for binding_index, binding_role in enumerate(sorted(allowed_binding_roles)):
            binding_match = document_entity_binding.alias(
                f"authority_binding_{rule_index}_{binding_index}"
            )
            coverage_match = document_coverage.alias(
                f"authority_coverage_{rule_index}_{binding_index}"
            )
            publisher_roles = publisher_roles_for_document_role(
                rule.required_role, binding_role
            )
            branches.append(
                sa.and_(
                    document_record.c.document_type.in_(
                        tuple(sorted(document_types_for_role(rule.required_role)))
                    ),
                    document_profile.c.publisher_role.in_(
                        tuple(sorted(role.value for role in publisher_roles))
                    ),
                    sa.exists(
                        sa.select(1).select_from(binding_match).where(
                            binding_match.c.dataset_version
                            == binding_scope.c.dataset_version,
                            binding_match.c.document_id
                            == binding_scope.c.document_id,
                            binding_match.c.entity_id == binding_scope.c.entity_id,
                            binding_match.c.binding_role == binding_role,
                        )
                    ),
                    sa.exists(
                        sa.select(1).select_from(coverage_match).where(
                            coverage_match.c.dataset_version
                            == binding_scope.c.dataset_version,
                            coverage_match.c.document_id
                            == binding_scope.c.document_id,
                            coverage_match.c.entity_id == binding_scope.c.entity_id,
                            coverage_match.c.required_document_role
                            == rule.required_role.value,
                            coverage_match.c.coverage_status == "indexed",
                        )
                    ),
                )
            )
    return sa.or_(*branches)


def _hit_from_row(
    row: sa.RowMapping,
    *,
    keyword_rank: int | None = None,
    vector_rank: int | None = None,
) -> DocumentCandidateHit:
    return DocumentCandidateHit(
        dataset_version=row["dataset_version"],
        entity_id=row["entity_id"],
        document_id=row["document_id"],
        chunk_id=row["chunk_id"],
        section_type=SectionType(row["section_type"]),
        exact_text=row["exact_text"],
        source_id=row["source_id"],
        source_locator=_source_locator(row),
        published_at=row["published_at"],
        available_at=row["available_at"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        document_version=row["document_version"],
        cutoff_eligible=row["cutoff_eligible"],
        publisher_approved=row["publisher_approved"],
        keyword_rank=keyword_rank,
        vector_rank=vector_rank,
        fused_score=None,
        evidence_id=None,
    )


def _source_locator(row: sa.RowMapping) -> str:
    page = (
        "unknown"
        if row["page_start"] is None
        else (
            str(row["page_start"])
            if row["page_end"] == row["page_start"]
            else f'{row["page_start"]}-{row["page_end"]}'
        )
    )
    return (
        f'{row["source_locator_root"]}#{row["object_key"]}'
        f';document={row["document_id"]};chunk={row["chunk_id"]}'
        f';page={page};section={row["section_path"]}'
        f';characters={row["character_start"]}-{row["character_end"]}'
    )


def _hit_identity(hit: DocumentCandidateHit) -> tuple[str, str, str, str]:
    return (
        hit.dataset_version,
        hit.entity_id,
        hit.document_id,
        hit.chunk_id,
    )


def _metadata_only(hit: DocumentCandidateHit) -> DocumentCandidateHit:
    return replace(
        hit,
        keyword_rank=None,
        vector_rank=None,
        fused_score=None,
        evidence_id=None,
    )


def _validate_top_k(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {_MAX_TOP_K}")


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
