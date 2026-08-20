from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from openpyxl import Workbook


def write_data_workbook(
    path: Path,
    *,
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    sheet_name: str = "datarows",
) -> Path:
    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet(sheet_name)
    worksheet.append(tuple(headers))
    for row in rows:
        worksheet.append(tuple(row))
    workbook.save(path)
    return path


def write_schema_workbook(
    path: Path,
    *,
    headers: Sequence[str],
    sheet_name: str = "Sheet1_Schema",
) -> Path:
    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet(sheet_name)
    worksheet.append(("2026-07-11",))
    worksheet.append(
        ("컬럼명", "PK/FK", "컬럼타입", "컬럼한글명", "컬럼값 예시")
    )
    for header in headers:
        worksheet.append((header, "", "text", "", ""))
    workbook.save(path)
    return path
