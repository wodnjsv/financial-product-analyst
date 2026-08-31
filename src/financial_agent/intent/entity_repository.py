"""Dataset-pinned, bounded entity-candidate lookup."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from .candidates import EntityCandidate, Mention


MAX_ENTITY_CANDIDATES_PER_MENTION = 5
TRIGRAM_THRESHOLD = 0.30


class ResolverCatalogUnavailable(RuntimeError):
    code = "RESOLVER_CATALOG_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class EntityCandidateRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def search_batch(
        self,
        dataset_version: str,
        mentions: Sequence[Mention],
    ) -> Mapping[str, tuple[EntityCandidate, ...]]:
        """Search every mention in one dataset-pinned read transaction."""
        if not dataset_version:
            raise ValueError("dataset_version is required")
        mention_ids = tuple(mention.mention_id for mention in mentions)
        if len(set(mention_ids)) != len(mention_ids):
            raise ValueError("mention IDs must be unique")
        if not mentions:
            return MappingProxyType({})

        statement, parameters = _search_statement(dataset_version, mentions)
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    rows = (await connection.execute(statement, parameters)).mappings().all()
            candidates: dict[str, list[EntityCandidate]] = {
                mention_id: [] for mention_id in mention_ids
            }
            for row in rows:
                candidates[str(row["mention_id"])].append(
                    EntityCandidate(
                        entity_id=str(row["entity_id"]),
                        canonical_name=str(row["canonical_name"]),
                        entity_type=str(row["entity_type"]),
                        product_family=(
                            str(row["product_family"])
                            if row["product_family"] is not None
                            else None
                        ),
                        match_kind=str(row["match_kind"]),  # type: ignore[arg-type]
                        score=int(row["score"]),
                        source_id=str(row["source_id"]),
                    )
                )
        except (KeyError, SQLAlchemyError, ValidationError) as error:
            raise ResolverCatalogUnavailable() from error
        return MappingProxyType(
            {mention_id: tuple(candidates[mention_id]) for mention_id in mention_ids}
        )


def _search_statement(
    dataset_version: str, mentions: Sequence[Mention]
) -> tuple[sa.TextClause, dict[str, object]]:
    values = ", ".join(
        f"(:mention_id_{index}, :normalized_text_{index})"
        for index, _ in enumerate(mentions)
    )
    parameters: dict[str, object] = {
        "dataset_version": dataset_version,
        "trigram_threshold": TRIGRAM_THRESHOLD,
    }
    for index, mention in enumerate(mentions):
        parameters[f"mention_id_{index}"] = mention.mention_id
        parameters[f"normalized_text_{index}"] = mention.normalized_text

    statement = sa.text(
        f"""
        WITH mentions(mention_id, normalized_text) AS (VALUES {values}),
        dataset AS (
            SELECT cutoff_date
            FROM operations.dataset_version
            WHERE dataset_version = :dataset_version
        ),
        candidates AS (
            SELECT m.mention_id, entity.entity_id, entity.canonical_name,
                   entity.entity_type, product.product_family,
                   'exact_identifier'::text AS match_kind,
                   1000000::integer AS score, identifier.identifier_id AS source_id,
                   0::integer AS match_priority
            FROM mentions AS m
            JOIN dataset ON TRUE
            JOIN catalog.identifier AS identifier
              ON identifier.dataset_version = :dataset_version
             AND identifier.identifier_value = m.normalized_text
            JOIN catalog.entity AS entity
              ON entity.dataset_version = identifier.dataset_version
             AND entity.entity_id = identifier.entity_id
            LEFT JOIN catalog.product AS product
              ON product.dataset_version = entity.dataset_version
             AND product.entity_id = entity.entity_id

            UNION ALL

            SELECT m.mention_id, entity.entity_id, entity.canonical_name,
                   entity.entity_type, product.product_family,
                   'exact_name'::text AS match_kind,
                   1000000::integer AS score, entity.entity_id AS source_id,
                   1::integer AS match_priority
            FROM mentions AS m
            JOIN dataset ON TRUE
            JOIN catalog.entity AS entity
              ON entity.dataset_version = :dataset_version
             AND entity.normalized_name = m.normalized_text
            LEFT JOIN catalog.product AS product
              ON product.dataset_version = entity.dataset_version
             AND product.entity_id = entity.entity_id

            UNION ALL

            SELECT m.mention_id, entity.entity_id, entity.canonical_name,
                   entity.entity_type, product.product_family,
                   'exact_alias'::text AS match_kind,
                   1000000::integer AS score, alias.alias_id AS source_id,
                   2::integer AS match_priority
            FROM mentions AS m
            JOIN dataset ON TRUE
            JOIN catalog.alias AS alias
              ON alias.dataset_version = :dataset_version
             AND alias.normalized_alias_text = m.normalized_text
             AND (alias.valid_from IS NULL OR alias.valid_from <= dataset.cutoff_date)
             AND (alias.valid_to IS NULL OR alias.valid_to >= dataset.cutoff_date)
            JOIN catalog.entity AS entity
              ON entity.dataset_version = alias.dataset_version
             AND entity.entity_id = alias.entity_id
            LEFT JOIN catalog.product AS product
              ON product.dataset_version = entity.dataset_version
             AND product.entity_id = entity.entity_id

            UNION ALL

            SELECT m.mention_id, entity.entity_id, entity.canonical_name,
                   entity.entity_type, product.product_family,
                   'trigram'::text AS match_kind,
                   floor(similarity(alias.normalized_alias_text, m.normalized_text) * 1000000)::integer AS score,
                   alias.alias_id AS source_id, 3::integer AS match_priority
            FROM mentions AS m
            JOIN dataset ON TRUE
            CROSS JOIN LATERAL (
                SELECT candidate_alias.*
                FROM catalog.alias AS candidate_alias
                WHERE candidate_alias.dataset_version = :dataset_version
                  AND (candidate_alias.valid_from IS NULL OR candidate_alias.valid_from <= dataset.cutoff_date)
                  AND (candidate_alias.valid_to IS NULL OR candidate_alias.valid_to >= dataset.cutoff_date)
                  AND similarity(candidate_alias.normalized_alias_text, m.normalized_text) >= :trigram_threshold
                ORDER BY similarity(candidate_alias.normalized_alias_text, m.normalized_text) DESC,
                         candidate_alias.entity_id ASC,
                         candidate_alias.alias_id ASC
                LIMIT {MAX_ENTITY_CANDIDATES_PER_MENTION}
            ) AS alias
            JOIN catalog.entity AS entity
              ON entity.dataset_version = alias.dataset_version
             AND entity.entity_id = alias.entity_id
            LEFT JOIN catalog.product AS product
              ON product.dataset_version = entity.dataset_version
             AND product.entity_id = entity.entity_id
        ),
        best_entity_matches AS (
            SELECT candidates.*,
                   row_number() OVER (
                       PARTITION BY mention_id, entity_id
                       ORDER BY match_priority ASC, score DESC, source_id ASC
                   ) AS entity_rank
            FROM candidates
        ),
        ranked_matches AS (
            SELECT best_entity_matches.*,
                   row_number() OVER (
                       PARTITION BY mention_id
                       ORDER BY match_priority ASC, score DESC, entity_id ASC, source_id ASC
                   ) AS mention_rank
            FROM best_entity_matches
            WHERE entity_rank = 1
        )
        SELECT mention_id, entity_id, canonical_name, entity_type, product_family,
               match_kind, score, source_id
        FROM ranked_matches
        WHERE mention_rank <= {MAX_ENTITY_CANDIDATES_PER_MENTION}
        ORDER BY mention_id ASC, mention_rank ASC
        """
    )
    return statement, parameters
