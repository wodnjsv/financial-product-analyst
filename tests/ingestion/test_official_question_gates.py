from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.official import (
    NportProductBinding,
    build_sec_series_class_index,
    iter_eligible_nport_funds,
    map_ecos_fx,
    map_krx_etf_daily,
    map_krx_holding_snapshot,
    parse_ecos_731y001,
    parse_krx_etf_daily,
    parse_krx_etf_pdf_csv,
    parse_sec_series_class,
)
from financial_agent.ingestion.official.identity import (
    IdentityCandidate,
    OfficialIdentityIndex,
)
from financial_agent.ingestion.official.krx_holdings import (
    KrxEtfProductBinding,
)
from tests.fixtures.official_ingestion import (
    ecos_731y001_payload,
    krx_etf_daily_payload,
    krx_etf_pdf_payload,
    official_manifest,
    sec_nport_tsv_files,
    sec_series_class_payload,
)


APPROVED_GRAPH_PREDICATES = {
    "managedBy",
    "issuedBy",
    "tracksIndex",
    "holdsSecurity",
    "containsSecurity",
    "securityOfCompany",
    "controlsCompany",
    "listedOn",
    "classifiedAsIndustry",
    "associatedWithTheme",
    "hasShareClass",
    "documentedBy",
    "hasRiskFactor",
}

REQUIREMENT_GROUPS = {
    "entities",
    "attributes",
    "metrics",
    "relations",
    "document_claims",
    "control_checks",
}

APPROVED_CAPABILITIES = {
    "resolve_entity",
    "lookup_facts",
    "filter_products",
    "rank_metric",
    "calculate_metric",
    "validate_metric_compatibility",
    "normalize_currency",
    "traverse_relation",
    "calculate_similarity",
    "resolve_reference",
    "search_documents",
    "validate_source_spans",
    "validate_missingness",
    "validate_availability",
    "validate_closed_world_coverage",
    "deduplicate_share_classes",
    "build_evidence_bundle",
    "generate_atomic_claims",
    "verify_claim_support",
    "determine_disposition",
    "apply_claim_gate",
    "render_verified_answer",
}

FROZEN_CASE_FINGERPRINT = (
    "730ff0efdbe38a8899e52c7b5bbea6993cdfdeb704e3a1e86b1325169a52e761"
)


def _question_catalog() -> dict[str, object]:
    return json.loads(
        (
            Path(__file__).parents[1]
            / "gold"
            / "core_questions.json"
        ).read_text("utf-8")
    )


def _records(rows: object, table: str) -> tuple[dict[str, object], ...]:
    values = rows if isinstance(rows, tuple) else (rows,)
    return tuple(
        dict(record)
        for row in values
        for record in row.records_by_table[table]
    )


def _domestic_binding() -> KrxEtfProductBinding:
    return KrxEtfProductBinding(
        product_entity_id=stable_id(
            "product", "PREF01N001", "KR7305080004"
        ),
        organizer_isin="KR7305080004",
        krx_short_code="305080",
        organizer_name="TIGER 미국채10년선물",
        krx_name="TIGER 미국채10년선물",
        name_matches=True,
    )


