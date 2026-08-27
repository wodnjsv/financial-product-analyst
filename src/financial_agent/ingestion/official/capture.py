from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
import re
from pathlib import Path
import shutil
import tempfile
from typing import Literal
from typing import Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

from financial_agent.ingestion.sources import (
    SourceVerificationError,
    sha256_path,
    upload_verified_object,
)

from .models import OfficialObjectManifest, OfficialSnapshotManifest
from .snapshot import capture_http_object, write_canonical_manifest


_CUTOFF_DATE = date(2026, 8, 24)
_DOMESTIC_MARKET_DATE = date(2026, 8, 22)
_DOMESTIC_MARKET_DATE_TEXT = _DOMESTIC_MARKET_DATE.strftime("%Y%m%d")
_ECOS_DATE = date(2026, 8, 24)
_ECOS_DATE_TEXT = _ECOS_DATE.strftime("%Y%m%d")
_DAILY_AVAILABLE_AT = datetime(2026, 8, 24, 14, 59, 59, tzinfo=UTC)
_REAPPROVED_SEC_OBJECTS: Mapping[str, tuple[int, str]] = {
    "SEC_NPORT_2026Q2": (
        440_699_889,
        "077cc836a978a593b29012219395fbe9c303d5e930f5be3b5f4353c3b02296fc",
    ),
    "SEC_SERIES_CLASS_20260601": (
        8_051_163,
        "9fdb6d24157bbec44244366dfddebe2300404ab591da479cf537db884078af6a",
    ),
}


class OfficialCaptureConfigurationError(SourceVerificationError):
    def __init__(self) -> None:
        super().__init__(
            "OFFICIAL_SOURCE_CONFIGURATION_MISSING",
            "official source capture configuration is incomplete",
        )


class _Opener(Protocol):
    def open(self, request: object) -> object: ...


@dataclass(frozen=True, slots=True)
class OfficialCaptureSpec:
    source_code: str
    snapshot_id: str
    publisher_code: str
    access_kind: Literal[
        "krx_api", "ecos_api", "sec_file", "local_directory"
    ]
    endpoint: str | None
    object_name: str | None
    media_type: str
    maximum_bytes: int
    cutoff_date: date
    applicable_date: date | None
    published_at: datetime | None
    available_at: datetime
    vintage_date: date | None


@dataclass(frozen=True, slots=True, repr=False)
class OfficialCaptureConfiguration:
    krx_api_key: str
    ecos_api_key: str
    sec_user_agent: str
    holdings_root: Path
    output_root: Path


@dataclass(frozen=True, slots=True)
class OfficialCaptureResult:
    output_root: Path
    object_root: Path
    manifest_root: Path
    source_count: int
    object_count: int
    manifest_count: int
    total_bytes: int
    eligible_start: str
    eligible_end: str


