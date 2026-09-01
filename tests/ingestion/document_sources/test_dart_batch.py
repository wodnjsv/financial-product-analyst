from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from io import BytesIO
import json
from urllib.parse import parse_qs, urlparse

from financial_agent.ingestion.document_sources import (
    DartPublisherBinding,
    DartPublisherReconciliation,
    DocumentDiscoveryContext,
    discover_dart_candidates_by_publisher,
)
from financial_agent.ingestion.document_sources.dart import DartDocumentSourceAdapter
from financial_agent.ingestion.document_sources.dart_targets import (
    OrganizerDartProductRow,
    build_organizer_dart_inventory,
)


CUTOFF = date(2026, 8, 24)


def _inventory():
    rows = tuple(
        OrganizerDartProductRow(
            entity_id=f"product-{index}",
            canonical_name=product_name,
            product_family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value=f"PF-{index}",
            representative_entity_id=None,
            representative_name=None,
            manager_entity_id="manager-one",
            manager_name="한빛자산운용",
        )
        for index, product_name in enumerate(
            ("한빛 성장 펀드", "한빛 채권 펀드"), start=1
        )
    )
    return build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)


def _filing(
    product_name: str,
    receipt_no: str,
    *,
    receipt_date: str = "20260820",
    correction: str = "",
    rm: str = "",
) -> dict[str, str]:
    return {
        "corp_code": "00123456",
        "corp_name": "한빛자산운용",
        "stock_code": "",
        "corp_cls": "E",
        "report_nm": f"{correction}투자설명서(집합투자증권)[{product_name}]",
        "rcept_no": receipt_no,
        "flr_nm": "한빛자산운용",
        "rcept_dt": receipt_date,
        "rm": rm,
    }


class _Response(BytesIO):
    status = 200
    headers: Mapping[str, str] = {}


class _PublisherOpener:
    def __init__(self, filings: list[dict[str, str]]) -> None:
        self.filings = filings
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
        assert parsed.hostname == "opendart.fss.or.kr"
        assert parsed.path == "/api/list.json"
        query = parse_qs(parsed.query)
        assert query["corp_code"] == ["00123456"]
        assert query["page_no"] == ["1"]
        payload = {
            "status": "000",
            "message": "정상",
            "page_no": 1,
            "page_count": 100,
            "total_count": len(self.filings),
            "total_page": 1,
            "list": self.filings,
        }
        return _Response(json.dumps(payload).encode())


def _reconciliation() -> DartPublisherReconciliation:
    return DartPublisherReconciliation(
        bindings=(
            DartPublisherBinding(
                manager_entity_id="manager-one",
                manager_name="한빛자산운용",
                corp_code="00123456",
                corp_name="한빛자산운용",
                match_basis="official_name",
            ),
        ),
        failures=(),
        source_checksum="a" * 64,
    )


def _context() -> DocumentDiscoveryContext:
    return DocumentDiscoveryContext(
        cutoff_date=CUTOFF,
        dart_api_key="SYNTHETIC-SECRET",
        sec_user_agent=None,
        locator_registry_path=None,
    )


def test_one_publisher_page_serves_multiple_organizer_targets() -> None:
    inventory = _inventory()
    opener = _PublisherOpener(
        [
            _filing(
                "한빛 성장 펀드",
                "20260810000001",
                receipt_date="20260810",
                rm="정",
            ),
            _filing(
                "한빛 성장 펀드",
                "20260820000001",
                correction="[기재정정] ",
            ),
            _filing("한빛 채권 펀드", "20260820000002"),
        ]
    )

    result = discover_dart_candidates_by_publisher(
        inventory=inventory,
        reconciliation=_reconciliation(),
        adapter=DartDocumentSourceAdapter(opener),
        context=_context(),
    )

    assert len(opener.calls) == 1
    assert set(result.indexed_ids) == {target.target_key for target in inventory.targets}
    assert result.failed_ids == ()
    assert result.downloaded_ids == ()
    assert result.requested_publisher_codes == ("00123456",)
    assert {
        candidate.accession_or_receipt_id
        for disposition in result.dispositions
        for candidate in disposition.candidates
    } == {"20260820000001", "20260820000002"}
    assert {
        candidate.target_entity_id
        for disposition in result.dispositions
        for candidate in disposition.candidates
    } == {target.representative_entity_id for target in inventory.targets}


def test_multi_class_fund_binds_to_one_exact_publisher_filing() -> None:
    rows = tuple(
        OrganizerDartProductRow(
            entity_id=f"class-{index}",
            canonical_name=name,
            product_family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value=f"PF-{index}",
            representative_entity_id="representative-fund",
            representative_name="2000102M4800",
            manager_entity_id="manager-one",
            manager_name="한빛자산운용",
        )
        for index, name in enumerate(
            ("한빛 성장 펀드 A 클래스", "한빛 성장 펀드 C1 클래스"),
            start=1,
        )
    )
    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)
    opener = _PublisherOpener(
        [_filing("한빛 성장 펀드", "20260820000001")]
    )

    result = discover_dart_candidates_by_publisher(
        inventory=inventory,
        reconciliation=_reconciliation(),
        adapter=DartDocumentSourceAdapter(opener),
        context=_context(),
    )

    assert result.indexed_ids == ("public_fund:representative-fund",)
    assert result.failed_ids == ()
    assert result.dispositions[0].member_entity_ids == (
        "class-1",
        "class-2",
    )
    assert result.dispositions[0].resolved_product_name == "한빛 성장 펀드"


