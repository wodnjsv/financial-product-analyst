from financial_agent.ingestion.mapping.asset_managers import (
    resolve_etf_asset_manager,
)


def test_bilingual_samsung_values_resolve_to_one_official_manager() -> None:
    result = resolve_etf_asset_manager(
        "삼성",
        "Samsung Asset Management Co Ltd",
    )

    assert result.status == "reviewed"
    assert result.identity is not None
    assert result.identity.key == "samsung_asset_management"
    assert result.identity.canonical_name == "삼성자산운용"
    assert result.identity.dart_corp_code == "00260453"
    assert result.supporting_fields == (
        "cu_fund_mgmt_co",
        "ref_fund_mgmt_co",
    )
    assert result.fallback_fields == ()


def test_malformed_korean_value_does_not_override_valid_refinitiv_manager() -> None:
    result = resolve_etf_asset_manager(
        "삼성KODEX레버리지증권상장지수투자신탁[주식-파생형]",
        "Samsung Asset Management Co Ltd",
    )

    assert result.status == "reviewed"
    assert result.identity is not None
    assert result.identity.canonical_name == "삼성자산운용"
    assert result.supporting_fields == ("ref_fund_mgmt_co",)
    assert result.fallback_fields == ("cu_fund_mgmt_co",)
    assert result.accepted_aliases == ("Samsung Asset Management Co Ltd",)


def test_reviewed_brand_resolves_when_refinitiv_value_is_blank() -> None:
    result = resolve_etf_asset_manager("TIGER", None)

    assert result.status == "reviewed"
    assert result.identity is not None
    assert result.identity.canonical_name == "미래에셋자산운용"
    assert result.supporting_fields == ("cu_fund_mgmt_co",)


def test_two_different_reviewed_managers_remain_a_conflict() -> None:
    result = resolve_etf_asset_manager(
        "삼성",
        "Mirae Asset Global Investments Co Ltd",
    )

    assert result.status == "conflict"
    assert result.identity is None
    assert result.supporting_fields == ()
    assert result.fallback_fields == (
        "cu_fund_mgmt_co",
        "ref_fund_mgmt_co",
    )


def test_equal_unreviewed_values_keep_the_safe_source_local_fallback() -> None:
    result = resolve_etf_asset_manager("합성 자산운용", "합성 자산운용")

    assert result.status == "source_equal"
    assert result.identity is not None
    assert result.identity.canonical_name == "합성 자산운용"
    assert result.identity.dart_corp_code is None
    assert result.supporting_fields == (
        "cu_fund_mgmt_co",
        "ref_fund_mgmt_co",
    )


def test_single_nonblank_unreviewed_value_remains_a_source_local_manager() -> None:
    result = resolve_etf_asset_manager("새운용사", None)

    assert result.status == "source_local"
    assert result.identity is not None
    assert result.identity.canonical_name == "새운용사"
    assert result.identity.dart_corp_code is None
    assert result.supporting_fields == ("cu_fund_mgmt_co",)


def test_only_dot_or_blank_values_are_treated_as_missing() -> None:
    for source_value in ("N/A", "-", "미상"):
        result = resolve_etf_asset_manager(source_value, None)

        assert result.status == "source_local"
        assert result.identity is not None
        assert result.identity.canonical_name == source_value
        assert result.identity.dart_corp_code is None


def test_dot_or_blank_values_do_not_create_a_manager() -> None:
    for cu_name, refinitiv_name in (
        (".", None),
        (" . ", None),
        (None, None),
        ("", ""),
        ("   ", "\t"),
    ):
        result = resolve_etf_asset_manager(cu_name, refinitiv_name)

        assert result.status == "unresolved"
        assert result.identity is None
