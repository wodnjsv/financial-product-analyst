from __future__ import annotations

from datetime import date
from io import BytesIO
from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from financial_agent.ingestion.document_sources import (
    DartPublisherDataError,
    fetch_dart_corporation_codes,
    reconcile_dart_publishers,
)
from financial_agent.ingestion.document_sources.dart_targets import (
    OrganizerDartProductRow,
    build_organizer_dart_inventory,
)


CUTOFF = date(2026, 8, 24)


def _inventory(*managers: tuple[str, str]):
    rows = tuple(
        OrganizerDartProductRow(
            entity_id=f"product-{index}",
            canonical_name=f"Product {index}",
            product_family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value=f"PF-{index}",
            representative_entity_id=None,
            representative_name=None,
            manager_entity_id=manager_id,
            manager_name=manager_name,
        )
        for index, (manager_id, manager_name) in enumerate(managers, start=1)
    )
    return build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)


def _corp_code_zip(*entries: tuple[str, str]) -> bytes:
    lists = "".join(
        "<list>"
        f"<corp_code>{corp_code}</corp_code>"
        f"<corp_name>{corp_name}</corp_name>"
        "<stock_code></stock_code><modify_date>20260824</modify_date>"
        "</list>"
        for corp_code, corp_name in entries
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("CORPCODE.xml", f"<result>{lists}</result>".encode())
    return buffer.getvalue()


def _raw_xml_zip(xml: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("CORPCODE.xml", xml.encode())
    return buffer.getvalue()


class _Response(BytesIO):
    status = 200
    headers: Mapping[str, str] = {}


class _CorpCodeOpener:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def open_no_redirect(
        self,
        url: str,
        *,
        method: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        self.calls.append(url)
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.hostname == "opendart.fss.or.kr"
        assert parsed.path == "/api/corpCode.xml"
        assert parse_qs(parsed.query)["crtfc_key"] == ["SYNTHETIC-SECRET"]
        return _Response(self.payload)


def test_corporation_codes_are_fetched_once_from_the_official_endpoint() -> None:
    expected = _corp_code_zip(("00123456", "한빛자산운용"))
    opener = _CorpCodeOpener(expected)

    actual = fetch_dart_corporation_codes(opener, "SYNTHETIC-SECRET")

    assert actual == expected
    assert len(opener.calls) == 1


def test_reconciles_only_exact_official_name_identifier_or_reviewed_alias() -> None:
    inventory = _inventory(
        ("manager-name", "한빛 자산운용"),
        ("manager-id", "Identifier Manager"),
        ("manager-alias", "00123456"),
        ("manager-unmatched", "한빛운용"),
    )
    payload = _corp_code_zip(
        ("00123456", "한빛  자산운용"),
        ("00222222", "공식 식별자 운용사"),
        ("00333333", "공식 별칭 운용사"),
    )

    result = reconcile_dart_publishers(
        inventory=inventory,
        corp_code_zip=payload,
        institution_identifiers={
            "manager-id": (("DART_CORP_CODE", "00222222"),),
            "manager-alias": (
                ("ORGANIZER_EXTERNAL_INSTITUTION", "00123456"),
            ),
        },
        reviewed_aliases={"manager-alias": "00333333"},
    )

    assert [
        (binding.manager_entity_id, binding.corp_code, binding.match_basis)
        for binding in result.bindings
    ] == [
        ("manager-alias", "00333333", "reviewed_alias"),
        ("manager-id", "00222222", "official_identifier"),
        ("manager-name", "00123456", "official_name"),
    ]
    assert [(item.manager_entity_id, item.reason_code) for item in result.failures] == [
        ("manager-unmatched", "dart_publisher_not_matched")
    ]
    assert len(result.source_checksum) == 64


def test_same_length_organizer_external_code_is_not_a_dart_corp_code() -> None:
    result = reconcile_dart_publishers(
        inventory=_inventory(("manager-code", "00123456")),
        corp_code_zip=_corp_code_zip(("00123456", "다른 공식 회사")),
        institution_identifiers={
            "manager-code": (
                ("ORGANIZER_EXTERNAL_INSTITUTION", "00123456"),
            )
        },
        reviewed_aliases={},
    )

    assert result.bindings == ()
    assert result.failures[0].reason_code == "dart_publisher_not_matched"


def test_one_to_many_official_name_is_ambiguous_and_abbreviation_is_not_guessed() -> None:
    result = reconcile_dart_publishers(
        inventory=_inventory(
            ("manager-duplicate", "같은운용사"),
            ("manager-abbreviation", "한빛운용"),
        ),
        corp_code_zip=_corp_code_zip(
            ("00111111", "같은운용사"),
            ("00222222", "같은운용사"),
            ("00333333", "한빛자산운용"),
        ),
        institution_identifiers={},
        reviewed_aliases={},
    )

    assert result.bindings == ()
    assert [(item.manager_entity_id, item.reason_code) for item in result.failures] == [
        ("manager-abbreviation", "dart_publisher_not_matched"),
        ("manager-duplicate", "dart_publisher_name_ambiguous"),
    ]


def test_reviewed_alias_must_be_anchored_to_an_inventory_manager() -> None:
    with pytest.raises(DartPublisherDataError) as raised:
        reconcile_dart_publishers(
            inventory=_inventory(("manager-one", "Manager One")),
            corp_code_zip=_corp_code_zip(("00111111", "Manager One")),
            institution_identifiers={},
            reviewed_aliases={"not-an-organizer-manager": "00111111"},
        )

    assert raised.value.code == "dart_reviewed_alias_not_anchored"


@pytest.mark.parametrize(
    "payload",
    (
        b"not-a-zip",
        _corp_code_zip(("not-eight", "Manager One")),
        _corp_code_zip(("00111111", "")),
        _raw_xml_zip(
            "<result><list><corp_code>00111111</corp_code>"
            "<corp_code>00222222</corp_code><corp_name>Manager One</corp_name>"
            "<stock_code></stock_code><modify_date>20260824</modify_date>"
            "</list></result>"
        ),
    ),
)
def test_malformed_corporation_code_archives_fail_closed(payload: bytes) -> None:
    with pytest.raises(DartPublisherDataError) as raised:
        reconcile_dart_publishers(
            inventory=_inventory(("manager-one", "Manager One")),
            corp_code_zip=payload,
            institution_identifiers={},
            reviewed_aliases={},
        )

    assert raised.value.code == "dart_corporation_codes_malformed"
