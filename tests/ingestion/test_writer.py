from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import encode_contract_value
from financial_agent.ingestion.mapping.common import make_record_hash
from financial_agent.ingestion.models import MappedRow
from financial_agent.ingestion.writer import (
    DatasetBuildConflict,
    DatasetBuildRoleError,
    DatasetBuildStateError,
    DatasetBuildWriter,
)


CUTOFF_DATE = date(2026, 7, 11)
MANIFEST_HASH = "a" * 64
APPROVED_AT = datetime(2026, 8, 20, tzinfo=UTC)


def _hashed(payload: dict[str, object]) -> dict[str, object]:
    record = dict(payload)
    record["record_hash"] = make_record_hash(payload)
    return record


def _tag(value: object) -> dict[str, object]:
    return encode_contract_value(value).model_dump(mode="json")


def _synthetic_row(
    token: str,
    *,
    product_name: str = "Synthetic Product",
    include_extra_alias: bool = False,
) -> MappedRow:
    publisher_id = f"publisher-{token}"
    product_id = f"product-{token}"
    source_id = f"source-{token}"
    relation_id = f"relation-{token}"
    observation_id = f"observation-{token}"
    relation_evidence_id = f"evidence-relation-{token}"
    observation_evidence_id = f"evidence-observation-{token}"
    metric_payload: dict[str, object] = {
        "metric_id": "synthetic.organizer.net_assets",
        "definition_version": "1",
        "semantic_family": "synthetic_organizer",
        "value_kind": "numeric",
        "default_unit": "won",
        "description": "Synthetic organizer amount",
        "approved_at": APPROVED_AT,
    }
    metric_payload["definition_hash"] = make_record_hash(metric_payload)

    alias_rows = [
        _hashed(
            {
                "alias_id": f"alias-{token}",
                "entity_id": product_id,
                "alias_text": "Synthetic Alias",
                "normalized_alias_text": "Synthetic Alias",
                "valid_from": None,
                "valid_to": None,
            }
        )
    ]
    if include_extra_alias:
        alias_rows.append(
            _hashed(
                {
                    "alias_id": f"alias-extra-{token}",
                    "entity_id": product_id,
                    "alias_text": "Synthetic Extra Alias",
                    "normalized_alias_text": "Synthetic Extra Alias",
                    "valid_from": None,
                    "valid_to": None,
                }
            )
        )

    relation_payload = _hashed(
        {
            "relation_id": relation_id,
            "subject_id": product_id,
            "predicate_id": "managedBy",
            "object_id": publisher_id,
            "valid_from": None,
            "valid_to": None,
        }
    )
    observation_payload = _hashed(
        {
            "observation_id": observation_id,
            "entity_id": product_id,
            "relation_id": None,
            "metric_id": metric_payload["metric_id"],
            "metric_definition_version": "1",
            "value_status": "present",
            "numeric_value": Decimal("50000000000"),
            "text_value": None,
            "boolean_value": None,
            "date_value": None,
            "timestamp_value": None,
            "unit": "won",
            "currency": "KRW",
            "period_start": None,
            "period_end": None,
            "applicable_date": CUTOFF_DATE,
            "published_at": None,
            "available_at": None,
            "vintage_date": CUTOFF_DATE,
            "reason_code": None,
        }
    )

    def evidence_payload(
        evidence_id: str,
        evidence_kind: str,
        predicate_id: str,
        value: object,
        column: str,
    ) -> dict[str, object]:
        return _hashed(
            {
                "evidence_id": evidence_id,
                "evidence_kind": evidence_kind,
                "source_id": source_id,
                "subject_id": product_id,
                "predicate_id": predicate_id,
                "value_or_object_id": _tag(value),
                "normalized_value": _tag(value),
                "unit": "won" if evidence_kind == "observation" else None,
                "currency": "KRW" if evidence_kind == "observation" else None,
                "applicable_date": CUTOFF_DATE,
                "valid_from": None,
                "valid_to": None,
                "published_at": None,
                "available_at": None,
                "vintage_date": CUTOFF_DATE,
                "locator_type": "tabular",
                "locator_uri_or_object_key": "synthetic-workbook.xlsx",
                "locator_record_key": f"record-{token}",
                "locator_sheet": "datarows",
                "locator_row": 7,
                "locator_column": column,
                "locator_page": None,
                "locator_section": None,
                "locator_sentence_start": None,
                "locator_sentence_end": None,
                "raw_value_repr": str(value),
                "parser_version": "1",
                "mapping_version": "1",
                "cutoff_status": "eligible",
                "scope_completeness": None,
            }
        )

    records: dict[str, tuple[dict[str, object], ...]] = {
        "catalog.entity": (
            _hashed(
                {
                    "entity_id": publisher_id,
                    "entity_type": "institution",
                    "canonical_name": "Synthetic Organizer",
                    "normalized_name": "Synthetic Organizer",
                }
            ),
            _hashed(
                {
                    "entity_id": product_id,
                    "entity_type": "product",
                    "canonical_name": product_name,
                    "normalized_name": product_name,
                }
            ),
        ),
        "catalog.institution": (
            {
                "entity_id": publisher_id,
                "institution_kind": "organizer",
            },
        ),
        "catalog.product": (
            {
                "entity_id": product_id,
                "product_family": "public_fund",
                "primary_currency": "KRW",
            },
        ),
        "evidence.source_record": (
            _hashed(
                {
                    "source_id": source_id,
                    "publisher": publisher_id,
                    "publisher_type": "organizer",
                    "source_title": "Synthetic organizer source",
                    "source_type": "dataset",
                    "authority_tier": "organizer",
                    "source_locator_root": "synthetic/root",
                    "content_checksum": "b" * 64,
                    "license_or_usage_note": "synthetic test use",
                    "eligible_for_claim": True,
                }
            ),
        ),
        "observation.metric_definition": (metric_payload,),
        "catalog.identifier": (
            _hashed(
                {
                    "identifier_id": f"identifier-{token}",
                    "entity_id": product_id,
                    "scheme": "SYNTHETIC_PRODUCT",
                    "identifier_value": f"SYN-{token}",
                    "is_primary": True,
                    "valid_from": None,
                    "valid_to": None,
                }
            ),
        ),
        "catalog.alias": tuple(alias_rows),
        "relation.relation_record": (relation_payload,),
        "observation.observation_record": (observation_payload,),
        "evidence.evidence_record": (
            evidence_payload(
                relation_evidence_id,
                "relation",
                "managedBy",
                publisher_id,
                "manager",
            ),
            evidence_payload(
                observation_evidence_id,
                "observation",
                str(metric_payload["metric_id"]),
                Decimal("50000000000"),
                "net_assets",
            ),
        ),
        "evidence.evidence_relation_origin": (
            {
                "evidence_id": relation_evidence_id,
                "relation_id": relation_id,
            },
        ),
        "evidence.evidence_observation_origin": (
            {
                "evidence_id": observation_evidence_id,
                "observation_id": observation_id,
            },
        ),
    }
    return MappedRow(
        row_number=7,
        disposition="accepted",
        records_by_table=records,
        issues=(),
    )


