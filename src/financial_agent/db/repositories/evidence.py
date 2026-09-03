from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Literal, TypeVar

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from financial_agent.contracts import (
    AtomicClaim,
    CalculationRecord,
    ClaimSupport,
    ClaimType,
    EvidenceRecord,
    SourceRecord,
    canonical_json_bytes,
    canonical_sha256,
    decode_contract_value,
    encode_contract_value,
)
from financial_agent.db.schema.evidence import (
    atomic_claim,
    calculation_dependency,
    calculation_evidence_input,
    calculation_exclusion,
    calculation_parameter,
    calculation_population,
    calculation_population_filter,
    calculation_record,
    claim_qualifier,
    claim_support,
    evidence_document_origin,
    evidence_observation_origin,
    evidence_record,
    evidence_relation_origin,
    source_record,
)
from financial_agent.db.schema.operations import request_run


_ContractModel = TypeVar("_ContractModel", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class RequestScope:
    request_key: str
    run_id: str
    dataset_version: str


@dataclass(frozen=True, slots=True)
class OriginReference:
    origin_kind: Literal["observation", "relation", "document_chunk"]
    dataset_version: str
    record_id: str


class EvidenceLedgerConflict(RuntimeError):
    code = "EVIDENCE_LEDGER_CONFLICT"

    def __init__(self, artifact_type: str, identity: str) -> None:
        super().__init__(f"{self.code}: {artifact_type} {identity} has different payload")


class RequestScopeMismatch(ValueError):
    code = "REQUEST_SCOPE_MISMATCH"

    def __init__(self) -> None:
        super().__init__(self.code)


class EvidenceLedgerNotFound(LookupError):
    code = "EVIDENCE_LEDGER_NOT_FOUND"

    def __init__(self, artifact_type: str, identity: str) -> None:
        super().__init__(f"{self.code}: {artifact_type} {identity}")


_CLAIM_SUBJECT_KIND: dict[ClaimType, Literal["entity", "request"]] = {
    ClaimType.DIRECT_FACT: "entity",
    ClaimType.RELATION: "entity",
    ClaimType.DERIVED_METRIC: "entity",
    ClaimType.RANK: "entity",
    ClaimType.SIMILARITY: "entity",
    ClaimType.NO_MATCH: "request",
    ClaimType.DATA_LIMITATION: "request",
    ClaimType.POLICY_BOUNDARY: "request",
}

_ORIGIN_TABLES = {
    "observation": (evidence_observation_origin, "observation_id"),
    "relation": (evidence_relation_origin, "relation_id"),
    "document_chunk": (evidence_document_origin, "chunk_id"),
}


def _is_unique_violation(error: IntegrityError) -> bool:
    return getattr(error.orig, "sqlstate", None) == "23505"


def _dump_tagged_value(value: object) -> dict[str, object]:
    decoded = decode_contract_value(value)  # type: ignore[arg-type]
    return encode_contract_value(decoded).model_dump(mode="json")


def _validate_contract_json(
    model_type: type[_ContractModel], payload: dict[str, object]
) -> _ContractModel:
    return model_type.model_validate_json(
        json.dumps(payload, ensure_ascii=False, default=_json_default)
    )


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("database datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _model_bytes(model: BaseModel) -> bytes:
    return canonical_json_bytes(model.model_dump(mode="json"))


def _models_bytes(models: tuple[BaseModel, ...]) -> bytes:
    return canonical_json_bytes(
        {"items": [model.model_dump(mode="json") for model in models]}
    )


def _evidence_bytes(
    evidence: EvidenceRecord, origin: OriginReference | None
) -> bytes:
    return canonical_json_bytes(
        {
            "evidence": evidence.model_dump(mode="json"),
            "origin": asdict(origin) if origin is not None else None,
        }
    )


class EvidenceLedgerRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append_source(
        self, dataset_version: str, source: SourceRecord
    ) -> None:
        payload = source.model_dump(mode="json")
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await connection.execute(
                        sa.insert(source_record).values(
                            dataset_version=dataset_version,
                            source_id=payload["source_id"],
                            publisher=payload["publisher"],
                            publisher_type=payload["publisher_type"],
                            source_title=payload["source_title"],
                            source_type=payload["source_type"],
                            authority_tier=payload["authority_tier"],
                            source_locator_root=payload["source_locator_root"],
                            content_checksum=payload["content_checksum"],
                            license_or_usage_note=payload["license_or_usage_note"],
                            eligible_for_claim=payload["eligible_for_claim"],
                            record_hash=canonical_sha256(source),
                            created_at=datetime.now(UTC),
                        )
                    )
                    await self._force_constraints(connection)
        except IntegrityError as error:
            if not _is_unique_violation(error):
                raise
            try:
                existing = await self._get_source(dataset_version, source.source_id)
            except EvidenceLedgerNotFound:
                raise error from None
            if _model_bytes(existing) == _model_bytes(source):
                return
            raise EvidenceLedgerConflict(
                "SourceRecord", f"{dataset_version}/{source.source_id}"
            ) from error

    async def append_evidence(
        self,
        evidence: EvidenceRecord,
        *,
        origin: OriginReference | None = None,
    ) -> None:
        if origin is not None and origin.dataset_version != evidence.dataset_version:
            raise ValueError("origin dataset_version must match EvidenceRecord")
        payload = evidence.model_dump(mode="json")
        locator = payload["source_locator"]
        assert isinstance(locator, dict)
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await connection.execute(
                        sa.insert(evidence_record).values(
                            dataset_version=payload["dataset_version"],
                            evidence_id=payload["evidence_id"],
                            evidence_kind=payload["evidence_kind"],
                            source_id=payload["source_id"],
                            subject_id=payload["subject_id"],
                            predicate_id=payload["predicate_id"],
                            value_or_object_id=_dump_tagged_value(
                                evidence.value_or_object_id
                            ),
                            normalized_value=_dump_tagged_value(
                                evidence.normalized_value
                            ),
                            unit=payload["unit"],
                            currency=payload["currency"],
                            applicable_date=payload["applicable_date"],
                            valid_from=payload["valid_from"],
                            valid_to=payload["valid_to"],
                            published_at=payload["published_at"],
                            available_at=payload["available_at"],
                            vintage_date=payload["vintage_date"],
                            locator_type=locator["locator_type"],
                            locator_uri_or_object_key=locator["uri_or_object_key"],
                            locator_record_key=locator["record_key"],
                            locator_sheet=locator["sheet"],
                            locator_row=locator["row"],
                            locator_column=locator["column"],
                            locator_page=locator["page"],
                            locator_section=locator["section"],
                            locator_sentence_start=locator["sentence_start"],
                            locator_sentence_end=locator["sentence_end"],
                            raw_value_repr=payload["raw_value_repr"],
                            parser_version=payload["parser_version"],
                            mapping_version=payload["mapping_version"],
                            cutoff_status=payload["cutoff_status"],
                            record_hash=payload["record_hash"],
                            scope_completeness=payload["scope_completeness"],
                            created_at=datetime.now(UTC),
                        )
                    )
                    if origin is not None:
                        origin_table, record_column = _ORIGIN_TABLES[
                            origin.origin_kind
                        ]
                        await connection.execute(
                            sa.insert(origin_table).values(
                                dataset_version=origin.dataset_version,
                                evidence_id=evidence.evidence_id,
                                **{record_column: origin.record_id},
                            )
                        )
                    await self._force_constraints(connection)
        except IntegrityError as error:
            if not _is_unique_violation(error):
                raise
            try:
                existing = await self.get_evidence(
                    evidence.dataset_version, evidence.evidence_id
                )
            except EvidenceLedgerNotFound:
                raise error from None
            existing_origin = await self._get_origin(
                evidence.dataset_version, evidence.evidence_id
            )
            if _evidence_bytes(existing, existing_origin) == _evidence_bytes(
                evidence, origin
            ):
                return
            raise EvidenceLedgerConflict(
                "EvidenceRecord",
                f"{evidence.dataset_version}/{evidence.evidence_id}",
            ) from error

    async def append_calculation(
        self, scope: RequestScope, calculation: CalculationRecord
    ) -> None:
        payload = calculation.model_dump(mode="json")
        created_at = datetime.now(UTC)
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await self._require_scope(connection, scope)
                    await connection.execute(
                        sa.insert(calculation_record).values(
                            run_id=scope.run_id,
                            dataset_version=scope.dataset_version,
                            calculation_id=payload["calculation_id"],
                            calculation_type=payload["calculation_type"],
                            formula_id=payload["formula_id"],
                            formula_version=payload["formula_version"],
                            tie_break_rule=payload["tie_break_rule"],
                            result_value=_dump_tagged_value(
                                calculation.result_value
                            ),
                            unit=payload["unit"],
                            currency=payload["currency"],
                            rounding_rule=payload["rounding_rule"],
                            calculation_hash=payload["calculation_hash"],
                            created_at=created_at,
                        )
                    )
                    await self._insert_calculation_associations(
                        connection, scope, calculation
                    )
                    await self._force_constraints(connection)
        except IntegrityError as error:
            if not _is_unique_violation(error):
                raise
            try:
                existing = await self.get_calculation(
                    scope.run_id, calculation.calculation_id
                )
            except EvidenceLedgerNotFound:
                raise error from None
            if _model_bytes(existing) == _model_bytes(calculation):
                return
            raise EvidenceLedgerConflict(
                "CalculationRecord", f"{scope.run_id}/{calculation.calculation_id}"
            ) from error

    async def append_claim(
        self,
        scope: RequestScope,
        claim: AtomicClaim,
        *,
        supports: tuple[ClaimSupport, ...],
    ) -> None:
        if not supports:
            raise ValueError("Claim requires at least one initial support")
        if any(support.claim_id != claim.claim_id for support in supports):
            raise ValueError("initial support claim_id must match AtomicClaim")

        payload = claim.model_dump(mode="json")
        subject_kind = _CLAIM_SUBJECT_KIND[claim.claim_type]
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await self._require_scope(connection, scope)
                    await connection.execute(
                        sa.insert(atomic_claim).values(
                            run_id=scope.run_id,
                            dataset_version=scope.dataset_version,
                            claim_id=payload["claim_id"],
                            claim_type=payload["claim_type"],
                            subtask_id=payload["subtask_id"],
                            subject_id=payload["subject_id"],
                            subject_kind=subject_kind,
                            subject_entity_id=(
                                claim.subject_id if subject_kind == "entity" else None
                            ),
                            request_subject_id=(
                                claim.subject_id if subject_kind == "request" else None
                            ),
                            predicate_id=payload["predicate_id"],
                            object_id=payload["object_id"],
                            value=(
                                _dump_tagged_value(claim.value)
                                if claim.value is not None
                                else None
                            ),
                            unit=payload["unit"],
                            currency=payload["currency"],
                            display_policy_id=payload["display_policy_id"],
                            claim_hash=payload["claim_hash"],
                            created_at=datetime.now(UTC),
                        )
                    )
                    for ordinal, qualifier in enumerate(claim.qualifiers):
                        await connection.execute(
                            sa.insert(claim_qualifier).values(
                                run_id=scope.run_id,
                                dataset_version=scope.dataset_version,
                                claim_id=claim.claim_id,
                                ordinal=ordinal,
                                qualifier_id=qualifier.qualifier_id,
                                value=_dump_tagged_value(qualifier.value),
                            )
                        )
                    for support in supports:
                        await self._insert_support(connection, scope, support)
                    await self._force_constraints(connection)
        except IntegrityError as error:
            if not _is_unique_violation(error):
                raise
            try:
                existing = await self.get_claim(scope.run_id, claim.claim_id)
            except EvidenceLedgerNotFound:
                raise error from None
            if _model_bytes(existing) != _model_bytes(claim):
                raise EvidenceLedgerConflict(
                    "AtomicClaim", f"{scope.run_id}/{claim.claim_id}"
                ) from error
            existing_supports = await self._get_supports(
                scope.run_id, claim.claim_id
            )
            if _models_bytes(existing_supports) != _models_bytes(supports):
                raise EvidenceLedgerConflict(
                    "ClaimSupport", f"{scope.run_id}/{claim.claim_id}"
                ) from error

    async def append_support(
        self, scope: RequestScope, support: ClaimSupport
    ) -> None:
        try:
            async with self._engine.connect() as connection:
                async with connection.begin():
                    await self._require_scope(connection, scope)
                    await self._insert_support(connection, scope, support)
                    await self._force_constraints(connection)
        except IntegrityError as error:
            if not _is_unique_violation(error):
                raise
            try:
                existing = await self._get_support(
                    scope.run_id, support.claim_id, support.ordinal
                )
            except EvidenceLedgerNotFound:
                raise error from None
            if _model_bytes(existing) == _model_bytes(support):
                return
            raise EvidenceLedgerConflict(
                "ClaimSupport",
                f"{scope.run_id}/{support.claim_id}/{support.ordinal}",
            ) from error

    async def get_evidence(
        self, dataset_version: str, evidence_id: str
    ) -> EvidenceRecord:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.select(evidence_record).where(
                        evidence_record.c.dataset_version == dataset_version,
                        evidence_record.c.evidence_id == evidence_id,
                    )
                )
            ).mappings().one_or_none()
        if row is None:
            raise EvidenceLedgerNotFound(
                "EvidenceRecord", f"{dataset_version}/{evidence_id}"
            )
        payload: dict[str, object] = {
            "evidence_id": row["evidence_id"],
            "evidence_kind": row["evidence_kind"],
            "source_id": row["source_id"],
            "dataset_version": row["dataset_version"],
            "subject_id": row["subject_id"],
            "predicate_id": row["predicate_id"],
            "value_or_object_id": row["value_or_object_id"],
            "normalized_value": row["normalized_value"],
            "unit": row["unit"],
            "currency": row["currency"],
            "applicable_date": row["applicable_date"],
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "published_at": row["published_at"],
            "available_at": row["available_at"],
            "vintage_date": row["vintage_date"],
            "source_locator": {
                "locator_type": row["locator_type"],
                "uri_or_object_key": row["locator_uri_or_object_key"],
                "record_key": row["locator_record_key"],
                "sheet": row["locator_sheet"],
                "row": row["locator_row"],
                "column": row["locator_column"],
                "page": row["locator_page"],
                "section": row["locator_section"],
                "sentence_start": row["locator_sentence_start"],
                "sentence_end": row["locator_sentence_end"],
            },
            "raw_value_repr": row["raw_value_repr"],
            "parser_version": row["parser_version"],
            "mapping_version": row["mapping_version"],
            "cutoff_status": row["cutoff_status"],
            "record_hash": row["record_hash"],
            "scope_completeness": row["scope_completeness"],
        }
        return _validate_contract_json(EvidenceRecord, payload)

    async def get_calculation(
        self, run_id: str, calculation_id: str
    ) -> CalculationRecord:
        async with self._engine.connect() as connection:
            parent = (
                await connection.execute(
                    sa.select(calculation_record).where(
                        calculation_record.c.run_id == run_id,
                        calculation_record.c.calculation_id == calculation_id,
                    )
                )
            ).mappings().one_or_none()
            if parent is None:
                raise EvidenceLedgerNotFound(
                    "CalculationRecord", f"{run_id}/{calculation_id}"
                )
            parameters = (
                await connection.execute(
                    sa.select(
                        calculation_parameter.c.parameter_id,
                        calculation_parameter.c.value,
                    )
                    .where(
                        calculation_parameter.c.run_id == run_id,
                        calculation_parameter.c.calculation_id == calculation_id,
                    )
                    .order_by(calculation_parameter.c.ordinal)
                )
            ).mappings().all()
            evidence_inputs = (
                await connection.execute(
                    sa.select(calculation_evidence_input.c.evidence_id)
                    .where(
                        calculation_evidence_input.c.run_id == run_id,
                        calculation_evidence_input.c.calculation_id
                        == calculation_id,
                    )
                    .order_by(calculation_evidence_input.c.ordinal)
                )
            ).scalars().all()
            dependencies = (
                await connection.execute(
                    sa.select(calculation_dependency.c.input_calculation_id)
                    .where(
                        calculation_dependency.c.run_id == run_id,
                        calculation_dependency.c.calculation_id == calculation_id,
                    )
                    .order_by(calculation_dependency.c.ordinal)
                )
            ).scalars().all()
            exclusions = (
                await connection.execute(
                    sa.select(calculation_exclusion.c.evidence_id)
                    .where(
                        calculation_exclusion.c.run_id == run_id,
                        calculation_exclusion.c.calculation_id == calculation_id,
                    )
                    .order_by(calculation_exclusion.c.ordinal)
                )
            ).scalars().all()
            population = (
                await connection.execute(
                    sa.select(calculation_population).where(
                        calculation_population.c.run_id == run_id,
                        calculation_population.c.calculation_id == calculation_id,
                    )
                )
            ).mappings().one_or_none()
            filters: list[str] = []
            if population is not None:
                filters = list(
                    (
                        await connection.execute(
                            sa.select(calculation_population_filter.c.filter_id)
                            .where(
                                calculation_population_filter.c.run_id == run_id,
                                calculation_population_filter.c.calculation_id
                                == calculation_id,
                            )
                            .order_by(calculation_population_filter.c.ordinal)
                        )
                    ).scalars()
                )

        population_payload: dict[str, object] | None = None
        if population is not None:
            population_payload = {
                "population_id": population["population_id"],
                "scope_evidence_id": population["scope_evidence_id"],
                "filter_ids": filters,
                "member_count": population["member_count"],
                "population_hash": population["population_hash"],
            }
        payload = {
            "calculation_id": parent["calculation_id"],
            "calculation_type": parent["calculation_type"],
            "formula_id": parent["formula_id"],
            "formula_version": parent["formula_version"],
            "input_evidence_ids": list(evidence_inputs),
            "input_calculation_ids": list(dependencies),
            "parameters": [dict(row) for row in parameters],
            "population_definition": population_payload,
            "exclusion_evidence_ids": list(exclusions),
            "tie_break_rule": parent["tie_break_rule"],
            "result_value": parent["result_value"],
            "unit": parent["unit"],
            "currency": parent["currency"],
            "rounding_rule": parent["rounding_rule"],
            "calculation_hash": parent["calculation_hash"],
        }
        return _validate_contract_json(CalculationRecord, payload)

    async def get_claim(self, run_id: str, claim_id: str) -> AtomicClaim:
        async with self._engine.connect() as connection:
            parent = (
                await connection.execute(
                    sa.select(atomic_claim).where(
                        atomic_claim.c.run_id == run_id,
                        atomic_claim.c.claim_id == claim_id,
                    )
                )
            ).mappings().one_or_none()
            if parent is None:
                raise EvidenceLedgerNotFound(
                    "AtomicClaim", f"{run_id}/{claim_id}"
                )
            qualifiers = (
                await connection.execute(
                    sa.select(
                        claim_qualifier.c.qualifier_id,
                        claim_qualifier.c.value,
                    )
                    .where(
                        claim_qualifier.c.run_id == run_id,
                        claim_qualifier.c.claim_id == claim_id,
                    )
                    .order_by(claim_qualifier.c.ordinal)
                )
            ).mappings().all()
        payload = {
            "claim_id": parent["claim_id"],
            "claim_type": parent["claim_type"],
            "subtask_id": parent["subtask_id"],
            "subject_id": parent["subject_id"],
            "predicate_id": parent["predicate_id"],
            "object_id": parent["object_id"],
            "value": parent["value"],
            "unit": parent["unit"],
            "currency": parent["currency"],
            "qualifiers": [dict(row) for row in qualifiers],
            "display_policy_id": parent["display_policy_id"],
            "claim_hash": parent["claim_hash"],
        }
        return _validate_contract_json(AtomicClaim, payload)

    async def get_source(
        self, dataset_version: str, source_id: str
    ) -> SourceRecord:
        """Return the immutable source needed by verifier and renderer."""

        return await self._get_source(dataset_version, source_id)

    async def get_claim_supports(
        self, run_id: str, claim_id: str
    ) -> tuple[ClaimSupport, ...]:
        """Return ordered support links for one candidate claim."""

        return await self._get_supports(run_id, claim_id)

    async def _get_source(
        self, dataset_version: str, source_id: str
    ) -> SourceRecord:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.select(source_record).where(
                        source_record.c.dataset_version == dataset_version,
                        source_record.c.source_id == source_id,
                    )
                )
            ).mappings().one_or_none()
        if row is None:
            raise EvidenceLedgerNotFound(
                "SourceRecord", f"{dataset_version}/{source_id}"
            )
        payload = {
            "source_id": row["source_id"],
            "publisher": row["publisher"],
            "publisher_type": row["publisher_type"],
            "source_title": row["source_title"],
            "source_type": row["source_type"],
            "authority_tier": row["authority_tier"],
            "source_locator_root": row["source_locator_root"],
            "content_checksum": row["content_checksum"],
            "license_or_usage_note": row["license_or_usage_note"],
            "eligible_for_claim": row["eligible_for_claim"],
        }
        return _validate_contract_json(SourceRecord, payload)

    async def _get_origin(
        self, dataset_version: str, evidence_id: str
    ) -> OriginReference | None:
        async with self._engine.connect() as connection:
            for origin_kind, (origin_table, record_column) in _ORIGIN_TABLES.items():
                record_id = (
                    await connection.execute(
                        sa.select(origin_table.c[record_column]).where(
                            origin_table.c.dataset_version == dataset_version,
                            origin_table.c.evidence_id == evidence_id,
                        )
                    )
                ).scalar_one_or_none()
                if record_id is not None:
                    return OriginReference(
                        origin_kind=origin_kind,  # type: ignore[arg-type]
                        dataset_version=dataset_version,
                        record_id=record_id,
                    )
        return None

    async def _get_support(
        self, run_id: str, claim_id: str, ordinal: int
    ) -> ClaimSupport:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.select(claim_support).where(
                        claim_support.c.run_id == run_id,
                        claim_support.c.claim_id == claim_id,
                        claim_support.c.ordinal == ordinal,
                    )
                )
            ).mappings().one_or_none()
        if row is None:
            raise EvidenceLedgerNotFound(
                "ClaimSupport", f"{run_id}/{claim_id}/{ordinal}"
            )
        payload = {
            "claim_id": row["claim_id"],
            "support_kind": row["support_kind"],
            "evidence_id": row["evidence_id"],
            "calculation_id": row["calculation_id"],
            "support_role": row["support_role"],
            "ordinal": row["ordinal"],
        }
        return _validate_contract_json(ClaimSupport, payload)

    async def _get_supports(
        self, run_id: str, claim_id: str
    ) -> tuple[ClaimSupport, ...]:
        async with self._engine.connect() as connection:
            rows = (
                await connection.execute(
                    sa.select(claim_support)
                    .where(
                        claim_support.c.run_id == run_id,
                        claim_support.c.claim_id == claim_id,
                    )
                    .order_by(claim_support.c.ordinal)
                )
            ).mappings().all()
        return tuple(
            _validate_contract_json(
                ClaimSupport,
                {
                    "claim_id": row["claim_id"],
                    "support_kind": row["support_kind"],
                    "evidence_id": row["evidence_id"],
                    "calculation_id": row["calculation_id"],
                    "support_role": row["support_role"],
                    "ordinal": row["ordinal"],
                },
            )
            for row in rows
        )

    async def _insert_calculation_associations(
        self,
        connection: AsyncConnection,
        scope: RequestScope,
        calculation: CalculationRecord,
    ) -> None:
        for ordinal, parameter in enumerate(calculation.parameters):
            await connection.execute(
                sa.insert(calculation_parameter).values(
                    run_id=scope.run_id,
                    dataset_version=scope.dataset_version,
                    calculation_id=calculation.calculation_id,
                    ordinal=ordinal,
                    parameter_id=parameter.parameter_id,
                    value=_dump_tagged_value(parameter.value),
                )
            )
        for ordinal, evidence_id in enumerate(calculation.input_evidence_ids):
            await connection.execute(
                sa.insert(calculation_evidence_input).values(
                    run_id=scope.run_id,
                    dataset_version=scope.dataset_version,
                    calculation_id=calculation.calculation_id,
                    evidence_id=evidence_id,
                    ordinal=ordinal,
                )
            )
        for ordinal, input_calculation_id in enumerate(
            calculation.input_calculation_ids
        ):
            await connection.execute(
                sa.insert(calculation_dependency).values(
                    run_id=scope.run_id,
                    dataset_version=scope.dataset_version,
                    calculation_id=calculation.calculation_id,
                    input_calculation_id=input_calculation_id,
                    ordinal=ordinal,
                )
            )
        for ordinal, evidence_id in enumerate(calculation.exclusion_evidence_ids):
            await connection.execute(
                sa.insert(calculation_exclusion).values(
                    run_id=scope.run_id,
                    dataset_version=scope.dataset_version,
                    calculation_id=calculation.calculation_id,
                    evidence_id=evidence_id,
                    ordinal=ordinal,
                )
            )
        population = calculation.population_definition
        if population is None:
            return
        await connection.execute(
            sa.insert(calculation_population).values(
                run_id=scope.run_id,
                dataset_version=scope.dataset_version,
                calculation_id=calculation.calculation_id,
                population_id=population.population_id,
                scope_evidence_id=population.scope_evidence_id,
                member_count=population.member_count,
                population_hash=population.population_hash,
            )
        )
        for ordinal, filter_id in enumerate(population.filter_ids):
            await connection.execute(
                sa.insert(calculation_population_filter).values(
                    run_id=scope.run_id,
                    dataset_version=scope.dataset_version,
                    calculation_id=calculation.calculation_id,
                    ordinal=ordinal,
                    filter_id=filter_id,
                )
            )

    async def _insert_support(
        self,
        connection: AsyncConnection,
        scope: RequestScope,
        support: ClaimSupport,
    ) -> None:
        payload = support.model_dump(mode="json")
        await connection.execute(
            sa.insert(claim_support).values(
                run_id=scope.run_id,
                dataset_version=scope.dataset_version,
                claim_id=payload["claim_id"],
                support_kind=payload["support_kind"],
                evidence_id=payload["evidence_id"],
                calculation_id=payload["calculation_id"],
                support_role=payload["support_role"],
                ordinal=payload["ordinal"],
            )
        )

    @staticmethod
    async def _require_scope(
        connection: AsyncConnection, scope: RequestScope
    ) -> None:
        exists = (
            await connection.execute(
                sa.select(request_run.c.run_id).where(
                    request_run.c.request_key == scope.request_key,
                    request_run.c.run_id == scope.run_id,
                    request_run.c.dataset_version == scope.dataset_version,
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise RequestScopeMismatch()

    @staticmethod
    async def _force_constraints(connection: AsyncConnection) -> None:
        await connection.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))