APPROVED_CAPTURE_SPECS = (
    OfficialCaptureSpec(
        source_code="KRX_KOSPI_BASIC",
        snapshot_id=f"krx-kospi-basic-{_DOMESTIC_MARKET_DATE_TEXT}",
        publisher_code="KRX",
        access_kind="krx_api",
        endpoint="https://data-dbg.krx.co.kr/svc/apis/sto/stk_isu_base_info",
        object_name=f"krx-kospi-basic-{_DOMESTIC_MARKET_DATE_TEXT}.json",
        media_type="application/json",
        maximum_bytes=32 * 1024 * 1024,
        cutoff_date=_CUTOFF_DATE,
        applicable_date=_DOMESTIC_MARKET_DATE,
        published_at=None,
        available_at=_DAILY_AVAILABLE_AT,
        vintage_date=None,
    ),
    OfficialCaptureSpec(
        source_code="KRX_KOSDAQ_BASIC",
        snapshot_id=f"krx-kosdaq-basic-{_DOMESTIC_MARKET_DATE_TEXT}",
        publisher_code="KRX",
        access_kind="krx_api",
        endpoint="https://data-dbg.krx.co.kr/svc/apis/sto/ksq_isu_base_info",
        object_name=f"krx-kosdaq-basic-{_DOMESTIC_MARKET_DATE_TEXT}.json",
        media_type="application/json",
        maximum_bytes=48 * 1024 * 1024,
        cutoff_date=_CUTOFF_DATE,
        applicable_date=_DOMESTIC_MARKET_DATE,
        published_at=None,
        available_at=_DAILY_AVAILABLE_AT,
        vintage_date=None,
    ),
    OfficialCaptureSpec(
        source_code="ECOS_731Y001",
        snapshot_id=f"ecos-731y001-{_ECOS_DATE_TEXT}",
        publisher_code="BOK",
        access_kind="ecos_api",
        endpoint="https://ecos.bok.or.kr/api/StatisticSearch",
        object_name=f"ecos-731y001-{_ECOS_DATE_TEXT}.json",
        media_type="application/json",
        maximum_bytes=8 * 1024 * 1024,
        cutoff_date=_CUTOFF_DATE,
        applicable_date=_ECOS_DATE,
        published_at=None,
        available_at=_DAILY_AVAILABLE_AT,
        vintage_date=None,
    ),
    OfficialCaptureSpec(
        source_code="SEC_SERIES_CLASS_20260601",
        snapshot_id="sec-series-class-20260601",
        publisher_code="SEC",
        access_kind="sec_file",
        endpoint=(
            "https://www.sec.gov/files/investment/data/other/"
            "investment-company-series-class-information/"
            "investment-company-series-class-2026.csv"
        ),
        object_name="investment-company-series-class-2026.csv",
        media_type="application/octet-stream",
        maximum_bytes=16 * 1024 * 1024,
        cutoff_date=_CUTOFF_DATE,
        applicable_date=date(2026, 6, 1),
        published_at=datetime(2026, 6, 1, tzinfo=UTC),
        available_at=datetime(2026, 6, 1, tzinfo=UTC),
        vintage_date=date(2026, 6, 1),
    ),
    OfficialCaptureSpec(
        source_code="SEC_NPORT_2026Q2",
        snapshot_id="sec-nport-2026q2",
        publisher_code="SEC",
        access_kind="sec_file",
        endpoint=(
            "https://www.sec.gov/files/dera/data/form-n-port-data-sets/"
            "2026q2_nport.zip"
        ),
        object_name="2026q2_nport.zip",
        media_type="application/octet-stream",
        maximum_bytes=600 * 1024 * 1024,
        cutoff_date=_CUTOFF_DATE,
        applicable_date=None,
        published_at=datetime(2026, 6, 30, tzinfo=UTC),
        available_at=datetime(2026, 7, 9, tzinfo=UTC),
        vintage_date=date(2026, 6, 30),
    ),
    OfficialCaptureSpec(
        source_code="KRX_ETF_PDF",
        snapshot_id=f"krx-etf-pdf-{_DOMESTIC_MARKET_DATE_TEXT}",
        publisher_code="KRX",
        access_kind="local_directory",
        endpoint=None,
        object_name=None,
        media_type="text/csv",
        maximum_bytes=64 * 1024 * 1024,
        cutoff_date=_CUTOFF_DATE,
        applicable_date=_DOMESTIC_MARKET_DATE,
        published_at=None,
        available_at=_DAILY_AVAILABLE_AT,
        vintage_date=None,
    ),
)


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value.strip():
        raise OfficialCaptureConfigurationError() from None
    return value


def load_capture_configuration(
    environment: Mapping[str, str],
) -> OfficialCaptureConfiguration:
    krx_api_key = _required(environment, "FINANCIAL_AGENT_KRX_API_KEY")
    ecos_api_key = _required(environment, "FINANCIAL_AGENT_ECOS_API_KEY")
    sec_user_agent = _required(
        environment, "FINANCIAL_AGENT_SEC_USER_AGENT"
    )
    if "@" not in sec_user_agent or len(sec_user_agent.split()) < 2:
        raise OfficialCaptureConfigurationError() from None
    return OfficialCaptureConfiguration(
        krx_api_key=krx_api_key,
        ecos_api_key=ecos_api_key,
        sec_user_agent=sec_user_agent,
        holdings_root=Path(
            _required(environment, "FINANCIAL_AGENT_KRX_HOLDINGS_ROOT")
        ),
        output_root=Path(
            _required(environment, "FINANCIAL_AGENT_OFFICIAL_OUTPUT_ROOT")
        ),
    )


