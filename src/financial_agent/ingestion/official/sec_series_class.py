from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping

from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.sources import SourceVerificationError

from .identity import IdentityCandidate, OfficialIdentityIndex
from .models import OfficialSnapshotManifest
from .snapshot import validate_official_snapshot


_FIELDS = (
    "CIK",
    "Series ID",
    "Series Name",
    "Class ID",
    "Class Name",
    "Class Ticker",
)


def _error(code: str, message: str) -> SourceVerificationError:
    return SourceVerificationError(code, message)


def parse_sec_series_class(payload: bytes) -> tuple[Mapping[str, object], ...]:
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8"), newline=""))
        if tuple(reader.fieldnames or ()) != _FIELDS:
            raise TypeError
        rows: list[Mapping[str, object]] = []
        for raw_row in reader:
            if None in raw_row or set(raw_row) != set(_FIELDS):
                raise TypeError
            row = {field: raw_row[field] for field in _FIELDS}
            if any(not isinstance(value, str) for value in row.values()):
                raise TypeError
            if not all(row[field] for field in ("CIK", "Series ID", "Class ID")):
                raise TypeError
            rows.append(row)
        if not rows:
            raise TypeError
        return tuple(rows)
    except Exception:
        raise _error(
            "SEC_SERIES_CLASS_SCHEMA_MISMATCH",
            "SEC Series/Class report differs from the approved schema",
        ) from None


def build_sec_series_class_index(
    manifest: OfficialSnapshotManifest,
    rows: Iterable[Mapping[str, object]],
) -> OfficialIdentityIndex:
    if manifest.source_code != "SEC_SERIES_CLASS_20260601":
        raise _error(
            "SEC_SERIES_CLASS_SOURCE_MISMATCH",
            "SEC Series/Class manifest source is invalid",
        ) from None
    validate_official_snapshot(manifest)
    exact_entries: list[tuple[IdentityCandidate, str]] = []
    compound_entries: list[tuple[str, tuple[str, ...], str]] = []
    class_ids: set[str] = set()
    for row in rows:
        cik = str(row["CIK"])
        series_id = str(row["Series ID"]).upper()
        class_id = str(row["Class ID"]).upper()
        ticker = str(row["Class Ticker"])
        if (
            re.fullmatch(r"[0-9]{1,10}", cik) is None
            or re.fullmatch(r"S[0-9]{9}", series_id) is None
            or re.fullmatch(r"C[0-9]{9}", class_id) is None
        ):
            raise _error(
                "SEC_SERIES_CLASS_IDENTIFIER_INVALID",
                "SEC Series/Class report contains an invalid identifier",
            ) from None
        if class_id in class_ids:
            raise _error(
                "SEC_SERIES_CLASS_DUPLICATE_CLASS_ID",
                "SEC Series/Class report contains a duplicate class ID",
            ) from None
        class_ids.add(class_id)
        entity_id = stable_id("product", manifest.source_code, series_id)
        exact_entries.extend(
            (
                (IdentityCandidate("SEC_SERIES_ID", series_id), entity_id),
                (IdentityCandidate("SEC_CLASS_ID", class_id), entity_id),
            )
        )
        if ticker.strip():
            compound_entries.append(
                (
                    "SEC_CIK_CLASS_TICKER",
                    (cik, ticker),
                    entity_id,
                )
            )
    return OfficialIdentityIndex(
        exact_entries=exact_entries,
        compound_entries=compound_entries,
    )
