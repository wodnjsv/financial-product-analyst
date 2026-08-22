from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


CoverageStatus = Literal[
    "COVERED", "PARTIALLY_COVERED", "NOT_COVERED", "CONFLICT"
]


@dataclass(frozen=True, slots=True)
class OfficialObjectManifest:
    object_name: str
    object_key: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OfficialSnapshotManifest:
    source_code: str
    snapshot_id: str
    publisher_code: str
    cutoff_date: date
    applicable_date: date | None
    published_at: datetime | None
    available_at: datetime | None
    vintage_date: date | None
    parser_version: str
    mapping_version: str
    objects: tuple[OfficialObjectManifest, ...]
