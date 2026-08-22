from __future__ import annotations

import hashlib
import csv
import io
import json
from datetime import date, datetime, timezone

from financial_agent.ingestion.official.models import (
    OfficialObjectManifest,
    OfficialSnapshotManifest,
)


def official_manifest(
    *,
    source_code: str,
    object_name: str,
    payload: bytes,
    applicable_date: date,
    published_at: datetime | None = None,
    available_at: datetime | None = None,
    media_type: str = "application/json",
) -> OfficialSnapshotManifest:
    return OfficialSnapshotManifest(
        source_code=source_code,
        snapshot_id=f"{source_code.lower()}-{applicable_date:%Y%m%d}",
        publisher_code="KRX" if source_code.startswith("KRX_") else "SEC",
        cutoff_date=date(2026, 7, 11),
        applicable_date=applicable_date,
        published_at=published_at,
        available_at=available_at
        or datetime(2026, 7, 10, 23, 59, 59, tzinfo=timezone.utc),
        vintage_date=applicable_date,
        parser_version="1",
        mapping_version="1",
        objects=(
            OfficialObjectManifest(
                object_name=object_name,
                object_key=(
                    f"external/2026-07-11/{source_code}/synthetic/{object_name}"
                ),
                media_type=media_type,
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            ),
        ),
    )


def krx_security_basic_payload(
    rows: tuple[dict[str, str], ...] | None = None,
) -> bytes:
    values = rows if rows is not None else (
        {
            "ISU_CD": "KR7000000001",
            "ISU_SRT_CD": "000001",
            "ISU_NM": "합성 보통주",
            "ISU_ABBRV": "합성주",
            "ISU_ENG_NM": "Synthetic Common Stock",
            "LIST_DD": "20200102",
        },
    )
    return json.dumps(
        {"OutBlock_1": values}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def sec_series_class_payload(
    rows: tuple[dict[str, str], ...] | None = None,
) -> bytes:
    values = rows if rows is not None else (
        {
            "CIK": "0000123456",
            "Series ID": "S000000001",
            "Series Name": "Synthetic ETF Series",
            "Class ID": "C000000001",
            "Class Name": "Synthetic ETF Class",
            "Class Ticker": "SYNX",
        },
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "CIK",
            "Series ID",
            "Series Name",
            "Class ID",
            "Class Name",
            "Class Ticker",
        ),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(values)
    return output.getvalue().encode("utf-8")
