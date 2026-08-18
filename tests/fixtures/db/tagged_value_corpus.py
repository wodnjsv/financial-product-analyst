from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal


VALID_TAGGED_VALUES: tuple[tuple[object, dict[str, object]], ...] = (
    (None, {"type": "null", "value": None}),
    ("plain text", {"type": "string", "value": "plain text"}),
    ("2026-07-11", {"type": "string", "value": "2026-07-11"}),
    ("1.0", {"type": "string", "value": "1.0"}),
    (7, {"type": "integer", "value": 7}),
    (Decimal("0"), {"type": "decimal", "value": "0"}),
    (Decimal("1.00"), {"type": "decimal", "value": "1"}),
    (
        Decimal("0.000100000000"),
        {"type": "decimal", "value": "0.0001"},
    ),
    (
        Decimal("12345678901234567890.1234500"),
        {"type": "decimal", "value": "12345678901234567890.12345"},
    ),
    (False, {"type": "boolean", "value": False}),
    (True, {"type": "boolean", "value": True}),
    (date(2026, 7, 11), {"type": "date", "value": "2026-07-11"}),
    (
        datetime(2026, 7, 11, tzinfo=UTC),
        {"type": "datetime", "value": "2026-07-11T00:00:00Z"},
    ),
    (
        datetime(2026, 7, 11, 0, 0, 0, 123456, tzinfo=UTC),
        {
            "type": "datetime",
            "value": "2026-07-11T00:00:00.123456Z",
        },
    ),
    ((), {"type": "tuple", "items": []}),
    (
        (1, 2, 3),
        {
            "type": "tuple",
            "items": [
                {"type": "integer", "value": 1},
                {"type": "integer", "value": 2},
                {"type": "integer", "value": 3},
            ],
        },
    ),
    (
        (date(2026, 7, 11), "2026-07-11", Decimal("1.0"), "1.0"),
        {
            "type": "tuple",
            "items": [
                {"type": "date", "value": "2026-07-11"},
                {"type": "string", "value": "2026-07-11"},
                {"type": "decimal", "value": "1"},
                {"type": "string", "value": "1.0"},
            ],
        },
    ),
)


INVALID_TAGGED_JSON: tuple[object, ...] = (
    "untagged",
    1.5,
    ["untagged"],
    {"value": "missing-type"},
    {"type": "string"},
    {"type": "unknown", "value": "x"},
    {"type": "string", "value": "x", "extra": True},
    {"type": "null", "value": "null"},
    {"type": "string", "value": True},
    {"type": "integer", "value": True},
    {"type": "integer", "value": 1.5},
    {"type": "decimal", "value": 1},
    {"type": "decimal", "value": "1.0"},
    {"type": "decimal", "value": "1E+1000000"},
    {"type": "boolean", "value": 1},
    {"type": "date", "value": True},
    {"type": "date", "value": "2026-02-30"},
    {"type": "date", "value": "2025-02-29"},
    {"type": "datetime", "value": 0},
    {"type": "datetime", "value": "2026-07-11T00:00:00"},
    {"type": "datetime", "value": "2026-07-11T09:00:00+09:00"},
    {"type": "datetime", "value": "2026-07-11T00:00:00.1Z"},
    {"type": "datetime", "value": "2026-07-11T00:00:00.000000Z"},
    {"type": "datetime", "value": "2026-07-11T24:00:00Z"},
    {"type": "tuple", "items": "not-an-array"},
    {
        "type": "tuple",
        "items": [{"type": "tuple", "items": []}],
    },
)


INVALID_NATIVE_VALUES: tuple[object, ...] = (
    1.5,
    ["x"],
    {"value": "x"},
    (("nested",),),
    datetime(2026, 7, 11),
    datetime(2026, 7, 11, tzinfo=timezone(timedelta(hours=9))),
    Decimal("NaN"),
    Decimal("Infinity"),
)
