from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
from warnings import catch_warnings, simplefilter

import pytest
from rdflib import Dataset

from financial_agent.graph.contract import APPROVED_PREDICATES, FP
from financial_agent.graph.validator import validate_graph


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "graph"
SHAPE_PATHS = (
    PROJECT_ROOT / "ontology" / "shapes" / "common.shacl.ttl",
    PROJECT_ROOT / "ontology" / "shapes" / "domain.shacl.ttl",
)
CUTOFF_DATE = date(2026, 8, 24)


def validate_fixture(name: str):
    return validate_graph(
        data_paths=(FIXTURE_DIR / name,),
        shape_paths=SHAPE_PATHS,
        cutoff_date=CUTOFF_DATE,
    )


def test_valid_fixture_exercises_each_approved_predicate() -> None:
    """Catches a validator that accepts a fixture missing an approved relation path."""
    fixture = FIXTURE_DIR / "valid_all_predicates.trig"
    graph = Dataset()
    with catch_warnings():
        simplefilter("ignore", DeprecationWarning)
        graph.parse(fixture, format="trig")
    asserted_predicates = {
        str(predicate).removeprefix(str(FP))
        for _, _, predicate, _ in graph.quads((None, FP.predicate, None, None))
    }

    result = validate_fixture(fixture.name)

    assert asserted_predicates == APPROVED_PREDICATES
    assert result.conforms is True


def test_multi_role_product_keeps_one_canonical_identity_conformant() -> None:
    """Catches an erroneous rule that treats ETF/share-class multi-typing as disjoint."""
    result = validate_fixture("valid_multi_role_product.trig")

    assert result.conforms is True


@pytest.mark.parametrize(
    ("fixture", "expected_component"),
    [
        ("invalid_unknown_predicate.trig", "InConstraintComponent"),
        ("invalid_missing_evidence.trig", "MinCountConstraintComponent"),
        ("invalid_date_order.trig", "SPARQLConstraintComponent"),
        ("invalid_after_cutoff.trig", "SPARQLConstraintComponent"),
        ("invalid_etf_etn.trig", "NotConstraintComponent"),
        ("invalid_grade_scheme.trig", "InConstraintComponent"),
        ("invalid_holding_weight.trig", "MinCountConstraintComponent"),
    ],
)
def test_invalid_fixture_is_rejected_by_its_stable_constraint_component(
    fixture: str,
    expected_component: str,
) -> None:
    """Catches removal or weakening of each named semantic SHACL constraint."""
    result = validate_fixture(fixture)

    assert result.conforms is False
    assert expected_component in result.report_text


def test_report_hash_uses_stable_canonical_ntriples() -> None:
    """Catches hashing human report text or non-canonical blank-node labels."""
    first = validate_fixture("invalid_missing_evidence.trig")
    second = validate_fixture("invalid_missing_evidence.trig")

    assert first.report_hash == sha256(first.report_ntriples).hexdigest()
    assert first.report_ntriples == second.report_ntriples
    assert first.report_hash == second.report_hash


def test_validation_does_not_modify_the_named_graph_source() -> None:
    """Catches a validator that repairs or mutates the source while building its union graph."""
    fixture = FIXTURE_DIR / "valid_all_predicates.trig"
    before = fixture.read_bytes()

    validate_fixture(fixture.name)

    assert fixture.read_bytes() == before
