from __future__ import annotations

import hashlib
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from financial_agent.ingestion.official.capture import (
    OfficialCaptureResult,
    load_existing_capture,
    publish_official_capture,
)
from financial_agent.ingestion.official.models import (
    OfficialObjectManifest,
    OfficialSnapshotManifest,
)
from financial_agent.ingestion.official.snapshot import write_canonical_manifest


RUN_OFFICIAL_OBJECT_CHECK = (
    os.getenv("RUN_OFFICIAL_DATA_TESTS") == "1"
    and os.getenv("RUN_NCP_OBJECT_STORAGE_TESTS") == "1"
)
OBJECT_ENVIRONMENT = (
    "FINANCIAL_AGENT_OFFICIAL_OUTPUT_ROOT",
    "FINANCIAL_AGENT_OBJECT_STORAGE_ENDPOINT",
    "FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET",
    "FINANCIAL_AGENT_OBJECT_STORAGE_ACCESS_KEY_ID",
    "FINANCIAL_AGENT_OBJECT_STORAGE_SECRET_ACCESS_KEY",
)


@pytest.fixture(scope="session", autouse=True)
def _require_explicit_object_configuration() -> None:
    if RUN_OFFICIAL_OBJECT_CHECK and not all(
        os.getenv(name) for name in OBJECT_ENVIRONMENT
    ):
        pytest.fail("OFFICIAL_OBJECT_STORAGE_CONFIGURATION_MISSING", pytrace=False)


class _ObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_file(self, source: str, bucket: str, key: str) -> None:
        del bucket
        self.objects[key] = Path(source).read_bytes()

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        del bucket
        Path(destination).write_bytes(self.objects[key])


def _capture(tmp_path: Path) -> OfficialCaptureResult:
    output_root = tmp_path / "capture"
    object_root = output_root / "objects"
    manifest_root = output_root / "manifests"
    payload = b'{"OutBlock_1":[{"BAS_DD":"20260710"}]}'
    object_key = (
        "external/2026-07-11/KRX_ETF_DAILY/"
        "krx-etf-daily-20260710/data.json"
    )
    object_path = object_root / object_key
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(payload)
    manifest = OfficialSnapshotManifest(
        source_code="KRX_ETF_DAILY",
        snapshot_id="krx-etf-daily-20260710",
        publisher_code="KRX",
        cutoff_date=date(2026, 7, 11),
        applicable_date=date(2026, 7, 10),
        published_at=None,
        available_at=datetime(2026, 7, 10, 23, 59, 59, tzinfo=UTC),
        vintage_date=None,
        parser_version="1",
        mapping_version="1",
        objects=(
            OfficialObjectManifest(
                object_name="data.json",
                object_key=object_key,
                media_type="application/json",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            ),
        ),
    )
    write_canonical_manifest(
        manifest,
        manifest_root / manifest.source_code / f"{manifest.snapshot_id}.json",
    )
    return OfficialCaptureResult(
        output_root=output_root,
        object_root=object_root,
        manifest_root=manifest_root,
        source_count=1,
        object_count=1,
        manifest_count=1,
        total_bytes=len(payload),
        eligible_start="2026-07-10",
        eligible_end="2026-07-10",
    )


def test_publish_uploads_and_reverifies_objects_and_canonical_manifests(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)
    client = _ObjectStorage()

    published = publish_official_capture(
        capture,
        client=client,
        bucket="synthetic-private-bucket",
    )

    assert published == 2
    assert set(client.objects) == {
        (
            "external/2026-07-11/KRX_ETF_DAILY/"
            "krx-etf-daily-20260710/data.json"
        ),
        (
            "external/2026-07-11/KRX_ETF_DAILY/"
            "krx-etf-daily-20260710/manifest.json"
        ),
    }


def test_existing_capture_is_reloaded_only_after_every_hash_is_verified(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path)

    reloaded = load_existing_capture(capture.output_root)

    assert reloaded.object_count == 1
    assert reloaded.manifest_count == 1
    assert reloaded.total_bytes == capture.total_bytes

    object_path = next(
        path for path in capture.object_root.rglob("*") if path.is_file()
    )
    object_path.write_bytes(b"tampered")
    with pytest.raises(Exception) as captured_error:
        load_existing_capture(capture.output_root)
    assert getattr(captured_error.value, "code", None) == (
        "OFFICIAL_OBJECT_SIZE_MISMATCH"
    )


@pytest.mark.official_data
@pytest.mark.object_storage
@pytest.mark.ncp_integration
@pytest.mark.skipif(
    not RUN_OFFICIAL_OBJECT_CHECK,
    reason="explicit official Object Storage gate is disabled",
)
def test_live_official_capture_round_trips_through_private_object_storage() -> None:
    from financial_agent.ingestion.cli import _object_storage_client

    capture = load_existing_capture(
        Path(os.environ["FINANCIAL_AGENT_OFFICIAL_OUTPUT_ROOT"])
    )
    published = publish_official_capture(
        capture,
        client=_object_storage_client(),
        bucket=os.environ["FINANCIAL_AGENT_OBJECT_STORAGE_BUCKET"],
    )

    assert published == capture.object_count + capture.manifest_count
