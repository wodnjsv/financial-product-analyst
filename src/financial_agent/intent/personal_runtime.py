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
