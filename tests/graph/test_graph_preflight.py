from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from financial_agent.graph.preflight import validate_projection_batch
from tests.graph.test_graph_exporter import valid_batch


def test_valid_projection_has_canonical_counted_preflight_report() -> None:
    """Catches omitted aggregate coverage or non-canonical report serialization."""
    batch = valid_batch()

    first = validate_projection_batch(batch)
    second = validate_projection_batch(
        replace(
            batch,
            entities=tuple(reversed(batch.entities)),
            sources=tuple(reversed(batch.sources)),
            evidences=tuple(reversed(batch.evidences)),
        )
    )

    assert first.conforms is True
    assert first.violation_codes == ()
    assert first.counts == {
        "entities": 4,
        "evidences": 2,
        "holding_observations": 1,
        "relations": 1,
        "sources": 2,
    }
    assert first.report_bytes == second.report_bytes
    assert json.loads(first.report_bytes) == {
        "conforms": True,
        "counts": dict(first.counts),
        "dataset_version": batch.dataset_version,
        "schema_version": "1",
        "violation_codes": [],
    }


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        (
            lambda batch: replace(
                batch, entities=(*batch.entities, batch.entities[0])
            ),
            "DUPLICATE_ENTITY_ID",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(batch.relations[0], dataset_version="foreign"),
                ),
            ),
            "DATASET_VERSION_MISMATCH",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(batch.relations[0], predicate_id="unknown"),
                ),
            ),
            "UNKNOWN_PREDICATE",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(batch.relations[0], subject_id="missing"),
                ),
            ),
            "MISSING_SUBJECT",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(batch.relations[0], object_id="product/상품"),
                ),
            ),
            "INVALID_RELATION_RANGE",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(batch.relations[0], evidence_ids=("missing",)),
                ),
            ),
            "MISSING_EVIDENCE",
        ),
        (
            lambda batch: replace(
                batch,
                evidences=(
                    replace(batch.evidences[0], source_id="missing"),
                    batch.evidences[1],
                ),
            ),
            "MISSING_SOURCE",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(
                        batch.relations[0],
                        valid_from=batch.cutoff_date,
                        valid_to=batch.cutoff_date - timedelta(days=1),
                    ),
                ),
            ),
            "INVALID_DATE_ORDER",
        ),
        (
            lambda batch: replace(
                batch,
                evidences=(
                    replace(
                        batch.evidences[0],
                        applicable_date=batch.cutoff_date + timedelta(days=1),
                    ),
                    batch.evidences[1],
                ),
            ),
            "AFTER_CUTOFF",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(replace(batch.relations[0], metrics=()),),
            ),
            "MISSING_HOLDING_WEIGHT",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(
                        batch.relations[0],
                        metrics=(
                            replace(
                                batch.relations[0].metrics[0],
                                numeric_value=Decimal("100.01"),
                            ),
                        ),
                    ),
                ),
            ),
            "INVALID_HOLDING_WEIGHT",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(
                        batch.relations[0],
                        metrics=(
                            batch.relations[0].metrics[0],
                            batch.relations[0].metrics[0],
                        ),
                    ),
                ),
            ),
            "DUPLICATE_OBSERVATION_ID",
        ),
        (
            lambda batch: replace(
                batch,
                relations=(
                    replace(
                        batch.relations[0],
                        metrics=(
                            replace(
                                batch.relations[0].metrics[0],
                                relation_id="another-relation",
                            ),
                        ),
                    ),
                ),
            ),
            "RELATION_METRIC_MISMATCH",
        ),
    ),
)
def test_preflight_reports_release_critical_projection_violations(
    mutation,
    expected_code: str,
) -> None:
    """Catches a malformed projection reaching RDF serialization or SHACL."""
    result = validate_projection_batch(mutation(valid_batch()))

    assert result.conforms is False
    assert expected_code in result.violation_codes
    assert result.violation_codes == tuple(sorted(set(result.violation_codes)))
