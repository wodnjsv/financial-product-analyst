from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from financial_agent.ingestion.official.models import (
    OfficialObjectManifest,
    OfficialSnapshotManifest,
)
from financial_agent.ingestion.official.snapshot import (
    capture_http_object,
    validate_official_snapshot,
    write_canonical_manifest,
)
from financial_agent.ingestion.sources import (
    SourceVerificationError,
    upload_verified_object,
)


CUTOFF = date(2026, 8, 24)
PAYLOAD = b'{"OutBlock_1":[{"BAS_DD":"20260710"}]}'
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


def _object(
    *,
    object_name: str = "krx-etf-daily.json",
    object_key: str = "external/2026-07-11/KRX_ETF_DAILY/snapshot/data.json",
    size_bytes: int = len(PAYLOAD),
    sha256: str = PAYLOAD_SHA256,
) -> OfficialObjectManifest:
    return OfficialObjectManifest(
        object_name=object_name,
        object_key=object_key,
        media_type="application/json",
        size_bytes=size_bytes,
        sha256=sha256,
    )


def _snapshot(
    *,
    objects: tuple[OfficialObjectManifest, ...] | None = None,
    applicable_date: date | None = date(2026, 7, 10),
    published_at: datetime | None = None,
    available_at: datetime | None = datetime(
        2026, 7, 10, 23, 59, 59, tzinfo=timezone.utc
    ),
    vintage_date: date | None = date(2026, 7, 10),
) -> OfficialSnapshotManifest:
    return OfficialSnapshotManifest(
        source_code="KRX_ETF_DAILY",
        snapshot_id="krx-etf-daily-20260710",
        publisher_code="KRX",
        cutoff_date=CUTOFF,
        applicable_date=applicable_date,
        published_at=published_at,
        available_at=available_at,
        vintage_date=vintage_date,
        parser_version="1",
        mapping_version="1",
        objects=objects if objects is not None else (_object(),),
    )


class FakeResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        content_type: str = "application/json; charset=utf-8",
        content_length: int | None = None,
    ) -> None:
        self._payload = payload
        self._offset = 0
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FakeOpener:
    def __init__(
        self, response: FakeResponse | None = None, *, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error

    def open(self, request: object) -> FakeResponse:
        del request
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class FakeUploadClient:
    def __init__(self, *, downloaded_payload: bytes | None = None) -> None:
        self.uploaded_payload: bytes | None = None
        self.downloaded_payload = downloaded_payload

    def upload_file(self, source: str, bucket: str, key: str) -> None:
        del bucket, key
        self.uploaded_payload = Path(source).read_bytes()

    def download_file(self, bucket: str, key: str, destination: str) -> None:
        del bucket, key
        payload = (
            self.downloaded_payload
            if self.downloaded_payload is not None
            else self.uploaded_payload
        )
        assert payload is not None
        Path(destination).write_bytes(payload)


def test_manifest_is_canonical_across_input_object_order(tmp_path: Path) -> None:
    first = _object(
        object_name="b.json",
        object_key="external/2026-07-11/KRX_ETF_DAILY/snapshot/b.json",
    )
    second = _object(
        object_name="a.json",
        object_key="external/2026-07-11/KRX_ETF_DAILY/snapshot/a.json",
    )
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"

    left_hash = write_canonical_manifest(
        _snapshot(objects=(first, second)), left
    )
    right_hash = write_canonical_manifest(
        _snapshot(objects=(second, first)), right
    )

    assert left.read_bytes() == right.read_bytes()
    assert left_hash == right_hash == hashlib.sha256(left.read_bytes()).hexdigest()
    assert left.read_text("utf-8").index("a.json") < left.read_text("utf-8").index(
        "b.json"
    )


@pytest.mark.parametrize(
    ("manifest", "expected_code"),
    [
        (
            _snapshot(objects=(_object(), _object(object_name="duplicate.json"))),
            "OFFICIAL_OBJECT_KEY_DUPLICATE",
        ),
        (_snapshot(objects=(_object(sha256="not-a-sha256"),)), "OFFICIAL_SHA256_INVALID"),
        (_snapshot(objects=(_object(size_bytes=0),)), "OFFICIAL_OBJECT_EMPTY"),
        (
            _snapshot(applicable_date=date(2026, 8, 25)),
            "OFFICIAL_CUTOFF_VIOLATION",
        ),
        (
            _snapshot(
                published_at=datetime(2026, 8, 25, tzinfo=timezone.utc)
            ),
            "OFFICIAL_CUTOFF_VIOLATION",
        ),
        (
            _snapshot(
                available_at=datetime(2026, 8, 25, tzinfo=timezone.utc)
            ),
            "OFFICIAL_CUTOFF_VIOLATION",
        ),
        (
            _snapshot(vintage_date=date(2026, 8, 25)),
            "OFFICIAL_CUTOFF_VIOLATION",
        ),
        (
            _snapshot(available_at=None),
            "OFFICIAL_AVAILABILITY_MISSING",
        ),
        (
            _snapshot(objects=()),
            "OFFICIAL_OBJECTS_MISSING",
        ),
        (
            _snapshot(
                objects=(
                    _object(
                        object_key=(
                            "https://example.invalid/data.json?token=SYNTHETIC-SECRET"
                        )
                    ),
                )
            ),
            "OFFICIAL_OBJECT_KEY_INVALID",
        ),
        (
            _snapshot(available_at=datetime(2026, 7, 10, 23, 59, 59)),
            "OFFICIAL_DATETIME_INVALID",
        ),
    ],
)
def test_snapshot_validation_rejects_invalid_manifest(
    manifest: OfficialSnapshotManifest, expected_code: str
) -> None:
    with pytest.raises(SourceVerificationError) as captured:
        validate_official_snapshot(manifest)

    assert captured.value.code == expected_code
    assert captured.value.__cause__ is None


def test_snapshot_cutoff_uses_end_of_day_in_asia_seoul() -> None:
    one_second_before = datetime(
        2026, 8, 24, 23, 59, 59, tzinfo=timezone(timedelta(hours=9))
    )
    one_second_after_in_utc = datetime(
        2026, 8, 24, 15, 0, 0, tzinfo=timezone.utc
    )

    validate_official_snapshot(_snapshot(available_at=one_second_before))
    with pytest.raises(SourceVerificationError) as captured:
        validate_official_snapshot(
            _snapshot(available_at=one_second_after_in_utc)
        )

    assert captured.value.code == "OFFICIAL_CUTOFF_VIOLATION"


def test_invalid_manifest_is_not_published(tmp_path: Path) -> None:
    destination = tmp_path / "manifest.json"

    with pytest.raises(SourceVerificationError):
        write_canonical_manifest(_snapshot(available_at=None), destination)

    assert not destination.exists()


def test_http_capture_streams_and_hashes_exact_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "data.json"

    captured = capture_http_object(
        FakeOpener(FakeResponse(PAYLOAD, content_length=len(PAYLOAD))),
        request=object(),
        destination=destination,
        object_name="data.json",
        object_key="external/2026-07-11/KRX_ETF_DAILY/snapshot/data.json",
        expected_media_type="application/json",
        maximum_bytes=len(PAYLOAD),
    )

    assert destination.read_bytes() == PAYLOAD
    assert captured == _object(object_name="data.json")


@pytest.mark.parametrize(
    ("response", "maximum_bytes", "expected_code"),
    [
        (
            FakeResponse(PAYLOAD, content_length=len(PAYLOAD) + 1),
            len(PAYLOAD),
            "OFFICIAL_OBJECT_TOO_LARGE",
        ),
        (
            FakeResponse(PAYLOAD + b"x"),
            len(PAYLOAD),
            "OFFICIAL_OBJECT_TOO_LARGE",
        ),
        (
            FakeResponse(PAYLOAD, content_length=len(PAYLOAD) + 1),
            len(PAYLOAD) + 1,
            "OFFICIAL_OBJECT_TRUNCATED",
        ),
        (
            FakeResponse(PAYLOAD, content_type="text/html"),
            len(PAYLOAD),
            "OFFICIAL_MEDIA_TYPE_MISMATCH",
        ),
        (
            FakeResponse(b"", content_length=0),
            len(PAYLOAD),
            "OFFICIAL_OBJECT_EMPTY",
        ),
    ],
)
def test_http_capture_rejects_invalid_response_without_replacing_destination(
    tmp_path: Path,
    response: FakeResponse,
    maximum_bytes: int,
    expected_code: str,
) -> None:
    destination = tmp_path / "data.json"
    destination.write_bytes(b"previous verified bytes")

    with pytest.raises(SourceVerificationError) as captured:
        capture_http_object(
            FakeOpener(response),
            request=object(),
            destination=destination,
            object_name="data.json",
            object_key="external/2026-07-11/KRX_ETF_DAILY/snapshot/data.json",
            expected_media_type="application/json",
            maximum_bytes=maximum_bytes,
        )

    assert captured.value.code == expected_code
    assert destination.read_bytes() == b"previous verified bytes"


def test_http_capture_sanitizes_transport_failure(tmp_path: Path) -> None:
    secret = "SYNTHETIC-SECRET-DO-NOT-RETAIN"

    with pytest.raises(SourceVerificationError) as captured:
        capture_http_object(
            FakeOpener(error=RuntimeError(f"https://example.invalid/?token={secret}")),
            request={"Authorization": secret},
            destination=tmp_path / "data.json",
            object_name="data.json",
            object_key="external/2026-07-11/KRX_ETF_DAILY/snapshot/data.json",
            expected_media_type="application/json",
            maximum_bytes=len(PAYLOAD),
        )

    assert captured.value.code == "OFFICIAL_CAPTURE_FAILED"
    assert secret not in str(captured.value)
    assert secret not in repr(captured.value)
    assert captured.value.__cause__ is None


def test_object_upload_rehashes_downloaded_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(PAYLOAD)
    client = FakeUploadClient()

    assert (
        upload_verified_object(
            client,
            bucket="private-bucket",
            key="external/2026-07-11/KRX_ETF_DAILY/snapshot/data.json",
            source=source,
            expected_sha256=PAYLOAD_SHA256,
        )
        == PAYLOAD_SHA256
    )
    assert client.uploaded_payload == PAYLOAD


@pytest.mark.parametrize(
    ("source_payload", "downloaded_payload", "expected_sha256", "expected_code"),
    [
        (
            PAYLOAD,
            None,
            "0" * 64,
            "OBJECT_UPLOAD_SOURCE_CHECKSUM_MISMATCH",
        ),
        (
            PAYLOAD,
            b"corrupted remote bytes",
            PAYLOAD_SHA256,
            "OBJECT_UPLOAD_VERIFICATION_FAILED",
        ),
    ],
)
def test_object_upload_fails_closed_on_checksum_mismatch(
    tmp_path: Path,
    source_payload: bytes,
    downloaded_payload: bytes | None,
    expected_sha256: str,
    expected_code: str,
) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(source_payload)
    client = FakeUploadClient(downloaded_payload=downloaded_payload)

    with pytest.raises(SourceVerificationError) as captured:
        upload_verified_object(
            client,
            bucket="private-bucket",
            key="external/2026-07-11/KRX_ETF_DAILY/snapshot/data.json",
            source=source,
            expected_sha256=expected_sha256,
        )

    assert captured.value.code == expected_code
    assert captured.value.__cause__ is None