def test_question_contract_preserves_frozen_case_identity_and_disposition() -> None:
    catalog = _question_catalog()
    frozen = [
        {
            key: case[key]
            for key in (
                "id",
                "question",
                "category",
                "support_level",
                "target_support_level",
                "expected_disposition",
            )
        }
        for case in catalog["cases"]
    ]
    payload = json.dumps(
        frozen,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    assert hashlib.sha256(payload).hexdigest() == FROZEN_CASE_FINGERPRINT


def test_question_contract_v13_has_explicit_requirements_and_routes() -> None:
    catalog = _question_catalog()

    assert catalog["schema_version"] == "1.3"
    assert len(catalog["cases"]) == 52
    assert {
        state: sum(case["support_level"] == state for case in catalog["cases"])
        for state in (
            "supported",
            "limited",
            "requires_additional_data",
            "unsupported",
        )
    } == {
        "supported": 16,
        "limited": 18,
        "requires_additional_data": 11,
        "unsupported": 7,
    }

    for case in catalog["cases"]:
        assert "required_relations" not in case, case["id"]
        assert set(case["requirements"]) == REQUIREMENT_GROUPS, case["id"]
        assert case["requires_data"] is (
            case["support_level"] == "requires_additional_data"
        ), case["id"]
        assert case["verification"] == {
            "coverage_assessment": "frozen_design_2026-08-27",
            "current_db_execution": "not_run",
            "verified_dataset_version": None,
            "verified_at": None,
            "result_artifact": None,
        }, case["id"]

        predicates = {
            relation["predicate"]
            for relation in case["requirements"]["relations"]
        }
        assert predicates <= APPROVED_GRAPH_PREDICATES, case["id"]
        assert all(
            set(relation) == {
                "predicate",
                "direction",
                "required_assertion_fields",
            }
            and {
                "relation_assertion_id",
                "evidence_id",
                "dataset_version",
            } <= set(relation["required_assertion_fields"])
            for relation in case["requirements"]["relations"]
        ), case["id"]
        routes = case["retrieval"]["subtask_routes"]
        profile = case["retrieval"]["profile"]
        assert case["retrieval"]["roles"] == catalog["retrieval_profiles"][
            profile
        ]["roles"], case["id"]
        assert len(routes) == len(case["subtasks"]), case["id"]
        assert {route["subtask"] for route in routes} == set(
            case["subtasks"]
        ), case["id"]
        assert all(
            set(route) == {"subtask", "capability", "role", "required"}
            and route["capability"] in APPROVED_CAPABILITIES
            and route["required"] is True
            for route in routes
        ), case["id"]
        allowed_route_roles = set(case["retrieval"]["roles"]) | {
            "application",
            "ontology",
            "policy",
        }
        assert all(
            set(
                route["role"]
                if isinstance(route["role"], list)
                else [route["role"]]
            )
            <= allowed_route_roles
            for route in routes
        ), case["id"]
        assert {
            item["id"] for item in case["requirements"]["attributes"]
        }.isdisjoint(APPROVED_GRAPH_PREDICATES), case["id"]
        assert {
            item["id"] for item in case["requirements"]["metrics"]
        }.isdisjoint(APPROVED_GRAPH_PREDICATES), case["id"]
        if "vector" in case["retrieval"]["roles"]:
            assert profile in {"document_grounded", "federated"}, case["id"]


def test_question_contract_separates_grades_and_document_provenance() -> None:
    cases = {case["id"]: case for case in _question_catalog()["cases"]}

    bond_filter = cases["FLT-BOND-001"]["requirements"]
    assert {item["id"] for item in bond_filter["attributes"]} >= {
        "credit_grade",
        "currency",
        "availability_status",
    }
    assert not bond_filter["relations"]

    cross_risk = cases["CMP-RISK-001"]["requirements"]
    assert {item["id"] for item in cross_risk["attributes"]} == {
        "product_risk_grade",
        "credit_grade",
    }

    document = cases["DOC-FUND-001"]["requirements"]
    assert "PolicyProgram" in {item["type"] for item in document["entities"]}
    assert {item["predicate"] for item in document["relations"]} == {
        "documentedBy"
    }
    assert document["document_claims"][0]["required_provenance"] == [
        "publisher_organization_id",
        "published_at",
        "effective_from",
        "effective_to",
        "available_at",
        "document_version",
        "source_object_id",
        "document_chunk_id",
        "source_span",
    ]
    assert all(
        set(claim) == {"claim_type", "required_provenance"}
        for claim in document["document_claims"]
    )

    fund_similarity = cases["REL-SIM-FUND-001"]["requirements"]
    assert "tracksIndex" in {
        item["predicate"] for item in fund_similarity["relations"]
    }


def test_stage03_question_coverage_contract_is_complete() -> None:
    catalog = json.loads(
        (
            Path(__file__).parents[1]
            / "gold"
            / "core_questions.json"
        ).read_text("utf-8")
    )

    assert "required_source_registry" in catalog
    assert "adversarial_missingness_cases" in catalog
    registered_sources = set(catalog["required_source_registry"])
    allowed_support = {
        "supported",
        "limited",
        "requires_additional_data",
        "unsupported",
    }
    partial_coverage_sources = {
        "official_etf_holdings_snapshot",
        "official_overseas_etf_holdings_snapshot",
        "official_public_fund_holdings_snapshot",
    }

    assert len(catalog["cases"]) == 52
    for case in catalog["cases"]:
        assert case["support_level"] in allowed_support, case["id"]
        assert isinstance(case["required_sources"], list), case["id"]
        assert set(case["required_sources"]) <= registered_sources, case["id"]
        assert "closed_world_scope" in case, case["id"]
        assert case["missingness_policy"] == "organizer_authoritative", case["id"]
        if case["support_level"] == "limited":
            assert case["limitation_reason"], case["id"]
        if partial_coverage_sources & set(case["required_sources"]):
            assert case["closed_world_scope"] is None, case["id"]

    adversarial_cases = catalog["adversarial_missingness_cases"]
    assert {case["metric"] for case in adversarial_cases} == {
        "aum",
        "return",
        "price",
        "nav",
        "risk",
    }
    assert all(
        case["organizer_state"] in {"null", "blank"}
        and case["external_state"] == "present"
        and case["expected_result"] == "unavailable"
        and case["forbidden_action"] == "external_backfill"
        for case in adversarial_cases
    )


def test_theme_relation_window_uses_current_dataset_cutoff() -> None:
    catalog = json.loads(
        (Path(__file__).parents[1] / "gold" / "core_questions.json").read_text(
            "utf-8"
        )
    )
    case = next(item for item in catalog["cases"] if item["id"] == "REL-THEME-001")

    assert case["temporal_scope"] == {
        "window_start": "2026-02-24",
        "window_end": "2026-08-24",
        "boundary": "inclusive",
        "publication_cutoff": "2026-08-24",
    }
    assert "WINDOW_END_2026_08_24" in case["business_rules"]
    assert "WINDOW_END_2026_07_11" not in case["business_rules"]


def test_cross_family_samsung_question_keeps_public_fund_gap_visible() -> None:
    catalog = json.loads(
        (
            Path(__file__).parents[1]
            / "gold"
            / "core_questions.json"
        ).read_text("utf-8")
    )
    case = next(
        item for item in catalog["cases"] if item["id"] == "REL-HOLD-001"
    )
    requirements = {
        item["name"]: item for item in case["data_requirements"]
    }

    assert case["product_families"] == [
        "domestic_etf",
        "overseas_etf",
        "public_fund",
    ]
    assert requirements["official_public_fund_holdings_snapshot"]["status"] == (
        "requires_additional_data"
    )
    assert case["coverage_policy"]["public_fund"] == "requires_data"
    assert "NO_FALSE_EMPTY_FOR_UNCOVERED_FAMILY" in case["business_rules"]
    assert case["expected_disposition"] == "limitation"


def test_domestic_question_gate_joins_holding_price_nav_and_evidence() -> None:
    holding_payload = krx_etf_pdf_payload()
    holding_manifest = official_manifest(
        source_code="KRX_ETF_PDF",
        object_name="305080_20260710.csv",
        payload=holding_payload,
        applicable_date=date(2026, 7, 10),
        media_type="text/csv",
    )
    holding = map_krx_holding_snapshot(
        holding_manifest,
        parse_krx_etf_pdf_csv(holding_payload),
        binding=_domestic_binding(),
        security_index=OfficialIdentityIndex(
            exact_entries=(
                (
                    IdentityCandidate("KRX_SHORT_ISSUE_CODE", "005930"),
                    "security-samsung-electronics",
                ),
            )
        ),
    )
    market_payload = krx_etf_daily_payload()
    market = map_krx_etf_daily(
        official_manifest(
            source_code="KRX_ETF_DAILY",
            object_name="krx-etf-daily-20260710.json",
            payload=market_payload,
            applicable_date=date(2026, 7, 10),
        ),
        parse_krx_etf_daily(market_payload),
        bindings=(_domestic_binding(),),
    )

    holding_relation = next(
        record
        for record in _records(holding, "relation.relation_record")
        if record["object_id"] == "security-samsung-electronics"
    )
    market_observations = _records(
        market, "observation.observation_record"
    )

    assert holding_relation["predicate_id"] == "holdsSecurity"
    assert holding_relation["subject_id"] == _domestic_binding().product_entity_id
    assert {row["entity_id"] for row in market_observations} == {
        holding_relation["subject_id"]
    }
    assert {row["metric_id"] for row in market_observations} == {
        "krx_etf_market_close_krw",
        "krx_etf_nav_per_share_krw",
    }
    assert all(
        evidence["cutoff_status"] == "eligible"
        for evidence in (
            _records(holding, "evidence.evidence_record")
            + _records(market, "evidence.evidence_record")
        )
    )


def test_fx_question_gate_has_four_fixed_definitions_and_actual_date() -> None:
    payload = ecos_731y001_payload()
    mapped = map_ecos_fx(
        official_manifest(
            source_code="ECOS_731Y001",
            object_name="ecos-731y001-20260710.json",
            payload=payload,
            applicable_date=date(2026, 7, 10),
        ),
        parse_ecos_731y001(payload),
    )
    observations = _records(mapped, "observation.observation_record")

    assert len(observations) == 4
    assert {row["applicable_date"] for row in observations} == {
        date(2026, 7, 10)
    }
    assert {
        row["metric_id"] for row in observations
    } == {
        "ecos_731y001_krw_per_usd",
        "ecos_731y001_krw_per_100_jpy",
        "ecos_731y001_krw_per_eur",
        "ecos_731y001_krw_per_cny",
    }
    assert all(isinstance(row["numeric_value"], Decimal) for row in observations)


def test_overseas_question_gate_discloses_bounded_holdings_scope(
    tmp_path: Path,
) -> None:
    files = sec_nport_tsv_files()
    file_paths: dict[str, Path] = {}
    for name, payload in files.items():
        path = tmp_path / name
        path.write_bytes(payload)
        file_paths[name] = path
    series_payload = sec_series_class_payload()
    series_manifest = official_manifest(
        source_code="SEC_SERIES_CLASS_20260601",
        object_name="investment-company-series-class-2026.csv",
        payload=series_payload,
        applicable_date=date(2026, 6, 1),
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        available_at=datetime(2026, 6, 1, tzinfo=UTC),
        media_type="text/csv",
    )
    package = b"".join(files[name] for name in sorted(files))
    nport_manifest = official_manifest(
        source_code="SEC_NPORT_2026Q2",
        object_name="2026q2_nport.zip",
        payload=package,
        applicable_date=date(2026, 3, 31),
        published_at=datetime(2026, 6, 30, tzinfo=UTC),
        available_at=datetime(2026, 7, 9, tzinfo=UTC),
        media_type="application/zip",
    )
    mapped = tuple(
        iter_eligible_nport_funds(
            file_paths,
            date(2026, 8, 24),
            manifest=nport_manifest,
            series_class_index=build_sec_series_class_index(
                series_manifest,
                parse_sec_series_class(series_payload),
            ),
            product_bindings=(
                NportProductBinding(
                    product_entity_id="organizer-overseas-etf-1",
                    cik="0000123456",
                    class_ticker="SYNX",
                ),
                NportProductBinding(
                    product_entity_id="organizer-overseas-etf-uncovered",
                    cik="0000123456",
                    class_ticker="NOPE",
                ),
            ),
        )
    )
    relations = _records(mapped, "relation.relation_record")
    evidence = _records(mapped, "evidence.evidence_record")
    scopes = tuple(
        row for row in evidence if row["evidence_kind"] == "query_scope"
    )

    assert {row["predicate_id"] for row in relations} == {"holdsSecurity"}
    assert {
        (row["scope_completeness"], row["normalized_value"]["value"])
        for row in scopes
    } == {
        ("closed_world", "COVERED"),
        ("bounded_unknown", "NOT_COVERED"),
    }
