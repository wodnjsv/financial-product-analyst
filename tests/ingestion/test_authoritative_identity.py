from __future__ import annotations

import pytest

from financial_agent.ingestion.identity import (
    AuthoritativeIdentityValidationError,
    build_authoritative_identity_index,
    collect_organizer_identifier_candidates,
)
from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.models import IdentifierCandidate


DOMESTIC_ETF_ISIN = "KR7005930003"
OVERSEAS_ETF_ISIN = "US0378331005"


def _candidate(
    *,
    source_code: str,
    row_number: int,
    natural_key: str,
    entity_role: str,
    scheme: str,
    value: str,
) -> IdentifierCandidate:
    return IdentifierCandidate(
        source_code=source_code,
        row_number=row_number,
        natural_key=natural_key,
        entity_role=entity_role,
        scheme=scheme,
        value=value,
    )


def _domestic_etf_candidates() -> tuple[IdentifierCandidate, ...]:
    return (
        _candidate(
            source_code="PREF01N001",
            row_number=2,
            natural_key=DOMESTIC_ETF_ISIN,
            entity_role="DomesticETF",
            scheme="PREF01_PD_ITM_NO",
            value=DOMESTIC_ETF_ISIN,
        ),
        _candidate(
            source_code="PREF01N001",
            row_number=2,
            natural_key=DOMESTIC_ETF_ISIN,
            entity_role="DomesticETF",
            scheme="ISIN",
            value=DOMESTIC_ETF_ISIN,
        ),
    )


def _public_fund_candidates() -> tuple[IdentifierCandidate, ...]:
    return (
        _candidate(
            source_code="PRFD01N001",
            row_number=3,
            natural_key="FUND-SHARE-1",
            entity_role="FundShareClass",
            scheme="PRFD_ITM_NO",
            value="FUND-SHARE-1",
        ),
        _candidate(
            source_code="PRFD01N001",
            row_number=3,
            natural_key="FUND-SHARE-1",
            entity_role="FundShareClass",
            scheme="ISIN",
            value=DOMESTIC_ETF_ISIN,
        ),
    )


def test_domestic_etf_and_public_fund_share_one_canonical_identity() -> None:
    index = build_authoritative_identity_index(
        _domestic_etf_candidates() + _public_fund_candidates()
    )

    result = index.resolve("ISIN", DOMESTIC_ETF_ISIN)

    assert result.status == "MATCHED"
    assert result.canonical_identity is not None
    assert result.canonical_identity.entity_id == stable_id(
        "product", "PREF01N001", DOMESTIC_ETF_ISIN
    )
    assert result.canonical_identity.owner_source_code == "PREF01N001"
    assert result.canonical_identity.owner_natural_key == DOMESTIC_ETF_ISIN
    assert result.canonical_identity.roles == frozenset(
        {"DomesticETF", "FundShareClass"}
    )
    assert (
        index.resolve("PRFD_ITM_NO", "FUND-SHARE-1").canonical_identity
        == result.canonical_identity
    )


def test_identity_output_is_stable_under_reversed_input_order() -> None:
    candidates = _domestic_etf_candidates() + _public_fund_candidates()

    forward = build_authoritative_identity_index(candidates)
    reversed_index = build_authoritative_identity_index(tuple(reversed(candidates)))

    assert forward.identities == reversed_index.identities
    assert forward.resolve("ISIN", DOMESTIC_ETF_ISIN) == reversed_index.resolve(
        "ISIN", DOMESTIC_ETF_ISIN
    )


def test_duplicate_global_identifier_for_distinct_products_is_ambiguous() -> None:
    index = build_authoritative_identity_index(
        (
            _candidate(
                source_code="PREF02N001",
                row_number=2,
                natural_key="OVERSEAS-1",
                entity_role="OverseasETF",
                scheme="ISIN",
                value=OVERSEAS_ETF_ISIN,
            ),
            _candidate(
                source_code="PREF02N001",
                row_number=3,
                natural_key="OVERSEAS-2",
                entity_role="OverseasETF",
                scheme="ISIN",
                value=OVERSEAS_ETF_ISIN,
            ),
        )
    )

    result = index.resolve("ISIN", OVERSEAS_ETF_ISIN)

    assert result.status == "AMBIGUOUS"
    assert result.canonical_identity is None


def test_etf_and_etn_are_never_merged() -> None:
    index = build_authoritative_identity_index(
        (
            _candidate(
                source_code="PREF02N001",
                row_number=2,
                natural_key="OVERSEAS-ETF",
                entity_role="OverseasETF",
                scheme="ISIN",
                value=OVERSEAS_ETF_ISIN,
            ),
            _candidate(
                source_code="PREF02N001",
                row_number=3,
                natural_key="OVERSEAS-ETN",
                entity_role="OverseasETN",
                scheme="ISIN",
                value=OVERSEAS_ETF_ISIN,
            ),
        )
    )

    assert index.resolve("ISIN", OVERSEAS_ETF_ISIN).status == "AMBIGUOUS"


