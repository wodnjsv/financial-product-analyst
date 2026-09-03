from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
from warnings import catch_warnings, filterwarnings

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
        filterwarnings(
            "ignore",
            message=(
                r"Dataset\.default_context is deprecated, use "
                r"Dataset\.default_graph instead\."
            ),
            category=DeprecationWarning,
            module=r"rdflib\.graph",
        )
        filterwarnings(
            "ignore",
            message=r"ConjunctiveGraph is deprecated, use Dataset instead\.",
            category=DeprecationWarning,
            module=r"rdflib\.plugins\.parsers\.trig",
        )
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


def test_explicit_snapshot_preserves_domestic_etf_subclass_closure() -> None:
    """Catches removal of RDFS subclass closure from the explicit domain-type pass."""
    result = validate_fixture("valid_domestic_etf_subclass.trig")

    assert result.conforms is True


def test_etn_may_explicitly_track_an_index() -> None:
    result = validate_fixture("valid_etn_tracks_index.trig")

    assert result.conforms is True, result.report_text


def test_cutoff_day_datetimes_accept_seoul_and_equivalent_utc_instants() -> None:
    """Catches lexical cutoff comparison that rejects valid cutoff-day dateTimes."""
    result = validate_fixture("valid_cutoff_day_datetime.trig")

    assert result.conforms is True


def test_cutoff_datetime_rejects_the_exclusive_seoul_next_day_boundary() -> None:
    """Catches a cutoff check that accepts the first instant after the Seoul cutoff day."""
    result = validate_fixture("invalid_after_cutoff_datetime.trig")

    assert result.conforms is False
    assert "SPARQLConstraintComponent" in result.report_text


def test_document_and_risk_provenance_fixture_conforms() -> None:
    """Catches provenance constraints that cannot accept a fully supported document span."""
    result = validate_fixture("valid_document_risk_provenance.trig")

    assert result.conforms is True, result.report_text


def test_document_and_risk_provenance_requires_explicit_trusted_types() -> None:
    """Catches property-range inference substituting for explicit provenance typing."""
    result = validate_fixture("invalid_provenance_inferred_types.trig")

    assert result.conforms is False
    assert "ClassConstraintComponent" in result.report_text


def test_document_provenance_requires_explicit_evidence_and_source_types() -> None:
    """Catches Evidence/source ranges substituting for explicit provenance types."""
    result = validate_fixture("invalid_document_inferred_evidence_types.trig")

    assert result.conforms is False
    assert "ClassConstraintComponent" in result.report_text


@pytest.mark.parametrize(
    "fixture",
    (
        "invalid_assertion_inferred_evidence_types.trig",
        "invalid_inferred_relation_assertion_type.trig",
    ),
)
def test_relation_assertion_provenance_requires_explicit_trusted_types(
    fixture: str,
) -> None:
    """Catches assertion or Evidence/source types supplied only by TBox inference."""
    result = validate_fixture(fixture)

    assert result.conforms is False
    assert "ClassConstraintComponent" in result.report_text


@pytest.mark.parametrize(
    ("fixture", "expected_path"),
    [
        ("invalid_risk_missing_chunk.trig", "documentChunk"),
        ("invalid_risk_missing_page.trig", "page"),
        ("invalid_risk_missing_section.trig", "section"),
        ("invalid_risk_missing_span.trig", "sourceSpan"),
        ("invalid_risk_missing_evidence.trig", "evidenceRecord"),
        ("invalid_document_missing_publisher.trig", "publisherOrganization"),
        ("invalid_document_missing_version.trig", "documentVersion"),
        ("invalid_document_missing_source_object.trig", "sourceObjectId"),
    ],
)
def test_document_and_risk_provenance_missingness_is_rejected(
    fixture: str,
    expected_path: str,
) -> None:
    """Catches document or span facts becoming claim-eligible without required provenance."""
    result = validate_fixture(fixture)

    assert result.conforms is False
    assert "MinCountConstraintComponent" in result.report_text
    assert expected_path in result.report_text


def test_multiple_holding_weight_observations_conform() -> None:
    """Catches a shape that flattens or rejects independently dated holding observations."""
    result = validate_fixture("valid_multiple_holding_weights.trig")

    assert result.conforms is True, result.report_text


@pytest.mark.parametrize("predicate", sorted(APPROVED_PREDICATES))
def test_domain_range_requires_explicit_types_before_relation_entailment(
    predicate: str,
) -> None:
    """Catches a relation that infers its own required type through RDFS domain/range."""
    result = validate_fixture("invalid_domain_range.trig")

    assert result.conforms is False
    assert "ClassConstraintComponent" in result.report_text
    assert f"invalid-{predicate}" in result.report_text


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
        ("invalid_holding_weight_date.trig", "MinCountConstraintComponent"),
        ("invalid_holding_weight_wrong_relation.trig", "SPARQLConstraintComponent"),
        ("invalid_ambiguous_holding_observation.trig", "MaxCountConstraintComponent"),
        ("invalid_holding_weight_same_date.trig", "SPARQLConstraintComponent"),
        ("invalid_assertion_missing_direct_edge.trig", "SPARQLConstraintComponent"),
        ("invalid_orphan_direct_edge.trig", "SPARQLConstraintComponent"),
        ("invalid_blank_document_provenance.trig", "PatternConstraintComponent"),
        ("invalid_blank_risk_span.trig", "PatternConstraintComponent"),
        ("invalid_blank_holding_observation_id.trig", "PatternConstraintComponent"),
        ("invalid_duplicate_holding_observation_id.trig", "SPARQLConstraintComponent"),
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
