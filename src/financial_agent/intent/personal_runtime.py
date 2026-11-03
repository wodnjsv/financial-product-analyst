"""Build the NVIDIA personal resolver from actual read-only dataset metadata."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.planning.physical_bindings import (
    load_physical_binding_registry,
    load_semantic_sql_policy_registry,
)
from financial_agent.planning.registry import load_planning_registry
from financial_agent.planning.semantic_compiler import SemanticPlanningCompiler

from .catalog import load_hybrid_catalog
from .entity_discovery import EntityMentionDiscovery
from .entity_repository import EntityCandidateRepository, ResolverCatalogUnavailable
from .nvidia import NvidiaStructuredOutputAdapter
from .nvidia_config import NvidiaResolverConfig
from .personal import PersonalIntentService
from .query_contract_registry import load_query_contract_registry
from .service import IntentResolverService
from .semantic_defaults import (
    DatasetSemanticDefaultsV1, SemanticAsOfDefaultV1,
    load_semantic_default_policy_registry,
)
from .view import (
    HYBRID_CANDIDATE_POLICY_VERSION,
    HYBRID_PROMPT_VERSION,
    HYBRID_RESOLVER_SCHEMA_VERSION,
    NORMALIZER_VERSION,
    NVIDIA_HYBRID_ADAPTER_VERSION,
    ActiveDatasetPin,
    build_hybrid_manifest,
)


async def create_personal_intent_service(
    project_root: Path,
    engine: AsyncEngine,
    config: NvidiaResolverConfig,
    dataset_version: str = "personal-2026-08-24-v1",
) -> PersonalIntentService:
    """Read a pinned building/validated/active dataset without activating it."""
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(sa.text("SET TRANSACTION READ ONLY"))
                await connection.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
                row = (
                    await connection.execute(
                        sa.text(
                            "SELECT dataset_version, manifest_hash, cutoff_date, status "
                            "FROM operations.dataset_version "
                            "WHERE dataset_version = :dataset_version"
                        ),
                        {"dataset_version": dataset_version},
                    )
                ).mappings().one_or_none()
        if (
            row is None
            or row["dataset_version"] != dataset_version
            or row["status"] not in ("building", "validated", "active")
            or type(row["cutoff_date"]) is not date
        ):
            raise ResolverCatalogUnavailable()
        pin = ActiveDatasetPin(
            dataset_version=dataset_version,
            manifest_hash=row["manifest_hash"],
        )
        cutoff_date = row["cutoff_date"]
    except (SQLAlchemyError, KeyError, TypeError, ValueError):
        raise ResolverCatalogUnavailable() from None

    catalog = load_hybrid_catalog(project_root)
    defaults = await _source_date_defaults(engine, pin, cutoff_date)
    resolver = IntentResolverService(
        adapter=NvidiaStructuredOutputAdapter(config),
        entity_repository=EntityCandidateRepository(engine),
        catalog=catalog,
        manifest=build_hybrid_manifest(
            catalog,
            {
                "normalizer_version": NORMALIZER_VERSION,
                "candidate_policy_version": HYBRID_CANDIDATE_POLICY_VERSION,
                "resolver_schema_version": HYBRID_RESOLVER_SCHEMA_VERSION,
                "prompt_version": HYBRID_PROMPT_VERSION,
                "adapter_version": NVIDIA_HYBRID_ADAPTER_VERSION,
            },
        ),
        active_dataset_pin=pin,
        query_contract_registry=load_query_contract_registry(project_root),
        semantic_default_registry=load_semantic_default_policy_registry(project_root),
        dataset_semantic_defaults=defaults,
    )
    compiler = SemanticPlanningCompiler(
        load_physical_binding_registry(project_root),
        load_semantic_sql_policy_registry(project_root),
        load_planning_registry(project_root),
    )
    return PersonalIntentService(
        resolver=resolver,
        discovery=EntityMentionDiscovery(engine),
        compiler=compiler,
        pin=pin,
        cutoff_date=cutoff_date,
        model_id=config.model_id,
    )


_DATE_DEFAULT_METRICS = {
    'organizer.pref02n001.aum': ('overseas_etf', 'aum'),
    'organizer.prbd01n001.remaining_days': ('domestic_bond', 'remaining_days'),
}


async def _source_date_defaults(engine, pin, cutoff_date):
    """Only a single actual date can become a server-side pinned default."""
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(sa.text('SET TRANSACTION READ ONLY'))
                await connection.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
                rows = (await connection.execute(sa.text('''
                    SELECT o.metric_id, p.product_family,
                           min(o.applicable_date) AS first_date,
                           max(o.applicable_date) AS last_date,
                           count(*) AS observation_count,
                           count(o.applicable_date) AS dated_count
                    FROM observation.observation_record o
                    JOIN catalog.product p ON p.dataset_version=o.dataset_version
                      AND p.entity_id=o.entity_id
                    WHERE o.dataset_version=:dataset_version
                      AND o.metric_definition_version='2'
                      AND o.metric_id=ANY(CAST(:metric_ids AS text[]))
                    GROUP BY o.metric_id, p.product_family
                '''), {'dataset_version': pin.dataset_version,
                       'metric_ids': list(_DATE_DEFAULT_METRICS)})).mappings().all()
    except SQLAlchemyError:
        raise ResolverCatalogUnavailable() from None
    defaults = []
    for row in rows:
        pair = _DATE_DEFAULT_METRICS.get(row['metric_id'])
        actual_date = row['first_date']
        if (pair is None or row['product_family'] != pair[0]
                or type(actual_date) is not date or actual_date != row['last_date']
                or actual_date > cutoff_date or row['observation_count'] == 0
                or row['dated_count'] != row['observation_count']):
            continue
        defaults.append(SemanticAsOfDefaultV1(
            default_record_id=f'{pin.dataset_version}-{pair[0]}-{pair[1]}',
            product_family_id=pair[0], semantic_id=pair[1], as_of_date=actual_date,
        ))
    return DatasetSemanticDefaultsV1(
        dataset_version=pin.dataset_version, manifest_hash=pin.manifest_hash,
        defaults=tuple(sorted(defaults, key=lambda item: item.default_record_id)),
    )
