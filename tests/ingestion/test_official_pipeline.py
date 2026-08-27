from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from financial_agent.contracts import canonical_sha256
from financial_agent.ingestion.identity import build_authoritative_identity_index
from financial_agent.ingestion.mapping.common import stable_id
from financial_agent.ingestion.models import IdentifierCandidate, MappedRow
from financial_agent.ingestion.official.models import (
    OfficialObjectManifest,
    OfficialSnapshotManifest,
)
from financial_agent.ingestion.official_pipeline import (
    OrganizerInputs,
    OfficialPipelineError,
    build_stage03b_capacity_probe,
    build_stage03b_dataset,
    compose_stage03b_capacity_probe_manifest,
    compose_stage03b_manifest,
    load_official_manifests,
    verify_official_snapshot_objects,
)
from financial_agent.ingestion.official.snapshot import write_canonical_manifest
from financial_agent.ingestion.pipeline import OrganizerWriteResult
from financial_agent.db.schema.operations import active_dataset, dataset_version
from tests.fixtures.official_ingestion import (
    ecos_731y001_payload,
    official_manifest,
    krx_etf_daily_payload,
    krx_etf_pdf_payload,
    krx_security_basic_payload,
    sec_series_class_payload,
    write_sec_nport_archive,
)


ORGANIZER_MANIFEST = {
    "cutoff_date": "2026-08-24",
    "sources": [
        {
            "data_sha256": "a" * 64,
            "mapping_version": "1",
            "parser_version": "1",
            "source_code": "PREF01N001",
        }
    ],
}


