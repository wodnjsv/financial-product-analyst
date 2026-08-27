from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

import pytest

from financial_agent.ingestion.official.capture import (
    APPROVED_CAPTURE_SPECS,
    OfficialCaptureConfigurationError,
    capture_approved_official_sources,
    capture_local_krx_holdings,
    load_existing_capture,
    load_capture_configuration,
)
from financial_agent.ingestion.official.ecos_fx import (
    map_ecos_fx,
    parse_ecos_731y001,
)
from financial_agent.ingestion.official_pipeline import (
    load_official_manifests,
    verify_official_snapshot_objects,
)
from financial_agent.ingestion.sources import SourceVerificationError


RUN_OFFICIAL_DATA = os.getenv("RUN_OFFICIAL_DATA_TESTS") == "1"
RUN_CURRENT_ECOS = os.getenv("RUN_CURRENT_ECOS_TESTS") == "1"
CURRENT_ECOS_CAPTURE_ROOT = os.getenv(
    "FINANCIAL_AGENT_CURRENT_ECOS_CAPTURE_ROOT"
)
OFFICIAL_ENVIRONMENT = (
    "FINANCIAL_AGENT_KRX_API_KEY",
    "FINANCIAL_AGENT_ECOS_API_KEY",
    "FINANCIAL_AGENT_SEC_USER_AGENT",
    "FINANCIAL_AGENT_KRX_HOLDINGS_ROOT",
    "FINANCIAL_AGENT_OFFICIAL_OUTPUT_ROOT",
)
HAS_OFFICIAL_CONFIGURATION = all(
    os.getenv(name) for name in OFFICIAL_ENVIRONMENT
)


@pytest.fixture(scope="session", autouse=True)
def _require_explicit_official_configuration() -> None:
    if RUN_OFFICIAL_DATA and not HAS_OFFICIAL_CONFIGURATION:
        pytest.fail("OFFICIAL_DATA_CONFIGURATION_MISSING", pytrace=False)
    if RUN_CURRENT_ECOS and CURRENT_ECOS_CAPTURE_ROOT is None:
        pytest.fail("CURRENT_ECOS_CONFIGURATION_MISSING", pytrace=False)


def test_capture_configuration_fails_closed_without_every_required_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in OFFICIAL_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FINANCIAL_AGENT_KRX_API_KEY", "SYNTHETIC-KRX-SECRET")

    with pytest.raises(OfficialCaptureConfigurationError) as captured:
        load_capture_configuration(os.environ)

    assert captured.value.code == "OFFICIAL_SOURCE_CONFIGURATION_MISSING"
    assert captured.value.__cause__ is None
    assert "SYNTHETIC-KRX-SECRET" not in str(captured.value)
    assert "SYNTHETIC-KRX-SECRET" not in repr(captured.value)


def test_capture_configuration_keeps_credentials_out_of_repr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = {
        "FINANCIAL_AGENT_KRX_API_KEY": "SYNTHETIC-KRX-SECRET",
        "FINANCIAL_AGENT_ECOS_API_KEY": "SYNTHETIC-ECOS-SECRET",
        "FINANCIAL_AGENT_SEC_USER_AGENT": (
            "Financial Product Agent test@example.invalid"
        ),
        "FINANCIAL_AGENT_KRX_HOLDINGS_ROOT": str(tmp_path / "holdings"),
        "FINANCIAL_AGENT_OFFICIAL_OUTPUT_ROOT": str(tmp_path / "capture"),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    configuration = load_capture_configuration(os.environ)
    rendered = repr(configuration)

    assert configuration.holdings_root == tmp_path / "holdings"
    assert configuration.output_root == tmp_path / "capture"
    assert "SYNTHETIC-KRX-SECRET" not in rendered
    assert "SYNTHETIC-ECOS-SECRET" not in rendered
    assert "test@example.invalid" not in rendered


def test_capture_plan_contains_only_the_six_approved_source_codes() -> None:
    assert tuple(spec.source_code for spec in APPROVED_CAPTURE_SPECS) == (
        "KRX_KOSPI_BASIC",
        "KRX_KOSDAQ_BASIC",
        "ECOS_731Y001",
        "SEC_SERIES_CLASS_20260601",
        "SEC_NPORT_2026Q2",
        "KRX_ETF_PDF",
    )
    assert all(
        spec.cutoff_date.isoformat() == "2026-08-24"
        for spec in APPROVED_CAPTURE_SPECS
    )
    domestic_market = tuple(
        spec
        for spec in APPROVED_CAPTURE_SPECS
        if spec.source_code
        in {
            "KRX_KOSPI_BASIC",
            "KRX_KOSDAQ_BASIC",
            "KRX_ETF_PDF",
        }
    )
    assert {
        spec.applicable_date.isoformat()
        for spec in domestic_market
        if spec.applicable_date is not None
    } == {"2026-08-22"}
    assert next(
        spec.applicable_date
        for spec in APPROVED_CAPTURE_SPECS
        if spec.source_code == "ECOS_731Y001"
    ).isoformat() == "2026-08-24"
    assert all(
        "manager" not in spec.source_code.lower()
        for spec in APPROVED_CAPTURE_SPECS
    )
    assert next(
        spec.publisher_code
        for spec in APPROVED_CAPTURE_SPECS
        if spec.source_code == "ECOS_731Y001"
    ) == "BOK"
    nport = next(
        spec
        for spec in APPROVED_CAPTURE_SPECS
        if spec.source_code == "SEC_NPORT_2026Q2"
    )
    assert nport.published_at == datetime(2026, 6, 30, tzinfo=UTC)
    assert nport.available_at == datetime(2026, 7, 9, tzinfo=UTC)


class _Response:
    def __init__(self, payload: bytes, content_type: str) -> None:
        self._payload = payload
        self._offset = 0
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(payload)),
        }

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _Opener:
    def __init__(self, *, fail_after: int | None = None) -> None:
        self.requests: list[Request] = []
        self.fail_after = fail_after

    def open(self, request: object) -> _Response:
        assert isinstance(request, Request)
        self.requests.append(request)
        if self.fail_after is not None and len(self.requests) > self.fail_after:
            raise RuntimeError("SYNTHETIC-PRIVATE-TRANSPORT-DETAIL")
        if request.full_url.endswith(".csv") or request.full_url.endswith(".zip"):
            return _Response(b"synthetic official file", "application/octet-stream")
        return _Response(b'{"synthetic":true}', "application/json")


