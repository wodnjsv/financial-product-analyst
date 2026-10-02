"""Bounded, catalog-grounded entity spans from the original request text."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts.request import NamedEntityMention, RequestContext

from .candidates import MAX_ENTITY_MENTIONS
from .entity_repository import ResolverCatalogUnavailable
from .normalization import (
    MAX_QUESTION_CODE_POINTS,
    NormalizedSegment,
    normalize_request,
)


MAX_CATALOG_SURFACES = MAX_ENTITY_MENTIONS * 4
_GENERIC_SURFACES = frozenset(
    {"ETF", "ETN", "펀드", "채권", "주식", "미국", "국내", "해외", "상품", "전자", "후자"}
)


class EntityDiscoveryError(ValueError):
    """Source coverage could not be preserved within the request bounds."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _CompactSegment:
    segment: NormalizedSegment
    text: str
    origins: tuple[tuple[int, int], ...]


class EntityMentionDiscovery:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def discover(self, context: RequestContext) -> tuple[NamedEntityMention, ...]:
        """Find exact catalog surfaces; leave identity and semantic roles unresolved.

        A single dataset-pinned lookup returns only matching lexical surfaces,
        rather than transferring or caching the entity catalog. Repeated spans
        keep distinct source offsets. Candidate identity/type projection remains
        the responsibility of EntityCandidateRepository.
        """

        normalized = normalize_request(context)
        if (
            sum(len(segment.original_text) for segment in normalized.segments)
            > MAX_QUESTION_CODE_POINTS
        ):
            raise EntityDiscoveryError("ENTITY_DISCOVERY_INPUT_LIMIT_EXCEEDED")
        segments = tuple(_compact_segment(segment) for segment in normalized.segments)
        if not segments:
            return ()
        statement, parameters = _discovery_statement(context.dataset_version, segments)
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                    await connection.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
                    rows = (
                        (await connection.execute(statement, parameters))
                        .mappings()
                        .all()
                    )
            surfaces: set[str] = set()
            dataset_available = False
            for row in rows:
                if row["is_dataset_status"]:
                    if not row["dataset_exists"]:
                        raise ResolverCatalogUnavailable()
                    dataset_available = True
                elif isinstance(row["surface"], str) and row["surface"]:
                    surfaces.add(row["surface"])
                else:
                    raise ResolverCatalogUnavailable()
            if not dataset_available:
                raise ResolverCatalogUnavailable()
        except (SQLAlchemyError, KeyError, TypeError) as error:
            raise ResolverCatalogUnavailable() from error
        if len(surfaces) > MAX_CATALOG_SURFACES:
            raise EntityDiscoveryError("ENTITY_DISCOVERY_SURFACE_LIMIT_EXCEEDED")

        mentions: list[NamedEntityMention] = []
        for compact in segments:
            spans = _source_spans(compact, surfaces)
            for start, end in spans:
                mentions.append(
                    NamedEntityMention(
                        mention_id=f"mention-{compact.segment.segment_id}-{start}-{end}",
                        segment_id=compact.segment.segment_id,
                        text=compact.segment.original_text[start:end],
                        expected_entity_types=(),
                        start_char=start,
                        end_char=end,
                    )
                )
        if len(mentions) > MAX_ENTITY_MENTIONS:
            raise EntityDiscoveryError("ENTITY_MENTION_LIMIT_EXCEEDED")
        return tuple(mentions)


def _compact_segment(segment: NormalizedSegment) -> _CompactSegment:
    characters: list[str] = []
    origins: list[tuple[int, int]] = []
    for character, origin in zip(
        segment.normalized_text, segment.origin_spans, strict=True
    ):
        if not character.isspace():
            for upper_character in character.upper():
                characters.append(upper_character)
                origins.append(origin)
    return _CompactSegment(segment, "".join(characters), tuple(origins))