def _manifest(
    tmp_path: Path,
    *,
    source_code: str,
    snapshot_id: str,
    payload: bytes,
) -> OfficialSnapshotManifest:
    import hashlib

    object_key = f"external/2026-08-24/{source_code}/{snapshot_id}/data.json"
    destination = tmp_path / object_key
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return OfficialSnapshotManifest(
        source_code=source_code,
        snapshot_id=snapshot_id,
        publisher_code="KRX",
        cutoff_date=date(2026, 8, 24),
        applicable_date=date(2026, 7, 10),
        published_at=None,
        available_at=datetime(2026, 7, 10, 23, 59, tzinfo=timezone.utc),
        vintage_date=date(2026, 7, 10),
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


def test_combined_manifest_is_order_independent_and_organizer_only_compatible(
    tmp_path: Path,
) -> None:
    first = _manifest(
        tmp_path,
        source_code="KRX_KOSPI_BASIC",
        snapshot_id="krx-kospi-20260710",
        payload=b"first",
    )
    second = _manifest(
        tmp_path,
        source_code="ECOS_731Y001",
        snapshot_id="ecos-20260710",
        payload=b"second",
    )

    organizer_only = compose_stage03b_manifest(ORGANIZER_MANIFEST, ())
    left = compose_stage03b_manifest(ORGANIZER_MANIFEST, (first, second))
    right = compose_stage03b_manifest(ORGANIZER_MANIFEST, (second, first))

    assert organizer_only == ORGANIZER_MANIFEST
    assert canonical_sha256(organizer_only) == canonical_sha256(ORGANIZER_MANIFEST)
    assert canonical_sha256(left) == canonical_sha256(right)


def test_capacity_probe_manifest_records_the_bounded_sample_contract(
    tmp_path: Path,
) -> None:
    manifest = _manifest(
        tmp_path,
        source_code="SEC_NPORT_2026Q2",
        snapshot_id="nport-2026q2",
        payload=b"nport",
    )

    combined = compose_stage03b_capacity_probe_manifest(
        ORGANIZER_MANIFEST,
        (manifest,),
        sample_product_count=100,
        full_holding_count=1_300_568,
    )

    assert combined["capacity_probe"] == {
        "full_holding_count": 1_300_568,
        "sample_product_count": 100,
        "sample_selection": "sha256_product_entity_id_v1",
    }
    assert canonical_sha256(combined) != canonical_sha256(
        compose_stage03b_manifest(ORGANIZER_MANIFEST, (manifest,))
    )


def test_canonical_official_manifests_load_in_stable_order(
    tmp_path: Path,
) -> None:
    first = _manifest(
        tmp_path,
        source_code="KRX_KOSPI_BASIC",
        snapshot_id="z-snapshot",
        payload=b"first",
    )
    second = _manifest(
        tmp_path,
        source_code="ECOS_731Y001",
        snapshot_id="a-snapshot",
        payload=b"second",
    )
    manifest_root = tmp_path / "manifests"
    write_canonical_manifest(first, manifest_root / "z.json")
    write_canonical_manifest(second, manifest_root / "a.json")

    loaded = load_official_manifests(manifest_root)

    assert loaded == (second, first)


def test_noncanonical_manifest_file_is_rejected(tmp_path: Path) -> None:
    manifest_root = tmp_path / "manifests"
    manifest_root.mkdir()
    (manifest_root / "bad.json").write_text('{"source_code":"unsafe"}\n')

    with pytest.raises(OfficialPipelineError) as captured:
        load_official_manifests(manifest_root)

    assert captured.value.code == "OFFICIAL_MANIFEST_INVALID"
    assert captured.value.__cause__ is None


def test_parser_or_mapping_version_changes_the_combined_manifest(
    tmp_path: Path,
) -> None:
    manifest = _manifest(
        tmp_path,
        source_code="KRX_KOSPI_BASIC",
        snapshot_id="krx-kospi-20260710",
        payload=b"payload",
    )
    baseline = canonical_sha256(
        compose_stage03b_manifest(ORGANIZER_MANIFEST, (manifest,))
    )

    assert baseline != canonical_sha256(
        compose_stage03b_manifest(
            ORGANIZER_MANIFEST,
            (replace(manifest, parser_version="2"),),
        )
    )
    assert baseline != canonical_sha256(
        compose_stage03b_manifest(
            ORGANIZER_MANIFEST,
            (replace(manifest, mapping_version="2"),),
        )
    )


def test_duplicate_snapshot_id_is_rejected(tmp_path: Path) -> None:
    first = _manifest(
        tmp_path,
        source_code="KRX_KOSPI_BASIC",
        snapshot_id="duplicate",
        payload=b"first",
    )
    second = _manifest(
        tmp_path,
        source_code="KRX_KOSDAQ_BASIC",
        snapshot_id="duplicate",
        payload=b"second",
    )

    with pytest.raises(OfficialPipelineError) as captured:
        compose_stage03b_manifest(ORGANIZER_MANIFEST, (first, second))

    assert captured.value.code == "OFFICIAL_SNAPSHOT_ID_DUPLICATE"
    assert captured.value.__cause__ is None


def test_missing_official_object_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        source_code="KRX_KOSPI_BASIC",
        snapshot_id="krx-kospi-20260710",
        payload=b"payload",
    )
    (tmp_path / manifest.objects[0].object_key).unlink()

    with pytest.raises(OfficialPipelineError) as captured:
        verify_official_snapshot_objects((manifest,), tmp_path)

    assert captured.value.code == "OFFICIAL_OBJECT_MISSING"
    assert captured.value.__cause__ is None


def test_official_build_reads_a_verified_immutable_object_snapshot(
    tmp_path: Path,
) -> None:
    from financial_agent.ingestion import official_pipeline

    payload = b"verified"
    manifest = _manifest(
        tmp_path,
        source_code="KRX_KOSPI_BASIC",
        snapshot_id="krx-kospi-20260710",
        payload=payload,
    )
    original = tmp_path / manifest.objects[0].object_key

    with official_pipeline._snapshot_official_inputs(
        (manifest,), tmp_path
    ) as verified:
        original.write_bytes(b"replaced")
        snapshot = verified[(manifest.snapshot_id, manifest.objects[0].object_key)]
        assert snapshot.read_bytes() == payload