def _error(code: str, message: str) -> SourceVerificationError:
    return SourceVerificationError(code, message)


def _object_key(spec: OfficialCaptureSpec, object_name: str) -> str:
    return "/".join(
        (
            "external",
            spec.cutoff_date.isoformat(),
            spec.source_code,
            spec.snapshot_id,
            object_name,
        )
    )


def _request(
    spec: OfficialCaptureSpec,
    configuration: OfficialCaptureConfiguration,
) -> Request:
    if spec.endpoint is None:
        raise _error(
            "OFFICIAL_CAPTURE_PLAN_INVALID",
            "official capture request endpoint is missing",
        ) from None
    headers = {"Accept": spec.media_type}
    if spec.access_kind == "krx_api":
        assert spec.applicable_date is not None
        date_text = spec.applicable_date.strftime("%Y%m%d")
        url = f"{spec.endpoint}?{urlencode({'basDd': date_text})}"
        headers["AUTH_KEY"] = configuration.krx_api_key
    elif spec.access_kind == "ecos_api":
        assert spec.applicable_date is not None
        date_text = spec.applicable_date.strftime("%Y%m%d")
        key = quote(configuration.ecos_api_key, safe="")
        url = (
            f"{spec.endpoint}/{key}/json/kr/1/100/731Y001/D/"
            f"{date_text}/{date_text}"
        )
    elif spec.access_kind == "sec_file":
        url = spec.endpoint
        headers["User-Agent"] = configuration.sec_user_agent
        headers["Accept-Encoding"] = "identity"
    else:
        raise _error(
            "OFFICIAL_CAPTURE_PLAN_INVALID",
            "official capture request kind is invalid",
        ) from None
    return Request(url, headers=headers, method="GET")


def _manifest(
    spec: OfficialCaptureSpec,
    *,
    objects: tuple[OfficialObjectManifest, ...],
    snapshot_id: str | None = None,
) -> OfficialSnapshotManifest:
    return OfficialSnapshotManifest(
        source_code=spec.source_code,
        snapshot_id=snapshot_id or spec.snapshot_id,
        publisher_code=spec.publisher_code,
        cutoff_date=spec.cutoff_date,
        applicable_date=spec.applicable_date,
        published_at=spec.published_at,
        available_at=spec.available_at,
        vintage_date=spec.vintage_date,
        parser_version="1",
        mapping_version="1",
        objects=objects,
    )


def _write_manifest(
    manifest: OfficialSnapshotManifest,
    manifest_root: Path,
) -> None:
    write_canonical_manifest(
        manifest,
        manifest_root / manifest.source_code / f"{manifest.snapshot_id}.json",
    )


def _capture_http_sources(
    configuration: OfficialCaptureConfiguration,
    *,
    opener: _Opener,
    object_root: Path,
    manifest_root: Path,
) -> tuple[int, int]:
    object_count = 0
    manifest_count = 0
    for spec in APPROVED_CAPTURE_SPECS:
        if spec.access_kind == "local_directory":
            continue
        assert spec.object_name is not None
        object_key = _object_key(spec, spec.object_name)
        captured = capture_http_object(
            opener,
            request=_request(spec, configuration),
            destination=object_root / object_key,
            object_name=spec.object_name,
            object_key=object_key,
            expected_media_type=spec.media_type,
            maximum_bytes=spec.maximum_bytes,
        )
        _write_manifest(_manifest(spec, objects=(captured,)), manifest_root)
        object_count += 1
        manifest_count += 1
    return object_count, manifest_count