def test_publisher_search_continues_past_unparseable_other_product() -> None:
    exact = _filing(
        "한빛 성장 펀드",
        "20260205000001",
        receipt_date="20260205",
    )
    ambiguous = _filing(
        "한빛 성장 펀드] [다른 펀드",
        "20260820000001",
    )

    class WindowedPublisherOpener:
        def __init__(self) -> None:
            self.windows: list[tuple[str, str]] = []

        def open_no_redirect(
            self,
            url: str,
            *,
            method: str,
            headers: Mapping[str, str],
            timeout: float,
        ) -> _Response:
            del method, headers, timeout
            query = parse_qs(urlparse(url).query)
            window = (query["bgn_de"][0], query["end_de"][0])
            self.windows.append(window)
            filings = (
                [ambiguous]
                if window == ("20260224", "20260824")
                else [exact]
            )
            return _Response(json.dumps({
                "status": "000",
                "message": "정상",
                "page_no": 1,
                "page_count": 100,
                "total_count": 1,
                "total_page": 1,
                "list": filings,
            }).encode())

    opener = WindowedPublisherOpener()
    result = DartDocumentSourceAdapter(opener).discover_publisher_targets(
        corp_code="00123456",
        publisher_name="한빛자산운용",
        targets=(("target-one", "한빛 성장 펀드", "product-one"),),
        context=_context(),
    )

    assert result.target_results[0][1].candidates[0].accession_or_receipt_id == (
        "20260205000001"
    )
    assert opener.windows == [
        ("20260224", "20260824"),
        ("20250823", "20260223"),
    ]


def test_dart_only_filing_never_expands_inventory_or_reaches_attachment_access() -> None:
    inventory = _inventory()
    opener = _PublisherOpener(
        [
            _filing("한빛 성장 펀드", "20260820000001"),
            _filing("한빛 채권 펀드", "20260820000002"),
            _filing("DART 전용 상품", "20260820000003"),
        ]
    )

    result = discover_dart_candidates_by_publisher(
        inventory=inventory,
        reconciliation=_reconciliation(),
        adapter=DartDocumentSourceAdapter(opener),
        context=_context(),
    )

    expected = {target.target_key for target in inventory.targets}
    assert set(result.indexed_ids) | set(result.failed_ids) == expected
    assert set(result.indexed_ids).isdisjoint(result.failed_ids)
    assert set(result.downloaded_ids) <= expected
    assert all("document.xml" not in url for url in opener.calls)
    assert all(
        candidate.accession_or_receipt_id != "20260820000003"
        for disposition in result.dispositions
        for candidate in disposition.candidates
    )
    assert (
        "20260820000003",
        "dart_filing_not_in_organizer_inventory",
    ) in {
        (item.receipt_id, item.reason_code) for item in result.rejected_filings
    }


def test_missing_and_ambiguous_managers_fail_without_network() -> None:
    rows = (
        OrganizerDartProductRow(
            entity_id="product-missing",
            canonical_name="Missing Manager Fund",
            product_family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-MISSING",
            representative_entity_id=None,
            representative_name=None,
            manager_entity_id=None,
            manager_name=None,
        ),
        OrganizerDartProductRow(
            entity_id="product-ambiguous",
            canonical_name="Ambiguous Manager Fund",
            product_family="public_fund",
            identifier_scheme="PRFD_ITM_NO",
            identifier_value="PF-AMBIGUOUS",
            representative_entity_id=None,
            representative_name=None,
            manager_entity_id="manager-a",
            manager_name="Manager A",
        ),
        OrganizerDartProductRow(
            entity_id="product-ambiguous",
            canonical_name="Ambiguous Manager Fund",
            product_family="public_fund",
            identifier_scheme="KSD_PRODUCT",
            identifier_value="KSD-AMBIGUOUS",
            representative_entity_id=None,
            representative_name=None,
            manager_entity_id="manager-b",
            manager_name="Manager B",
        ),
    )
    inventory = build_organizer_dart_inventory("organizer-v1", CUTOFF, rows)
    opener = _PublisherOpener([])

    result = discover_dart_candidates_by_publisher(
        inventory=inventory,
        reconciliation=DartPublisherReconciliation(
            bindings=(), failures=(), source_checksum="a" * 64
        ),
        adapter=DartDocumentSourceAdapter(opener),
        context=_context(),
    )

    assert result.indexed_ids == ()
    assert set(result.failed_ids) == {
        target.target_key for target in inventory.targets
    }
    assert opener.calls == []
    assert {item.reason_code for item in result.dispositions} == {
        "dart_manager_binding_missing",
        "dart_manager_binding_ambiguous",
    }