class _RecordingWriter:
    instances: list["_RecordingWriter"] = []

    def __init__(self, engine: object) -> None:
        del engine
        self.created: list[tuple[str, str, date]] = []
        self.writes: list[tuple[str, tuple[object, ...]]] = []
        type(self).instances.append(self)

    async def create_building_dataset(
        self, dataset_version: str, manifest_hash: str, cutoff: date
    ) -> None:
        self.created.append((dataset_version, manifest_hash, cutoff))

    async def table_counts(self, dataset_version: str) -> dict[str, int]:
        del dataset_version
        return {"catalog.entity": 4}

    async def write_rows(
        self, dataset_version: str, rows: object
    ) -> None:
        self.writes.append((dataset_version, tuple(rows)))  # type: ignore[arg-type]


def _organizer_inputs() -> OrganizerInputs:
    return OrganizerInputs(
        data_paths={"synthetic": Path("/synthetic-data.xlsx")},
        schema_paths={"synthetic": Path("/synthetic-schema.xlsx")},
        data_sha256={"synthetic": "a" * 64},
        schema_sha256={"synthetic": "b" * 64},
    )


def _configure_build_seams(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from financial_agent.ingestion import official_pipeline

    events: list[str] = []
    _RecordingWriter.instances.clear()

    @contextmanager
    def snapshots(data_paths: object, schema_paths: object):
        del data_paths, schema_paths
        events.append("organizer_snapshot")
        yield (
            {"synthetic": Path("/snapshot-data.xlsx")},
            {"synthetic": Path("/snapshot-schema.xlsx")},
        )

    def preflight(**kwargs: object) -> object:
        del kwargs
        events.append("organizer_preflight")
        identity_index = build_authoritative_identity_index(
            (
                IdentifierCandidate(
                    source_code="PREF01N001",
                    row_number=2,
                    natural_key="KR7305080004",
                    entity_role="DomesticETF",
                    scheme="PREF01_PD_ITM_NO",
                    value="KR7305080004",
                ),
                IdentifierCandidate(
                    source_code="PREF01N001",
                    row_number=2,
                    natural_key="KR7305080004",
                    entity_role="DomesticETF",
                    scheme="ISIN",
                    value="KR7305080004",
                ),
                IdentifierCandidate(
                    source_code="PREF02N001",
                    row_number=2,
                    natural_key="OVERSEAS-ETF-1",
                    entity_role="OverseasETF",
                    scheme="PREF02_PD_ITM_NO",
                    value="OVERSEAS-ETF-1",
                ),
            )
        )
        return SimpleNamespace(
            manifest=ORGANIZER_MANIFEST,
            manifest_hash=canonical_sha256(ORGANIZER_MANIFEST),
            contexts={"PREF02N001": {}},
            data_hashes={},
            identity_index=identity_index,
        )

    def map_source_row(
        source_code: str,
        row_number: int,
        row: dict[str, object],
        context: object,
        identity_index: object,
    ) -> MappedRow:
        del context, identity_index
        product_id = stable_id(
            "product", source_code, str(row["pd_itm_no"])
        )
        accepted = bool(row.get("pd_itm_no_ma"))
        return MappedRow(
            row_number=row_number,
            disposition="accepted" if accepted else "quarantined",
            records_by_table={
                "catalog.entity": (
                    {
                        "entity_id": product_id,
                        "entity_type": "product",
                    },
                )
                if accepted
                else (),
            },
            issues=(),
        )

    async def write_organizer(*args: object, **kwargs: object) -> OrganizerWriteResult:
        del args, kwargs
        events.append("organizer_write")
        return OrganizerWriteResult(
            source_counts={"PREF01N001": {"accepted": 1, "rows": 1}},
            issue_counts={},
            passed=True,
        )

    async def hashes(*args: object, **kwargs: object) -> dict[str, str]:
        del args, kwargs
        return {"postgresql": "c" * 64, "evidence": "d" * 64}

    monkeypatch.setattr(official_pipeline, "_snapshot_source_inputs", snapshots)
    monkeypatch.setattr(official_pipeline, "_preflight_sources", preflight)
    monkeypatch.setattr(official_pipeline, "DatasetBuildWriter", _RecordingWriter)
    monkeypatch.setattr(
        official_pipeline,
        "write_preflighted_organizer_rows",
        write_organizer,
    )
    monkeypatch.setattr(official_pipeline, "_database_component_hashes", hashes)
    monkeypatch.setattr(
        official_pipeline.organizer_pipeline,
        "_map_source_row",
        map_source_row,
    )
    return events


@pytest.mark.asyncio
async def test_organizer_only_combined_build_preserves_manifest_and_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events = _configure_build_seams(monkeypatch)

    report = await build_stage03b_dataset(
        object(),
        dataset_version="combined-organizer-only",
        organizer_inputs=_organizer_inputs(),
        official_manifests=(),
        official_object_root=tmp_path,
    )

    writer = _RecordingWriter.instances[0]
    assert events == [
        "organizer_snapshot",
        "organizer_preflight",
        "organizer_write",
    ]
    assert writer.created == [
        (
            "combined-organizer-only",
            canonical_sha256(ORGANIZER_MANIFEST),
                date(2026, 8, 24),
        )
    ]
    assert report.dataset_manifest_hash == canonical_sha256(ORGANIZER_MANIFEST)
    assert report.source_counts == {
        "PREF01N001": {"accepted": 1, "rows": 1}
    }


@pytest.mark.asyncio
async def test_combined_build_object_failure_creates_no_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_build_seams(monkeypatch)
    manifest = _manifest(
        tmp_path,
        source_code="ECOS_731Y001",
        snapshot_id="ecos-20260710",
        payload=b"payload",
    )
    (tmp_path / manifest.objects[0].object_key).unlink()

    with pytest.raises(OfficialPipelineError) as captured:
        await build_stage03b_dataset(
            object(),
            dataset_version="combined-invalid",
            organizer_inputs=_organizer_inputs(),
            official_manifests=(manifest,),
            official_object_root=tmp_path,
        )

    assert captured.value.code == "OFFICIAL_OBJECT_MISSING"
    assert _RecordingWriter.instances == []


@pytest.mark.asyncio
async def test_ecos_snapshot_is_preflighted_then_written_with_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_build_seams(monkeypatch)
    payload = ecos_731y001_payload()
    manifest = official_manifest(
        source_code="ECOS_731Y001",
        object_name="ecos.json",
        payload=payload,
        applicable_date=date(2026, 7, 10),
    )
    destination = tmp_path / manifest.objects[0].object_key
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)

    report = await build_stage03b_dataset(
        object(),
        dataset_version="combined-ecos",
        organizer_inputs=_organizer_inputs(),
        official_manifests=(manifest,),
        official_object_root=tmp_path,
        batch_size=2,
    )

    writer = _RecordingWriter.instances[0]
    assert len(writer.created) == 1
    assert [len(rows) for _, rows in writer.writes] == [2, 2]
    assert report.source_counts["ECOS_731Y001"] == {
        "COVERED": 0,
        "CONFLICT": 0,
        "NOT_COVERED": 0,
        "PARTIALLY_COVERED": 0,
        "accepted": 4,
        "fatal": 0,
        "limited": 0,
        "quarantined": 0,
        "rows": 4,
        "snapshots": 1,
    }