def _capture_holdings(
    holdings_root: Path,
    *,
    object_root: Path,
    manifest_root: Path,
) -> tuple[int, int]:
    spec = next(
        item
        for item in APPROVED_CAPTURE_SPECS
        if item.source_code == "KRX_ETF_PDF"
    )
    try:
        if not holdings_root.is_dir():
            raise OSError
        paths = tuple(sorted(holdings_root.glob("*.csv")))
        if not paths:
            raise OSError
    except OSError:
        raise _error(
            "OFFICIAL_LOCAL_SOURCE_INVALID",
            "official local source directory is unavailable",
        ) from None

    for path in paths:
        if re.fullmatch(
            rf"[A-Z0-9]{{6}}_{_DOMESTIC_MARKET_DATE_TEXT}\.csv", path.name
        ) is None:
            raise _error(
                "OFFICIAL_LOCAL_SOURCE_INVALID",
                "official local source name is invalid",
            ) from None
        try:
            size_bytes = path.stat().st_size
        except OSError:
            raise _error(
                "OFFICIAL_LOCAL_SOURCE_INVALID",
                "official local source is unreadable",
            ) from None
        if size_bytes <= 0 or size_bytes > spec.maximum_bytes:
            raise _error(
                "OFFICIAL_LOCAL_SOURCE_INVALID",
                "official local source size is invalid",
            ) from None

        short_code = path.name[:6]
        snapshot_id = (
            f"krx-etf-pdf-{short_code}-{_DOMESTIC_MARKET_DATE_TEXT}"
        )
        object_key = "/".join(
            (
                "external",
                spec.cutoff_date.isoformat(),
                spec.source_code,
                snapshot_id,
                path.name,
            )
        )
        destination = object_root / object_key
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            digest = sha256_path(destination)
        except OSError:
            raise _error(
                "OFFICIAL_LOCAL_SOURCE_INVALID",
                "official local source could not be copied",
            ) from None
        captured = OfficialObjectManifest(
            object_name=path.name,
            object_key=object_key,
            media_type=spec.media_type,
            size_bytes=size_bytes,
            sha256=digest,
        )
        _write_manifest(
            _manifest(spec, objects=(captured,), snapshot_id=snapshot_id),
            manifest_root,
        )
    return len(paths), len(paths)


def capture_local_krx_holdings(
    *,
    holdings_root: Path,
    output_root: Path,
) -> OfficialCaptureResult:
    if output_root.exists():
        raise _error(
            "OFFICIAL_CAPTURE_TARGET_EXISTS",
            "official capture target already exists",
        ) from None
    try:
        output_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".financial-agent-krx-holdings-capture-",
            dir=output_root.parent,
        ) as temporary:
            staging_root = Path(temporary) / "capture"
            object_root = staging_root / "objects"
            manifest_root = staging_root / "manifests"
            object_count, manifest_count = _capture_holdings(
                holdings_root,
                object_root=object_root,
                manifest_root=manifest_root,
            )
            total_bytes = sum(
                path.stat().st_size
                for path in object_root.rglob("*")
                if path.is_file()
            )
            staging_root.replace(output_root)
    except SourceVerificationError:
        raise
    except Exception:
        raise _error(
            "OFFICIAL_CAPTURE_FAILED",
            "official source capture failed",
        ) from None

    return OfficialCaptureResult(
        output_root=output_root,
        object_root=output_root / "objects",
        manifest_root=output_root / "manifests",
        source_count=1,
        object_count=object_count,
        manifest_count=manifest_count,
        total_bytes=total_bytes,
        eligible_start=_DOMESTIC_MARKET_DATE.isoformat(),
        eligible_end=_CUTOFF_DATE.isoformat(),
    )


