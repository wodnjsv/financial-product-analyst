from datetime import date

import pytest

from scripts.build_personal_dataset import select_krx_manifests
from tests.fixtures.official_ingestion import official_manifest


def test_selection_preserves_whole_snapshots_and_is_order_independent():
    from dataclasses import replace

    base = official_manifest(source_code="KRX_ETF_PDF", object_name="a.csv",
        payload=b"source", applicable_date=date(2026, 8, 22))
    items = tuple(replace(base, snapshot_id=f"snapshot-{i}") for i in range(60))
    first = select_krx_manifests(items)
    assert len(first) == 50
    assert first == select_krx_manifests(tuple(reversed(items)))
    assert all(item in items and item.objects == base.objects for item in first)


def test_selection_refuses_silent_undercoverage():
    with pytest.raises(ValueError, match="INSUFFICIENT"):
        select_krx_manifests(())