@pytest.mark.asyncio
async def test_official_schema_failure_happens_before_dataset_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_build_seams(monkeypatch)
    payload = b'{"unexpected":true}'
    manifest = official_manifest(
        source_code="ECOS_731Y001",
        object_name="ecos.json",
        payload=payload,
        applicable_date=date(2026, 7, 10),
    )
    destination = tmp_path / manifest.objects[0].object_key
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)

    with pytest.raises(Exception) as captured:
        await build_stage03b_dataset(
            object(),
            dataset_version="combined-bad-ecos",
            organizer_inputs=_organizer_inputs(),
            official_manifests=(manifest,),
            official_object_root=tmp_path,
        )

    assert getattr(captured.value, "code", None) == "ECOS_FX_SCHEMA_MISMATCH"
    assert _RecordingWriter.instances == []


@pytest.mark.asyncio
async def test_unapproved_manager_format_is_not_generalized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_build_seams(monkeypatch)
    payload = b"unapproved-manager-format"
    manifest = _manifest(
        tmp_path,
        source_code="UNAPPROVED_MANAGER_HOLDINGS",
        snapshot_id="manager-20260710",
        payload=payload,
    )

    with pytest.raises(OfficialPipelineError) as captured:
        await build_stage03b_dataset(
            object(),
            dataset_version="combined-manager-invalid",
            organizer_inputs=_organizer_inputs(),
            official_manifests=(manifest,),
            official_object_root=tmp_path,
        )

    assert captured.value.code == "OFFICIAL_SOURCE_UNSUPPORTED"
    assert _RecordingWriter.instances == []


