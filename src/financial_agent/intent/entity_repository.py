"""Dataset-pinned, bounded entity-candidate lookup."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.graph.entity_types import (
    EntityTypeProjectionError,
    ProductTypeFact,
    project_entity_ontology_type_ids,
)

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
            dataset_available = False
            for row in rows:
                if row["is_dataset_status"]:
                    if not row["dataset_exists"]:
                        raise ResolverCatalogUnavailable()
                    dataset_available = True
                    continue
                candidates[str(row["mention_id"])].append(
                    EntityCandidate(
                        entity_id=str(row["entity_id"]),
                        canonical_name=str(row["canonical_name"]),
                        ontology_type_ids=project_entity_ontology_type_ids(
                            entity_id=str(row["entity_id"]),
                            storage_entity_type=str(row["storage_entity_type"]),
                            product_family=(
                                str(row["product_family"])
                                if row["product_family"] is not None
                                else None
                            ),
                            security_kind=(
                                str(row["security_kind"])
                                if row["security_kind"] is not None
                                else None
                            ),
                            institution_kind=(
                                str(row["institution_kind"])
                                if row["institution_kind"] is not None
                                else None
                            ),
                            identifier_schemes=tuple(row["identifier_schemes"]),
                            product_type_facts=tuple(
                                ProductTypeFact(status, text_value, value_kind)
                                for status, text_value, value_kind in zip(
                                    row["product_type_statuses"],
                                    row["product_type_text_values"],
                                    row["product_type_value_kinds"],
                                    strict=True,
                                )
                            ),
                            is_share_class_subject=bool(row["is_share_class_subject"]),
                            is_share_class_object=bool(row["is_share_class_object"]),
                        ),
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
            if not dataset_available:
                raise ResolverCatalogUnavailable()
        except (
            EntityTypeProjectionError,
            KeyError,
            SQLAlchemyError,
            ValidationError,
        ) as error:
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
        dataset_status AS (
            SELECT EXISTS (SELECT 1 FROM dataset) AS dataset_exists
        ),
        candidates AS (
            SELECT m.mention_id, identifier.entity_id,
                   'exact_identifier'::text AS match_kind,
                   1000000::integer AS score, identifier.identifier_id AS source_id,
                   0::integer AS match_priority
            FROM mentions AS m
            JOIN dataset ON TRUE
            JOIN catalog.identifier AS identifier
              ON identifier.dataset_version = :dataset_version
             AND identifier.identifier_value = m.normalized_text
            UNION ALL

            SELECT m.mention_id, entity.entity_id,
                   'exact_name'::text AS match_kind,
                   1000000::integer AS score, entity.entity_id AS source_id,
                   1::integer AS match_priority
            FROM mentions AS m
            JOIN dataset ON TRUE
            JOIN catalog.entity AS entity
              ON entity.dataset_version = :dataset_version
             AND entity.normalized_name = m.normalized_text
            UNION ALL

            SELECT m.mention_id, alias.entity_id,
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
            UNION ALL

            SELECT m.mention_id, alias.entity_id,
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
        SELECT NULL::text AS mention_id, NULL::text AS entity_id,
               NULL::text AS canonical_name, NULL::text AS storage_entity_type,
               NULL::text AS product_family, NULL::text AS security_kind,
               NULL::text AS institution_kind,
               ARRAY[]::text[] AS identifier_schemes,
               ARRAY[]::text[] AS product_type_statuses,
               ARRAY[]::text[] AS product_type_text_values,
               ARRAY[]::text[] AS product_type_value_kinds,
               false AS is_share_class_subject,
               false AS is_share_class_object,
               NULL::text AS match_kind,
               NULL::integer AS score, NULL::text AS source_id,
               dataset_exists, true AS is_dataset_status, 0::integer AS output_rank
        FROM dataset_status

        UNION ALL

        SELECT ranked_matches.mention_id, ranked_matches.entity_id,
               entity.canonical_name, entity.entity_type AS storage_entity_type,
               product.product_family, security.security_kind,
               institution.institution_kind,
               ARRAY(
                   SELECT typed_identifier.scheme
                   FROM catalog.identifier AS typed_identifier
                   WHERE typed_identifier.dataset_version = :dataset_version
                     AND typed_identifier.entity_id = ranked_matches.entity_id
                     AND typed_identifier.scheme = 'PRFD_ITM_NO'
                   ORDER BY typed_identifier.scheme, typed_identifier.identifier_id
               ) AS identifier_schemes,
               ARRAY(
                   SELECT product_type.value_status
                   FROM observation.observation_record AS product_type
                   WHERE product_type.dataset_version = :dataset_version
                     AND product_type.entity_id = ranked_matches.entity_id
                     AND product_type.metric_id = 'product_type'
                   ORDER BY product_type.observation_id
               ) AS product_type_statuses,
               ARRAY(
                   SELECT product_type.text_value
                   FROM observation.observation_record AS product_type
                   WHERE product_type.dataset_version = :dataset_version
                     AND product_type.entity_id = ranked_matches.entity_id
                     AND product_type.metric_id = 'product_type'
                   ORDER BY product_type.observation_id
               ) AS product_type_text_values,
               ARRAY(
                   SELECT metric_definition.value_kind
                   FROM observation.observation_record AS product_type
                   JOIN observation.metric_definition AS metric_definition
                     ON metric_definition.metric_id = product_type.metric_id
                    AND metric_definition.definition_version = product_type.metric_definition_version
                   WHERE product_type.dataset_version = :dataset_version
                     AND product_type.entity_id = ranked_matches.entity_id
                     AND product_type.metric_id = 'product_type'
                   ORDER BY product_type.observation_id
               ) AS product_type_value_kinds,
               EXISTS (
                   SELECT 1 FROM relation.relation_record AS share_class
                   WHERE share_class.dataset_version = :dataset_version
                     AND share_class.predicate_id = 'hasShareClass'
                     AND share_class.subject_id = ranked_matches.entity_id
               ) AS is_share_class_subject,
               EXISTS (
                   SELECT 1 FROM relation.relation_record AS share_class
                   WHERE share_class.dataset_version = :dataset_version
                     AND share_class.predicate_id = 'hasShareClass'
                     AND share_class.object_id = ranked_matches.entity_id
               ) AS is_share_class_object,
               ranked_matches.match_kind, ranked_matches.score,
               ranked_matches.source_id, true AS dataset_exists,
               false AS is_dataset_status, mention_rank AS output_rank
        FROM ranked_matches
        JOIN catalog.entity AS entity
          ON entity.dataset_version = :dataset_version
         AND entity.entity_id = ranked_matches.entity_id
        LEFT JOIN catalog.product AS product
          ON product.dataset_version = entity.dataset_version
         AND product.entity_id = entity.entity_id
        LEFT JOIN catalog.security AS security
          ON security.dataset_version = entity.dataset_version
         AND security.entity_id = entity.entity_id
        LEFT JOIN catalog.institution AS institution
          ON institution.dataset_version = entity.dataset_version
         AND institution.entity_id = entity.entity_id
        WHERE mention_rank <= {MAX_ENTITY_CANDIDATES_PER_MENTION}
        ORDER BY is_dataset_status DESC, mention_id ASC, output_rank ASC
        """
    )
    return statement, parameters