def _changed_name(row: MappedRow, name: str) -> MappedRow:
    entities = list(row.records_by_table["catalog.entity"])
    product = dict(entities[1])
    product["canonical_name"] = name
    product["normalized_name"] = name
    product["record_hash"] = make_record_hash(
        {key: value for key, value in product.items() if key != "record_hash"}
    )
    entities[1] = product
    records = dict(row.records_by_table)
    records["catalog.entity"] = tuple(entities)
    return MappedRow(
        row_number=row.row_number,
        disposition=row.disposition,
        records_by_table=records,
        issues=row.issues,
    )


async def _create_dataset(writer: DatasetBuildWriter, token: str) -> str:
    dataset_version = f"writer-{token}"
    await writer.create_building_dataset(
        dataset_version,
        MANIFEST_HASH,
        CUTOFF_DATE,
    )
    return dataset_version


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_batch_writes_in_fk_order_and_links_evidence_origins(
    ingestion_build_engine: AsyncEngine,
) -> None:
    token = uuid4().hex
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset_version = await _create_dataset(writer, token)

    await writer.write_rows(dataset_version, [_synthetic_row(token)])

    counts = await writer.table_counts(dataset_version)
    assert counts == {
        "catalog.alias": 1,
        "catalog.entity": 2,
        "catalog.identifier": 1,
        "catalog.institution": 1,
        "catalog.product": 1,
        "catalog.security": 0,
        "evidence.evidence_observation_origin": 1,
        "evidence.evidence_record": 2,
        "evidence.evidence_relation_origin": 1,
        "evidence.source_record": 1,
        "observation.metric_definition": 1,
        "observation.observation_record": 1,
        "relation.relation_record": 1,
    }


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_identical_batch_retry_converges(
    ingestion_build_engine: AsyncEngine,
) -> None:
    token = uuid4().hex
    row = _synthetic_row(token)
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset_version = await _create_dataset(writer, token)

    await writer.write_rows(dataset_version, [row])
    first_counts = await writer.table_counts(dataset_version)
    await writer.write_rows(dataset_version, [row])

    assert await writer.table_counts(dataset_version) == first_counts


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_same_id_different_payload_rolls_back_whole_batch(
    ingestion_build_engine: AsyncEngine,
) -> None:
    token = uuid4().hex
    original = _synthetic_row(token)
    changed = _changed_name(
        _synthetic_row(token, include_extra_alias=True),
        "Changed Product",
    )
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset_version = await _create_dataset(writer, token)
    await writer.write_rows(dataset_version, [original])

    with pytest.raises(DatasetBuildConflict) as failure:
        await writer.write_rows(dataset_version, [changed])

    assert failure.value.code == "BUILD_PAYLOAD_CONFLICT"
    assert (await writer.table_counts(dataset_version))["catalog.alias"] == 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_batch_duplicate_ids_require_the_complete_same_payload(
    ingestion_build_engine: AsyncEngine,
) -> None:
    token = uuid4().hex
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset_version = await _create_dataset(writer, token)

    with pytest.raises(DatasetBuildConflict):
        await writer.write_rows(
            dataset_version,
            [_synthetic_row(token), _changed_name(_synthetic_row(token), "Other")],
        )

    assert (await writer.table_counts(dataset_version))["catalog.entity"] == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_writer_rejects_nonbuilding_dataset(
    ingestion_build_engine: AsyncEngine,
    ingestion_admin_engine: AsyncEngine,
) -> None:
    token = uuid4().hex
    writer = DatasetBuildWriter(ingestion_build_engine)
    dataset_version = await _create_dataset(writer, token)
    validation_run_id = f"validation-{token}"
    now = datetime.now(UTC)
    async with ingestion_admin_engine.begin() as connection:
        await connection.execute(
            sa.text(
                """
                INSERT INTO operations.dataset_validation_run (
                    validation_run_id, dataset_version, dataset_manifest_hash,
                    validator_id, validator_version, started_at, finished_at,
                    status, report_hash
                ) VALUES (
                    :validation_run_id, :dataset_version, :manifest_hash,
                    'synthetic-validator', '1', :started_at, :finished_at,
                    'pass', :report_hash
                )
                """
            ),
            {
                "validation_run_id": validation_run_id,
                "dataset_version": dataset_version,
                "manifest_hash": MANIFEST_HASH,
                "started_at": now,
                "finished_at": now + timedelta(seconds=1),
                "report_hash": "c" * 64,
            },
        )
        await connection.execute(
            sa.text("SELECT operations.finish_dataset_validation(:run_id)"),
            {"run_id": validation_run_id},
        )

    with pytest.raises(DatasetBuildStateError):
        await writer.write_rows(dataset_version, [_synthetic_row(token)])


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_runtime_role_cannot_use_writer_path(
    ingestion_runtime_engine: AsyncEngine,
    ingestion_admin_engine: AsyncEngine,
) -> None:
    token = uuid4().hex
    dataset_version = f"writer-runtime-{token}"
    writer = DatasetBuildWriter(ingestion_runtime_engine)

    with pytest.raises(DatasetBuildRoleError):
        await writer.create_building_dataset(
            dataset_version,
            MANIFEST_HASH,
            CUTOFF_DATE,
        )

    async with ingestion_admin_engine.connect() as connection:
        count = await connection.scalar(
            sa.text(
                "SELECT count(*) FROM operations.dataset_version "
                "WHERE dataset_version = :dataset_version"
            ),
            {"dataset_version": dataset_version},
        )
    assert count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_two_connections_same_batch_converge_or_conflict_stably(
    ingestion_build_engine: AsyncEngine,
) -> None:
    same_token = uuid4().hex
    writer_one = DatasetBuildWriter(ingestion_build_engine)
    writer_two = DatasetBuildWriter(ingestion_build_engine)
    same_dataset = await _create_dataset(writer_one, same_token)
    same_row = _synthetic_row(same_token)

    assert await asyncio.gather(
        writer_one.write_rows(same_dataset, [same_row]),
        writer_two.write_rows(same_dataset, [same_row]),
    ) == [None, None]
    assert (await writer_one.table_counts(same_dataset))["catalog.entity"] == 2

    conflict_token = uuid4().hex
    conflict_dataset = await _create_dataset(writer_one, conflict_token)
    results = await asyncio.gather(
        writer_one.write_rows(conflict_dataset, [_synthetic_row(conflict_token)]),
        writer_two.write_rows(
            conflict_dataset,
            [_changed_name(_synthetic_row(conflict_token), "Conflicting Product")],
        ),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    conflicts = [result for result in results if isinstance(result, Exception)]
    assert len(conflicts) == 1
    assert isinstance(conflicts[0], DatasetBuildConflict)