def _store_manifest_object(
    root: Path,
    manifest: OfficialSnapshotManifest,
    payload: bytes,
) -> None:
    destination = root / manifest.objects[0].object_key
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)


@pytest.mark.asyncio
async def test_krx_identity_holdings_market_and_ecos_follow_fixed_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from financial_agent.ingestion import official_pipeline

    _configure_build_seams(monkeypatch)
    monkeypatch.setattr(
        official_pipeline,
        "_organizer_rows_for_official",
        lambda data_paths, source_codes: {
            "PREF01N001": (
                {
                    "pd_grp_no": "ETF",
                    "pd_itm_no": "KR7305080004",
                    "pd_ticker": "305080",
                    "pd_abrv_nm": "TIGER 미국채10년선물",
                    "pd_lste_dt": "99991231",
                },
            )
        },
        raising=False,
    )
    basic_payload = krx_security_basic_payload(
        (
            {
                "ISU_CD": "KR7005930003",
                "ISU_SRT_CD": "005930",
                "ISU_NM": "삼성전자",
                "ISU_ABBRV": "삼성전자",
                "ISU_ENG_NM": "Samsung Electronics",
            },
        )
    )
    daily_payload = krx_etf_daily_payload()
    holdings_payload = krx_etf_pdf_payload()
    ecos_payload = ecos_731y001_payload()
    manifests = (
        official_manifest(
            source_code="KRX_ETF_DAILY",
            object_name="etf-daily-20260710.json",
            payload=daily_payload,
            applicable_date=date(2026, 7, 10),
        ),
        official_manifest(
            source_code="ECOS_731Y001",
            object_name="ecos.json",
            payload=ecos_payload,
            applicable_date=date(2026, 7, 10),
        ),
        official_manifest(
            source_code="KRX_ETF_PDF",
            object_name="305080_20260710.csv",
            payload=holdings_payload,
            applicable_date=date(2026, 7, 10),
            media_type="text/csv",
        ),
        official_manifest(
            source_code="KRX_KOSPI_BASIC",
            object_name="kospi-basic.json",
            payload=basic_payload,
            applicable_date=date(2026, 7, 10),
        ),
    )
    for manifest, payload in zip(
        manifests,
        (daily_payload, ecos_payload, holdings_payload, basic_payload),
        strict=True,
    ):
        _store_manifest_object(tmp_path, manifest, payload)

    report = await build_stage03b_dataset(
        object(),
        dataset_version="combined-krx",
        organizer_inputs=_organizer_inputs(),
        official_manifests=manifests,
        official_object_root=tmp_path,
        batch_size=1000,
    )

    official_codes = list(report.source_counts)[1:]
    assert official_codes == [
        "KRX_KOSPI_BASIC",
        "KRX_ETF_PDF",
        "KRX_ETF_DAILY",
        "ECOS_731Y001",
    ]
    assert report.source_counts["KRX_KOSPI_BASIC"]["accepted"] == 1
    assert report.source_counts["KRX_ETF_PDF"]["PARTIALLY_COVERED"] == 1
    assert report.source_counts["KRX_ETF_DAILY"]["accepted"] == 1
    assert report.source_counts["ECOS_731Y001"]["accepted"] == 4