def _source_spans(
    compact: _CompactSegment, surfaces: set[str]
) -> tuple[tuple[int, int], ...]:
    ranges: set[tuple[int, int]] = set()
    original = compact.segment.original_text
    for surface in sorted(surfaces, key=lambda item: (-len(item), item)):
        if len(surface) < 2 or surface in _GENERIC_SURFACES:
            continue
        position = compact.text.find(surface)
        while position >= 0:
            start = compact.origins[position][0]
            end = compact.origins[position + len(surface) - 1][1]
            # Never turn a partial NFKC expansion into a different source name.
            source_key = "".join(
                unicodedata.normalize("NFKC", original[start:end]).split()
            ).upper()
            if (
                source_key == surface
                and _ascii_boundaries(original, start, end, surface)
                and not any(
                    other_start <= start and end <= other_end
                    for other_start, other_end in ranges
                )
            ):
                ranges.add((start, end))
                if len(ranges) > MAX_ENTITY_MENTIONS:
                    raise EntityDiscoveryError("ENTITY_MENTION_LIMIT_EXCEEDED")
            position = compact.text.find(surface, position + 1)
    # Prefer full names over nested aliases, while preserving crossing spans and
    # independent occurrences of the shorter name elsewhere in the question.
    return tuple(sorted(ranges))


def _ascii_boundaries(original: str, start: int, end: int, surface: str) -> bool:
    def is_ascii_word(character: str) -> bool:
        normalized = unicodedata.normalize("NFKC", character)
        return bool(normalized) and all(
            item.isascii() and (item.isalnum() or item == "_")
            for item in normalized
        )

    return not (
        (
            is_ascii_word(surface[0])
            and start > 0
            and is_ascii_word(original[start - 1])
        )
        or (
            is_ascii_word(surface[-1])
            and end < len(original)
            and is_ascii_word(original[end])
        )
    )


def _discovery_statement(
    dataset_version: str, segments: Sequence[_CompactSegment]
) -> tuple[sa.TextClause, dict[str, object]]:
    values = ", ".join(f"(:segment_text_{index})" for index, _ in enumerate(segments))
    parameters: dict[str, object] = {
        "dataset_version": dataset_version,
        "surface_limit": MAX_CATALOG_SURFACES + 1,
        "generic_surfaces": sorted(_GENERIC_SURFACES),
    }
    parameters.update(
        {
            f"segment_text_{index}": segment.text
            for index, segment in enumerate(segments)
        }
    )
    return sa.text(
        f"""
        WITH segments(compact_text) AS (VALUES {values}),
        dataset AS (
            SELECT cutoff_date FROM operations.dataset_version
            WHERE dataset_version = :dataset_version
        ),
        names AS (
            SELECT entity.normalized_name AS surface
            FROM catalog.entity AS entity JOIN dataset ON TRUE
            WHERE entity.dataset_version = :dataset_version
              AND entity.entity_type IN ('product', 'security', 'company', 'institution')
            UNION ALL
            SELECT alias.normalized_alias_text AS surface
            FROM catalog.alias AS alias
            JOIN catalog.entity AS entity
              ON entity.dataset_version = alias.dataset_version
             AND entity.entity_id = alias.entity_id
            JOIN dataset ON TRUE
            WHERE alias.dataset_version = :dataset_version
              AND entity.entity_type IN ('product', 'security', 'company', 'institution')
              AND (alias.valid_from IS NULL OR alias.valid_from <= dataset.cutoff_date)
              AND (alias.valid_to IS NULL OR alias.valid_to >= dataset.cutoff_date)
            UNION ALL
            SELECT identifier.identifier_value AS surface
            FROM catalog.identifier AS identifier
            JOIN catalog.entity AS entity
              ON entity.dataset_version = identifier.dataset_version
             AND entity.entity_id = identifier.entity_id
            JOIN dataset ON TRUE
            WHERE identifier.dataset_version = :dataset_version
              AND entity.entity_type IN ('product', 'security', 'company', 'institution')
        ),
        compact_names AS (
            SELECT DISTINCT upper(regexp_replace(surface, '[[:space:]]', '', 'g')) AS surface
            FROM names
        ),
        matched AS (
            SELECT surface FROM compact_names
            WHERE length(surface) >= 2
              AND NOT (surface = ANY(CAST(:generic_surfaces AS text[])))
              AND EXISTS (
                  SELECT 1 FROM segments WHERE position(surface IN compact_text) > 0
              )
            ORDER BY length(surface) DESC, surface ASC
            LIMIT :surface_limit
        )
        SELECT NULL::text AS surface,
               EXISTS(SELECT 1 FROM dataset) AS dataset_exists,
               true AS is_dataset_status
        UNION ALL
        SELECT surface, true AS dataset_exists, false AS is_dataset_status FROM matched
        ORDER BY is_dataset_status DESC, surface ASC
        """
    ), parameters