def reapprove_existing_sec_capture(
    *,
    source_root: Path,
    output_root: Path,
) -> OfficialCaptureResult:
    """Copy only the two reviewed SEC objects under the current cutoff."""
    from financial_agent.ingestion.official_pipeline import (
        load_official_manifests,
        verify_official_snapshot_objects,
    )

    if output_root.exists():
        raise _error(
            "OFFICIAL_CAPTURE_TARGET_EXISTS",
            "official capture target already exists",
        ) from None
    sec_specs = {
        spec.source_code: spec
        for spec in APPROVED_CAPTURE_SPECS
        if spec.source_code
        in {"SEC_SERIES_CLASS_20260601", "SEC_NPORT_2026Q2"}
    }
    manifests = tuple(
        manifest
        for manifest in load_official_manifests(source_root / "manifests")
        if manifest.source_code in sec_specs
    )
    if len(manifests) != len(sec_specs) or {
        manifest.source_code for manifest in manifests
    } != set(sec_specs):
        raise _error(
            "OFFICIAL_REAPPROVAL_INVALID",
            "reviewed SEC source inventory is incomplete",
        ) from None
    verified = verify_official_snapshot_objects(
        manifests,
        source_root / "objects",
    )

    approved: list[tuple[OfficialSnapshotManifest, Path]] = []
    for manifest in manifests:
        spec = sec_specs[manifest.source_code]
        if (
            manifest.snapshot_id != spec.snapshot_id
            or manifest.publisher_code != spec.publisher_code
            or manifest.cutoff_date > spec.cutoff_date
            or manifest.applicable_date != spec.applicable_date
            or manifest.published_at != spec.published_at
            or manifest.available_at != spec.available_at
            or manifest.vintage_date != spec.vintage_date
            or manifest.parser_version != "1"
            or manifest.mapping_version != "1"
            or len(manifest.objects) != 1
        ):
            raise _error(
                "OFFICIAL_REAPPROVAL_INVALID",
                "reviewed SEC source metadata differs from the approved plan",
            ) from None
        item = manifest.objects[0]
        if (
            spec.object_name is None
            or item.object_name != spec.object_name
            or item.media_type != spec.media_type
            or (item.size_bytes, item.sha256)
            != _REAPPROVED_SEC_OBJECTS[manifest.source_code]
        ):
            raise _error(
                "OFFICIAL_REAPPROVAL_INVALID",
                "reviewed SEC object differs from the approved plan",
            ) from None
        approved.append(
            (
                manifest,
                verified[(manifest.snapshot_id, item.object_key)],
            )
        )

    try:
        output_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".financial-agent-sec-reapproval-",
            dir=output_root.parent,
        ) as temporary:
            staging_root = Path(temporary) / "capture"
            object_root = staging_root / "objects"
            manifest_root = staging_root / "manifests"
            for old_manifest, source_path in approved:
                spec = sec_specs[old_manifest.source_code]
                assert spec.object_name is not None
                object_key = _object_key(spec, spec.object_name)
                destination = object_root / object_key
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_path, destination)
                old_item = old_manifest.objects[0]
                copied = OfficialObjectManifest(
                    object_name=spec.object_name,
                    object_key=object_key,
                    media_type=spec.media_type,
                    size_bytes=destination.stat().st_size,
                    sha256=sha256_path(destination),
                )
                if (
                    copied.size_bytes != old_item.size_bytes
                    or copied.sha256 != old_item.sha256
                ):
                    raise _error(
                        "OFFICIAL_REAPPROVAL_INVALID",
                        "reviewed SEC object changed while being copied",
                    ) from None
                _write_manifest(_manifest(spec, objects=(copied,)), manifest_root)
            total_bytes = sum(
                path.stat().st_size
                for path in object_root.rglob("*")
                if path.is_file()
            )
            staging_root.replace(output_root)
    except SourceVerificationError:
        raise
    except Exception:
        raise _error(
            "OFFICIAL_CAPTURE_FAILED",
            "official source capture failed",
        ) from None

    return OfficialCaptureResult(
        output_root=output_root,
        object_root=output_root / "objects",
        manifest_root=output_root / "manifests",
        source_count=2,
        object_count=2,
        manifest_count=2,
        total_bytes=total_bytes,
        eligible_start="2026-06-01",
        eligible_end=_CUTOFF_DATE.isoformat(),
    )