@pytest.mark.asyncio
async def test_current_krx_holdings_do_not_require_daily_market_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from financial_agent.ingestion import official_pipeline

    _configure_build_seams(monkeypatch)
    monkeypatch.setattr(
        official_pipeline,
        "_organizer_rows_for_official",
        lambda data_paths, source_codes: {
            "PREF01N001": (
                {
                    "pd_grp_no": "ETF",
                    "pd_itm_no": "KR7305080004",
                    "pd_ticker": "305080",
                    "pd_abrv_nm": "TIGER 미국채10년선물",
                    "pd_lste_dt": "99991231",
                },
            )
        },
        raising=False,
    )
    holdings_payload = krx_etf_pdf_payload()
    holdings_manifest = official_manifest(
        source_code="KRX_ETF_PDF",
        object_name="305080_20260822.csv",
        payload=holdings_payload,
        applicable_date=date(2026, 8, 22),
        available_at=datetime(2026, 8, 24, 5, 59, 59, tzinfo=timezone.utc),
        media_type="text/csv",
    )
    _store_manifest_object(tmp_path, holdings_manifest, holdings_payload)

    report = await build_stage03b_dataset(
        object(),
        dataset_version="combined-current-holdings",
        organizer_inputs=_organizer_inputs(),
        official_manifests=(holdings_manifest,),
        official_object_root=tmp_path,
        batch_size=1000,
    )

    assert report.source_counts["KRX_ETF_PDF"]["PARTIALLY_COVERED"] == 1
    assert report.source_counts["KRX_ETF_PDF"]["limited"] == 1
    assert report.source_counts["KRX_ETF_PDF"]["fatal"] == 0


@pytest.mark.asyncio
async def test_sec_crosswalk_precedes_bounded_nport_holdings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from financial_agent.ingestion import official_pipeline

    _configure_build_seams(monkeypatch)
    monkeypatch.setattr(
        official_pipeline,
        "_organizer_rows_for_official",
        lambda data_paths, source_codes: {
            "PREF02N001": (
                {
                    "pd_itm_no": "OVERSEAS-ETF-1",
                    "pd_itm_no_ma": "OVERSEAS-ETF-MASTER-1",
                    "pd_nm": "Synthetic Overseas ETF",
                    "pd_us_cik": "0000123456",
                    "pd_abrv_nm": "SYNX",
                },
            )
        },
    )
    series_payload = sec_series_class_payload()
    archive_path = write_sec_nport_archive(tmp_path / "nport.zip")
    archive_payload = archive_path.read_bytes()
    series_manifest = official_manifest(
        source_code="SEC_SERIES_CLASS_20260601",
        object_name="series-class.csv",
        payload=series_payload,
        applicable_date=date(2026, 6, 1),
        published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        media_type="text/csv",
    )
    nport_manifest = official_manifest(
        source_code="SEC_NPORT_2026Q2",
        object_name="nport-2026q2.zip",
        payload=archive_payload,
        applicable_date=date(2026, 3, 31),
        published_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
        media_type="application/zip",
    )
    _store_manifest_object(tmp_path, series_manifest, series_payload)
    _store_manifest_object(tmp_path, nport_manifest, archive_payload)

    report = await build_stage03b_dataset(
        object(),
        dataset_version="combined-sec",
        organizer_inputs=_organizer_inputs(),
        official_manifests=(nport_manifest, series_manifest),
        official_object_root=tmp_path,
    )

    assert list(report.source_counts)[1:] == [
        "SEC_SERIES_CLASS_20260601",
        "SEC_NPORT_2026Q2",
    ]
    assert report.source_counts["SEC_SERIES_CLASS_20260601"]["snapshots"] == 1
    assert report.source_counts["SEC_NPORT_2026Q2"]["COVERED"] == 1
    assert report.source_counts["SEC_NPORT_2026Q2"]["accepted"] == 1