def test_one_source_product_cannot_carry_incompatible_roles() -> None:
    candidates = (
        _candidate(
            source_code="PREF02N001",
            row_number=2,
            natural_key="CONFLICTING-PRODUCT",
            entity_role="OverseasETF",
            scheme="PREF02_PD_ITM_NO",
            value="CONFLICTING-PRODUCT",
        ),
        _candidate(
            source_code="PREF02N001",
            row_number=3,
            natural_key="CONFLICTING-PRODUCT",
            entity_role="OverseasETN",
            scheme="PREF02_PD_ITM_NO",
            value="CONFLICTING-PRODUCT",
        ),
    )

    with pytest.raises(AuthoritativeIdentityValidationError) as failure:
        build_authoritative_identity_index(candidates)

    assert failure.value.issue_counts == {"IDENTITY_ROLE_CONFLICT": 1}


def test_source_local_identifiers_do_not_merge_on_equal_raw_values() -> None:
    index = build_authoritative_identity_index(
        (
            _candidate(
                source_code="PREF01N001",
                row_number=2,
                natural_key="LOCAL-1",
                entity_role="DomesticETF",
                scheme="PREF01_PD_ITM_NO",
                value="SAME-LOCAL-VALUE",
            ),
            _candidate(
                source_code="PRFD01N001",
                row_number=2,
                natural_key="LOCAL-2",
                entity_role="FundShareClass",
                scheme="PRFD_ITM_NO",
                value="SAME-LOCAL-VALUE",
            ),
        )
    )

    domestic = index.resolve("PREF01_PD_ITM_NO", "SAME-LOCAL-VALUE")
    fund = index.resolve("PRFD_ITM_NO", "SAME-LOCAL-VALUE")

    assert domestic.status == fund.status == "MATCHED"
    assert domestic.canonical_identity != fund.canonical_identity


@pytest.mark.parametrize(
    ("scheme", "value", "issue_code"),
    (
        ("ISIN", "KR7005930004", "IDENTITY_ISIN_INVALID"),
        ("ISIN", "  ", "IDENTITY_VALUE_BLANK"),
    ),
)
def test_invalid_candidates_fail_with_aggregate_only_diagnostics(
    scheme: str,
    value: str,
    issue_code: str,
) -> None:
    with pytest.raises(AuthoritativeIdentityValidationError) as failure:
        build_authoritative_identity_index(
            (
                _candidate(
                    source_code="PREF01N001",
                    row_number=2,
                    natural_key="PRIVATE-NATURAL-KEY",
                    entity_role="DomesticETF",
                    scheme=scheme,
                    value=value,
                ),
            )
        )

    assert failure.value.issue_counts == {issue_code: 1}
    if value.strip():
        assert value.strip() not in str(failure.value)
    assert "PRIVATE-NATURAL-KEY" not in str(failure.value)


def test_unknown_or_invalid_lookup_returns_not_found() -> None:
    index = build_authoritative_identity_index(_domestic_etf_candidates())

    assert index.resolve("ISIN", "US0000000000").status == "NOT_FOUND"
    assert index.resolve("UNKNOWN", "value").status == "NOT_FOUND"


def test_organizer_candidate_collection_keeps_source_and_global_identifiers() -> None:
    candidates = collect_organizer_identifier_candidates(
        "PREF01N001",
        (
            {
                "pd_itm_no": DOMESTIC_ETF_ISIN,
                "pd_isin_cd": DOMESTIC_ETF_ISIN,
                "pd_grp_no": "ETF",
            },
        ),
    )

    assert candidates == (
        IdentifierCandidate(
            source_code="PREF01N001",
            row_number=2,
            natural_key=DOMESTIC_ETF_ISIN,
            entity_role="DomesticETF",
            scheme="PREF01_PD_ITM_NO",
            value=DOMESTIC_ETF_ISIN,
        ),
        IdentifierCandidate(
            source_code="PREF01N001",
            row_number=2,
            natural_key=DOMESTIC_ETF_ISIN,
            entity_role="DomesticETF",
            scheme="ISIN",
            value=DOMESTIC_ETF_ISIN,
        ),
    )


def test_explicit_domestic_isin_must_match_the_isin_shaped_primary_key() -> None:
    with pytest.raises(AuthoritativeIdentityValidationError) as failure:
        collect_organizer_identifier_candidates(
            "PREF01N001",
            (
                {
                    "pd_itm_no": DOMESTIC_ETF_ISIN,
                    "pd_isin_cd": OVERSEAS_ETF_ISIN,
                    "pd_grp_no": "ETF",
                },
            ),
        )

    assert failure.value.issue_counts == {"IDENTITY_EXPLICIT_ISIN_MISMATCH": 1}
    assert DOMESTIC_ETF_ISIN not in str(failure.value)
    assert OVERSEAS_ETF_ISIN not in str(failure.value)


def test_public_fund_identifier_sentinel_is_not_promoted() -> None:
    candidates = collect_organizer_identifier_candidates(
        "PRFD01N001",
        ({"itm_no": "FUND-1", "ksd_itm_no": "KR0000000000"},),
    )

    assert candidates == (
        IdentifierCandidate(
            source_code="PRFD01N001",
            row_number=2,
            natural_key="FUND-1",
            entity_role="FundShareClass",
            scheme="PRFD_ITM_NO",
            value="FUND-1",
        ),
    )


def test_public_fund_ksd_identifier_only_becomes_isin_when_checksum_valid() -> None:
    candidates = collect_organizer_identifier_candidates(
        "PRFD01N001",
        ({"itm_no": "FUND-1", "ksd_itm_no": "KSD-SOURCE-ONLY"},),
    )

    assert tuple(item.scheme for item in candidates) == (
        "PRFD_ITM_NO",
        "KSD_PRODUCT",
    )