def capture_approved_official_sources(
    configuration: OfficialCaptureConfiguration,
    *,
    opener: _Opener | None = None,
) -> OfficialCaptureResult:
    output_root = configuration.output_root
    if output_root.exists():
        raise _error(
            "OFFICIAL_CAPTURE_TARGET_EXISTS",
            "official capture target already exists",
        ) from None
    try:
        output_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".financial-agent-official-capture-",
            dir=output_root.parent,
        ) as temporary:
            staging_root = Path(temporary) / "capture"
            object_root = staging_root / "objects"
            manifest_root = staging_root / "manifests"
            active_opener = opener if opener is not None else build_opener()
            http_counts = _capture_http_sources(
                configuration,
                opener=active_opener,
                object_root=object_root,
                manifest_root=manifest_root,
            )
            holding_counts = _capture_holdings(
                configuration.holdings_root,
                object_root=object_root,
                manifest_root=manifest_root,
            )
            total_bytes = sum(
                path.stat().st_size
                for path in object_root.rglob("*")
                if path.is_file()
            )
            staging_root.replace(output_root)
    except SourceVerificationError:
        raise
    except Exception:
        raise _error(
            "OFFICIAL_CAPTURE_FAILED",
            "official source capture failed",
        ) from None

    return OfficialCaptureResult(
        output_root=output_root,
        object_root=output_root / "objects",
        manifest_root=output_root / "manifests",
        source_count=len(APPROVED_CAPTURE_SPECS),
        object_count=http_counts[0] + holding_counts[0],
        manifest_count=http_counts[1] + holding_counts[1],
        total_bytes=total_bytes,
        eligible_start="2026-06-01",
        eligible_end=_CUTOFF_DATE.isoformat(),
    )


def publish_official_capture(
    capture: OfficialCaptureResult,
    *,
    client: object,
    bucket: str,
) -> int:
    from financial_agent.ingestion.official_pipeline import (
        load_official_manifests,
    )

    manifests = load_official_manifests(capture.manifest_root)
    published = 0
    for manifest in manifests:
        for item in manifest.objects:
            upload_verified_object(
                client,
                bucket=bucket,
                key=item.object_key,
                source=capture.object_root / item.object_key,
                expected_sha256=item.sha256,
            )
            published += 1
        manifest_path = (
            capture.manifest_root
            / manifest.source_code
            / f"{manifest.snapshot_id}.json"
        )
        manifest_key = "/".join(
            (
                "external",
                manifest.cutoff_date.isoformat(),
                manifest.source_code,
                manifest.snapshot_id,
                "manifest.json",
            )
        )
        upload_verified_object(
            client,
            bucket=bucket,
            key=manifest_key,
            source=manifest_path,
            expected_sha256=sha256_path(manifest_path),
        )
        published += 1
    return published


def load_existing_capture(output_root: Path) -> OfficialCaptureResult:
    from financial_agent.ingestion.official_pipeline import (
        OfficialPipelineError,
        load_official_manifests,
        verify_official_snapshot_objects,
    )

    object_root = output_root / "objects"
    manifest_root = output_root / "manifests"
    manifests = load_official_manifests(manifest_root)
    if not manifests:
        raise OfficialPipelineError("OFFICIAL_MANIFEST_INVALID") from None
    verify_official_snapshot_objects(manifests, object_root)
    dates = tuple(
        value
        for manifest in manifests
        for value in (
            manifest.applicable_date,
            manifest.published_at.date()
            if manifest.published_at is not None
            else None,
            manifest.available_at.date()
            if manifest.available_at is not None
            else None,
        )
        if value is not None
    )
    return OfficialCaptureResult(
        output_root=output_root,
        object_root=object_root,
        manifest_root=manifest_root,
        source_count=len({manifest.source_code for manifest in manifests}),
        object_count=sum(len(manifest.objects) for manifest in manifests),
        manifest_count=len(manifests),
        total_bytes=sum(
            item.size_bytes
            for manifest in manifests
            for item in manifest.objects
        ),
        eligible_start=min(dates).isoformat(),
        eligible_end=max(dates).isoformat(),
    )