def _configured_capture(tmp_path: Path) -> object:
    holdings_root = tmp_path / "holdings"
    holdings_root.mkdir()
    (holdings_root / "123456_20260822.csv").write_text(
        "종목코드,구성종목명,주식수(계약수),평가금액,시가총액,시가총액 구성비중\n"
        "KR7005930003,합성종목,1,1,1,1\n",
        "utf-8",
    )
    return load_capture_configuration(
        {
            "FINANCIAL_AGENT_KRX_API_KEY": "SYNTHETIC-KRX-SECRET",
            "FINANCIAL_AGENT_ECOS_API_KEY": "SYNTHETIC-ECOS-SECRET",
            "FINANCIAL_AGENT_SEC_USER_AGENT": (
                "Financial Product Agent test@example.invalid"
            ),
            "FINANCIAL_AGENT_KRX_HOLDINGS_ROOT": str(holdings_root),
            "FINANCIAL_AGENT_OFFICIAL_OUTPUT_ROOT": str(tmp_path / "capture"),
        }
    )


def test_capture_writes_canonical_manifests_without_credentials(
    tmp_path: Path,
) -> None:
    configuration = _configured_capture(tmp_path)
    opener = _Opener()

    result = capture_approved_official_sources(configuration, opener=opener)

    manifests = load_official_manifests(result.manifest_root)
    assert result.object_count == 6
    assert len(manifests) == 6
    assert {manifest.source_code for manifest in manifests} == {
        spec.source_code for spec in APPROVED_CAPTURE_SPECS
    }
    assert all(request.get_method() == "GET" for request in opener.requests)
    assert all("basDd=20260822" in request.full_url for request in opener.requests[:2])
    assert "/20260824/20260824" in opener.requests[2].full_url
    assert opener.requests[0].get_header("Auth_key") == "SYNTHETIC-KRX-SECRET"
    assert (
        opener.requests[-1].get_header("User-agent")
        == "Financial Product Agent test@example.invalid"
    )

    written = b"".join(
        path.read_bytes()
        for path in sorted(result.output_root.rglob("*"))
        if path.is_file()
    )
    assert b"SYNTHETIC-KRX-SECRET" not in written
    assert b"SYNTHETIC-ECOS-SECRET" not in written
    assert b"test@example.invalid" not in written


def test_capture_failure_never_publishes_a_partial_output(
    tmp_path: Path,
) -> None:
    configuration = _configured_capture(tmp_path)

    with pytest.raises(SourceVerificationError) as captured:
        capture_approved_official_sources(
            configuration,
            opener=_Opener(fail_after=1),
        )

    assert captured.value.code == "OFFICIAL_CAPTURE_FAILED"
    assert not configuration.output_root.exists()
    assert "SYNTHETIC-PRIVATE-TRANSPORT-DETAIL" not in str(captured.value)