@pytest.mark.asyncio
async def test_nport_does_not_bind_an_organizer_quarantined_product(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from financial_agent.ingestion import official_pipeline

    _configure_build_seams(monkeypatch)
    monkeypatch.setattr(
        official_pipeline,
        "_organizer_rows_for_official",
        lambda data_paths, source_codes: {
            "PREF02N001": (
                {
                    "pd_itm_no": "OVERSEAS-ETF-1",
                    "pd_us_cik": "0000123456",
                    "pd_abrv_nm": "SYNX",
                },
            )
        },
    )
    series_payload = sec_series_class_payload()
    archive_path = write_sec_nport_archive(tmp_path / "nport.zip")
    archive_payload = archive_path.read_bytes()
    series_manifest = official_manifest(
        source_code="SEC_SERIES_CLASS_20260601",
        object_name="series-class.csv",
        payload=series_payload,
        applicable_date=date(2026, 6, 1),
        published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        media_type="text/csv",
    )
    nport_manifest = official_manifest(
        source_code="SEC_NPORT_2026Q2",
        object_name="nport-2026q2.zip",
        payload=archive_payload,
        applicable_date=date(2026, 3, 31),
        published_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
        media_type="application/zip",
    )
    _store_manifest_object(tmp_path, series_manifest, series_payload)
    _store_manifest_object(tmp_path, nport_manifest, archive_payload)

    report = await build_stage03b_dataset(
        object(),
        dataset_version="combined-sec-organizer-quarantined",
        organizer_inputs=_organizer_inputs(),
        official_manifests=(nport_manifest, series_manifest),
        official_object_root=tmp_path,
    )

    assert report.source_counts["SEC_NPORT_2026Q2"]["rows"] == 0


@pytest.mark.asyncio
async def test_capacity_probe_measures_base_then_sample_and_stays_inactive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from financial_agent.ingestion import official_pipeline

    _configure_build_seams(monkeypatch)
    monkeypatch.setattr(
        official_pipeline,
        "_organizer_rows_for_official",
        lambda data_paths, source_codes: {
            "PREF02N001": (
                {
                    "pd_itm_no": "OVERSEAS-ETF-1",
                    "pd_itm_no_ma": "OVERSEAS-ETF-MASTER-1",
                    "pd_nm": "Synthetic Overseas ETF",
                    "pd_us_cik": "0000123456",
                    "pd_abrv_nm": "SYNX",
                },
            )
        },
    )
    measurements = iter((100, 700, 1_700))

    async def measure(engine: object) -> int:
        del engine
        return next(measurements)

    async def count_holdings(engine: object, dataset: str) -> int:
        del engine, dataset
        return 1

    async def state(engine: object, dataset: str) -> tuple[str, bool]:
        del engine, dataset
        return "building", False

    async def absent(engine: object, dataset: str) -> None:
        del engine, dataset

    monkeypatch.setattr(
        official_pipeline, "measure_application_storage_bytes", measure
    )
    monkeypatch.setattr(
        official_pipeline, "count_nport_holding_relations", count_holdings
    )
    monkeypatch.setattr(
        official_pipeline, "capacity_probe_dataset_state", state
    )
    monkeypatch.setattr(
        official_pipeline, "require_capacity_probe_dataset_absent", absent
    )
    series_payload = sec_series_class_payload()
    archive_path = write_sec_nport_archive(tmp_path / "nport.zip")
    archive_payload = archive_path.read_bytes()
    series_manifest = official_manifest(
        source_code="SEC_SERIES_CLASS_20260601",
        object_name="series-class.csv",
        payload=series_payload,
        applicable_date=date(2026, 6, 1),
        published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        media_type="text/csv",
    )
    nport_manifest = official_manifest(
        source_code="SEC_NPORT_2026Q2",
        object_name="nport-2026q2.zip",
        payload=archive_payload,
        applicable_date=date(2026, 3, 31),
        published_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
        media_type="application/zip",
    )
    _store_manifest_object(tmp_path, series_manifest, series_payload)
    _store_manifest_object(tmp_path, nport_manifest, archive_payload)

    report = await build_stage03b_capacity_probe(
        object(),
        dataset_version="capacity-probe-new",
        organizer_inputs=_organizer_inputs(),
        official_manifests=(nport_manifest, series_manifest),
        official_object_root=tmp_path,
        sample_product_count=1,
        full_holding_count=10,
        current_storage_gib=20,
    )

    assert report.sample_product_count == 1
    assert report.sample_holding_count == 1
    assert report.storage_before_bytes == 100
    assert report.base_bytes == 600
    assert report.sampled_nport_bytes == 1_000
    assert report.dataset_status == "building"
    assert report.active is False
    assert report.estimate.projected_nport_bytes == 10_000


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_combined_build_remains_building_and_inactive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    ingestion_build_engine: AsyncEngine,
) -> None:
    from financial_agent.ingestion import official_pipeline

    @contextmanager
    def snapshots(data_paths: object, schema_paths: object):
        del data_paths, schema_paths
        yield (
            {"synthetic": Path("/snapshot-data.xlsx")},
            {"synthetic": Path("/snapshot-schema.xlsx")},
        )

    monkeypatch.setattr(official_pipeline, "_snapshot_source_inputs", snapshots)
    monkeypatch.setattr(
        official_pipeline,
        "_preflight_sources",
        lambda **kwargs: SimpleNamespace(
            manifest=ORGANIZER_MANIFEST,
            manifest_hash=canonical_sha256(ORGANIZER_MANIFEST),
            contexts={},
            data_hashes={},
            identity_index=build_authoritative_identity_index(()),
        ),
    )
    monkeypatch.setattr(
        official_pipeline,
        "_organizer_rows_for_official",
        lambda data_paths, source_codes: {},
    )

    async def no_organizer_rows(
        *args: object, **kwargs: object
    ) -> OrganizerWriteResult:
        del args, kwargs
        return OrganizerWriteResult(
            source_counts={"PREF01N001": {"accepted": 0, "rows": 0}},
            issue_counts={},
            passed=True,
        )

    monkeypatch.setattr(
        official_pipeline,
        "write_preflighted_organizer_rows",
        no_organizer_rows,
    )
    payload = ecos_731y001_payload()
    manifest = official_manifest(
        source_code="ECOS_731Y001",
        object_name="ecos.json",
        payload=payload,
        applicable_date=date(2026, 7, 10),
    )
    _store_manifest_object(tmp_path, manifest, payload)
    version = f"combined-{uuid4()}"

    report = await build_stage03b_dataset(
        ingestion_build_engine,
        dataset_version=version,
        organizer_inputs=_organizer_inputs(),
        official_manifests=(manifest,),
        official_object_root=tmp_path,
    )

    async with ingestion_build_engine.connect() as connection:
        status = await connection.scalar(
            sa.select(dataset_version.c.status).where(
                dataset_version.c.dataset_version == version
            )
        )
        active = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(active_dataset)
            .where(active_dataset.c.dataset_version == version)
        )
    assert report.passed is True
    assert status == "building"
    assert active == 0
