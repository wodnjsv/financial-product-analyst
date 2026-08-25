from __future__ import annotations

from financial_agent.ingestion.identity import (
    build_authoritative_identity_index,
)
from financial_agent.ingestion.models import (
    IdentifierCandidate as OrganizerIdentifierCandidate,
)
from financial_agent.ingestion.official.identity import (
    IdentityCandidate,
    OfficialIdentityIndex,
)


SYNTHETIC_ISIN = "ZZ0000000008"


def test_exact_strong_identifier_resolves_one_entity() -> None:
    index = OfficialIdentityIndex(
        exact_entries=((IdentityCandidate("ISIN", SYNTHETIC_ISIN), "security-1"),)
    )

    resolved = index.resolve_product(
        (IdentityCandidate("ISIN", SYNTHETIC_ISIN.lower()),)
    )

    assert resolved.status == "exact"
    assert resolved.entity_id == "security-1"
    assert resolved.matched_scheme == "ISIN"
    assert resolved.issue_code is None


def test_same_strong_identifier_for_two_entities_is_conflict() -> None:
    candidate = IdentityCandidate("ISIN", SYNTHETIC_ISIN)
    index = OfficialIdentityIndex(
        exact_entries=((candidate, "security-1"), (candidate, "security-2"))
    )

    resolved = index.resolve_product((candidate,))

    assert resolved.status == "conflict"
    assert resolved.entity_id is None
    assert resolved.issue_code == "IDENTITY_KEY_CONFLICT"


def test_two_strong_identifiers_pointing_to_different_entities_is_conflict() -> None:
    index = OfficialIdentityIndex(
        exact_entries=(
            (IdentityCandidate("ISIN", SYNTHETIC_ISIN), "security-1"),
            (IdentityCandidate("CUSIP", "000000AA1"), "security-2"),
        )
    )

    resolved = index.resolve_product(
        (
            IdentityCandidate("ISIN", SYNTHETIC_ISIN),
            IdentityCandidate("CUSIP", "000000AA1"),
        )
    )

    assert resolved.status == "conflict"
    assert resolved.issue_code == "IDENTITY_CANDIDATE_CONFLICT"


def test_name_and_ticker_alone_never_resolve() -> None:
    index = OfficialIdentityIndex(
        exact_entries=(
            (IdentityCandidate("NAME", "Synthetic ETF"), "product-1"),
            (IdentityCandidate("TICKER", "SYNX"), "product-1"),
        )
    )

    for candidate in (
        IdentityCandidate("NAME", "Synthetic ETF"),
        IdentityCandidate("TICKER", "SYNX"),
    ):
        resolved = index.resolve_product((candidate,))
        assert resolved.status == "unresolved"
        assert resolved.entity_id is None
        assert resolved.issue_code == "NO_EXACT_IDENTITY"


def test_unique_cik_and_class_ticker_resolves_sec_series() -> None:
    index = OfficialIdentityIndex(
        compound_entries=(
            (
                "SEC_CIK_CLASS_TICKER",
                ("0000123456", "synx"),
                "series-1",
            ),
        )
    )

    resolved = index.resolve_compound_product(
        "SEC_CIK_CLASS_TICKER", ("123456", "SYNX")
    )

    assert resolved.status == "exact"
    assert resolved.entity_id == "series-1"
    assert resolved.matched_scheme == "SEC_CIK_CLASS_TICKER"


def test_same_cik_and_class_ticker_for_two_series_is_conflict() -> None:
    index = OfficialIdentityIndex(
        compound_entries=(
            ("SEC_CIK_CLASS_TICKER", ("123456", "SYNX"), "series-1"),
            ("SEC_CIK_CLASS_TICKER", ("0000123456", "synx"), "series-2"),
        )
    )

    resolved = index.resolve_compound_product(
        "SEC_CIK_CLASS_TICKER", ("123456", "SYNX")
    )

    assert resolved.status == "conflict"
    assert resolved.issue_code == "IDENTITY_KEY_CONFLICT"


def test_invalid_isin_is_not_repaired_or_resolved() -> None:
    index = OfficialIdentityIndex(
        exact_entries=(
            (IdentityCandidate("ISIN", "ZZ0000000000"), "security-1"),
        )
    )

    resolved = index.resolve_product(
        (IdentityCandidate("ISIN", "ZZ0000000000"),)
    )

    assert resolved.status == "unresolved"
    assert resolved.issue_code == "NO_EXACT_IDENTITY"


def test_source_local_holding_id_is_scoped_by_snapshot() -> None:
    index = OfficialIdentityIndex(
        exact_entries=(
            (
                IdentityCandidate(
                    "SEC_NPORT_HOLDING_ID", "snapshot-a/HOLDING-1"
                ),
                "security-a",
            ),
            (
                IdentityCandidate(
                    "SEC_NPORT_HOLDING_ID", "snapshot-b/HOLDING-1"
                ),
                "security-b",
            ),
        )
    )

    resolved = index.resolve_product(
        (
            IdentityCandidate(
                "SEC_NPORT_HOLDING_ID", "snapshot-a/HOLDING-1"
            ),
        )
    )

    assert resolved.status == "exact"
    assert resolved.entity_id == "security-a"


def _organizer_index(*natural_keys: str):
    return build_authoritative_identity_index(
        tuple(
            OrganizerIdentifierCandidate(
                source_code="PREF02N001",
                row_number=row_number,
                natural_key=natural_key,
                entity_role="OverseasETF",
                scheme="ISIN",
                value=SYNTHETIC_ISIN,
            )
            for row_number, natural_key in enumerate(natural_keys, start=2)
        )
    )


def test_official_identity_reuses_one_organizer_authoritative_isin() -> None:
    organizer_index = _organizer_index("organizer-product-1")
    canonical = organizer_index.resolve("ISIN", SYNTHETIC_ISIN)
    assert canonical.canonical_identity is not None
    index = OfficialIdentityIndex(organizer_index=organizer_index)

    resolved = index.resolve_product(
        (IdentityCandidate("ISIN", SYNTHETIC_ISIN),)
    )

    assert resolved.status == "exact"
    assert resolved.entity_id == canonical.canonical_identity.entity_id


def test_official_identity_rejects_an_ambiguous_organizer_isin() -> None:
    index = OfficialIdentityIndex(
        organizer_index=_organizer_index(
            "organizer-product-1", "organizer-product-2"
        )
    )

    resolved = index.resolve_product(
        (IdentityCandidate("ISIN", SYNTHETIC_ISIN),)
    )

    assert resolved.status == "conflict"
    assert resolved.entity_id is None
    assert resolved.issue_code == "ORGANIZER_IDENTITY_AMBIGUOUS"