def test_local_holdings_capture_needs_no_api_configuration(
    tmp_path: Path,
) -> None:
    holdings_root = tmp_path / "holdings"
    holdings_root.mkdir()
    source = holdings_root / "123456_20260822.csv"
    source.write_text(
        "종목코드,구성종목명,주식수(계약수),평가금액,시가총액,"
        "시가총액 구성비중\n"
        "005930,삼성전자,1,1,1,1\n",
        "cp949",
    )

    capture = capture_local_krx_holdings(
        holdings_root=holdings_root,
        output_root=tmp_path / "capture",
    )
    manifests = load_official_manifests(capture.manifest_root)

    assert capture.source_count == 1
    assert capture.object_count == 1
    assert capture.manifest_count == 1
    assert capture.eligible_start == "2026-08-22"
    assert capture.eligible_end == "2026-08-24"
    assert manifests[0].applicable_date.isoformat() == "2026-08-22"
    assert manifests[0].objects[0].object_name == source.name


def test_capture_official_cli_reports_only_safe_aggregates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from financial_agent.ingestion import cli

    configuration = object()
    monkeypatch.setattr(
        cli,
        "load_capture_configuration",
        lambda environment: configuration,
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "capture_approved_official_sources",
        lambda observed: SimpleNamespace(
            source_count=6,
            object_count=1_134,
            total_bytes=123_456,
            eligible_start="2026-06-01",
            eligible_end="2026-08-24",
        )
        if observed is configuration
        else None,
        raising=False,
    )

    assert cli.main(["capture-official"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.strip() == (
        "OFFICIAL_CAPTURE_OK sources=6 objects=1134 bytes=123456 "
        "eligible=2026-06-01..2026-08-24"
    )


@pytest.mark.official_data
@pytest.mark.skipif(
    not RUN_CURRENT_ECOS,
    reason="explicit current-ECOS gate is disabled",
)
def test_current_ecos_snapshot_has_four_exact_cutoff_eligible_rates() -> None:
    root = Path(CURRENT_ECOS_CAPTURE_ROOT or "")
    manifests = load_official_manifests(root / "manifests")
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest.source_code == "ECOS_731Y001"
    assert manifest.applicable_date == date(2026, 8, 24)
    assert manifest.cutoff_date == date(2026, 8, 24)
    verified = verify_official_snapshot_objects(manifests, root / "objects")
    item = manifest.objects[0]
    payload = verified[(manifest.snapshot_id, item.object_key)].read_bytes()
    raw_rows = json.loads(payload.decode("utf-8"))["StatisticSearch"]["row"]
    assert len(raw_rows) == 43

    mapped = map_ecos_fx(manifest, parse_ecos_731y001(payload))
    observations = {
        str(observation["metric_id"]): observation
        for row in mapped
        for observation in row.records_by_table[
            "observation.observation_record"
        ]
    }
    assert {
        metric_id: observation["numeric_value"]
        for metric_id, observation in observations.items()
    } == {
        "ecos_731y001_krw_per_usd": Decimal("1383.6"),
        "ecos_731y001_krw_per_100_jpy": Decimal("870.44"),
        "ecos_731y001_krw_per_eur": Decimal("1615.49"),
        "ecos_731y001_krw_per_cny": Decimal("205.55"),
    }
    assert {
        observation["applicable_date"]
        for observation in observations.values()
    } == {date(2026, 8, 24)}


@pytest.mark.official_data
@pytest.mark.skipif(
    not RUN_OFFICIAL_DATA,
    reason="explicit official-data gate is disabled",
)
def test_live_official_capture_is_complete_and_reproducibly_loadable() -> None:
    configuration = load_capture_configuration(os.environ)

    assert configuration.holdings_root.is_dir()
    assert configuration.output_root.is_absolute()
    capture = (
        load_existing_capture(configuration.output_root)
        if configuration.output_root.exists()
        else capture_approved_official_sources(configuration)
    )
    manifests = load_official_manifests(capture.manifest_root)
    expected_objects = (
        len(tuple(configuration.holdings_root.glob("*.csv"))) + 5
    )

    assert capture.source_count == 6
    assert capture.object_count == expected_objects
    assert capture.manifest_count == expected_objects
    assert capture.total_bytes > 0
    assert capture.eligible_start == "2026-06-01"
    assert capture.eligible_end == "2026-08-24"
    nport = next(
        manifest
        for manifest in manifests
        if manifest.source_code == "SEC_NPORT_2026Q2"
    )
    assert nport.published_at == datetime(2026, 6, 30, tzinfo=UTC)
    assert nport.available_at == datetime(2026, 7, 9, tzinfo=UTC)
