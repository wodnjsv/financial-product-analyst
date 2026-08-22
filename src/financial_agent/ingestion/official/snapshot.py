from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from financial_agent.ingestion.sources import SourceVerificationError

from .models import OfficialObjectManifest, OfficialSnapshotManifest


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_STREAM_CHUNK_BYTES = 1024 * 1024


class _Response(Protocol):
    headers: object

    def __enter__(self) -> "_Response": ...

    def __exit__(self, *args: object) -> object: ...

    def read(self, size: int) -> bytes: ...


class _Opener(Protocol):
    def open(self, request: object) -> _Response: ...


def _error(code: str, message: str) -> SourceVerificationError:
    return SourceVerificationError(code, message)


def _datetime_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _manifest_mapping(manifest: OfficialSnapshotManifest) -> dict[str, object]:
    objects = sorted(
        manifest.objects, key=lambda item: (item.object_key, item.object_name)
    )
    return {
        "applicable_date": (
            manifest.applicable_date.isoformat()
            if manifest.applicable_date is not None
            else None
        ),
        "available_at": _datetime_text(manifest.available_at),
        "cutoff_date": manifest.cutoff_date.isoformat(),
        "mapping_version": manifest.mapping_version,
        "objects": [
            {
                "media_type": item.media_type,
                "object_key": item.object_key,
                "object_name": item.object_name,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in objects
        ],
        "parser_version": manifest.parser_version,
        "published_at": _datetime_text(manifest.published_at),
        "publisher_code": manifest.publisher_code,
        "snapshot_id": manifest.snapshot_id,
        "source_code": manifest.source_code,
        "vintage_date": (
            manifest.vintage_date.isoformat()
            if manifest.vintage_date is not None
            else None
        ),
    }


def _canonical_manifest_bytes(manifest: OfficialSnapshotManifest) -> bytes:
    return json.dumps(
        _manifest_mapping(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def validate_official_snapshot(manifest: OfficialSnapshotManifest) -> str:
    if manifest.available_at is None:
        raise _error(
            "OFFICIAL_AVAILABILITY_MISSING",
            "official snapshot availability is missing",
        ) from None

    timestamps = (manifest.published_at, manifest.available_at)
    if any(
        value is not None
        and (value.tzinfo is None or value.utcoffset() is None)
        for value in timestamps
    ):
        raise _error(
            "OFFICIAL_DATETIME_INVALID",
            "official snapshot timestamp must include a timezone",
        ) from None

    if not manifest.objects:
        raise _error(
            "OFFICIAL_OBJECTS_MISSING",
            "official snapshot contains no objects",
        ) from None

    dates = (
        manifest.applicable_date,
        manifest.published_at.date() if manifest.published_at is not None else None,
        manifest.available_at.date(),
        manifest.vintage_date,
    )
    if any(value is not None and value > manifest.cutoff_date for value in dates):
        raise _error(
            "OFFICIAL_CUTOFF_VIOLATION",
            "official snapshot date exceeds the approved cutoff",
        ) from None

    object_keys: set[str] = set()
    for item in manifest.objects:
        key_parts = item.object_key.split("/")
        if (
            not item.object_key
            or item.object_key.startswith("/")
            or "://" in item.object_key
            or "?" in item.object_key
            or "#" in item.object_key
            or "@" in item.object_key
            or "\\" in item.object_key
            or ".." in key_parts
        ):
            raise _error(
                "OFFICIAL_OBJECT_KEY_INVALID",
                "official snapshot object key is invalid",
            ) from None
        if item.object_key in object_keys:
            raise _error(
                "OFFICIAL_OBJECT_KEY_DUPLICATE",
                "official snapshot contains a duplicate object key",
            ) from None
        object_keys.add(item.object_key)
        if item.size_bytes <= 0:
            raise _error(
                "OFFICIAL_OBJECT_EMPTY",
                "official snapshot object is empty",
            ) from None
        if _SHA256_PATTERN.fullmatch(item.sha256) is None:
            raise _error(
                "OFFICIAL_SHA256_INVALID",
                "official snapshot checksum is invalid",
            ) from None

    payload = _canonical_manifest_bytes(manifest)
    return hashlib.sha256(payload).hexdigest()


def write_canonical_manifest(
    manifest: OfficialSnapshotManifest, destination: Path
) -> str:
    manifest_hash = validate_official_snapshot(manifest)
    payload = _canonical_manifest_bytes(manifest)
    temporary_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".official-manifest-",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(destination)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise _error(
            "OFFICIAL_MANIFEST_WRITE_FAILED",
            "official snapshot manifest could not be written",
        ) from None
    return manifest_hash


def _header(response: _Response, name: str) -> str | None:
    headers = response.headers
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    return value if isinstance(value, str) else None


def capture_http_object(
    opener: _Opener,
    *,
    request: object,
    destination: Path,
    object_name: str,
    object_key: str,
    expected_media_type: str,
    maximum_bytes: int,
) -> OfficialObjectManifest:
    temporary_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with opener.open(request) as response:
            content_type = (_header(response, "Content-Type") or "").split(
                ";", 1
            )[0].strip().lower()
            if content_type != expected_media_type.lower():
                raise _error(
                    "OFFICIAL_MEDIA_TYPE_MISMATCH",
                    "official response media type differs from expected",
                )

            content_length_text = _header(response, "Content-Length")
            content_length = (
                int(content_length_text)
                if content_length_text is not None
                else None
            )
            if content_length == 0:
                raise _error(
                    "OFFICIAL_OBJECT_EMPTY", "official response is empty"
                )
            if content_length is not None and content_length > maximum_bytes:
                raise _error(
                    "OFFICIAL_OBJECT_TOO_LARGE",
                    "official response exceeds the byte limit",
                )

            digest = hashlib.sha256()
            size_bytes = 0
            with tempfile.NamedTemporaryFile(
                prefix=".official-object-",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := response.read(_STREAM_CHUNK_BYTES):
                    size_bytes += len(chunk)
                    if size_bytes > maximum_bytes:
                        raise _error(
                            "OFFICIAL_OBJECT_TOO_LARGE",
                            "official response exceeds the byte limit",
                        )
                    digest.update(chunk)
                    temporary.write(chunk)
                if size_bytes == 0:
                    raise _error(
                        "OFFICIAL_OBJECT_EMPTY", "official response is empty"
                    )
                if content_length is not None and size_bytes != content_length:
                    raise _error(
                        "OFFICIAL_OBJECT_TRUNCATED",
                        "official response length differs from declared length",
                    )
                temporary.flush()
                os.fsync(temporary.fileno())
        temporary_path.replace(destination)
        return OfficialObjectManifest(
            object_name=object_name,
            object_key=object_key,
            media_type=expected_media_type,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )
    except SourceVerificationError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise _error(
            "OFFICIAL_CAPTURE_FAILED", "official object capture failed"
        ) from None
