import hashlib
import json
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace

import pytest

from scripts.audit_personal_holdings import audit


@pytest.fixture
def capture(tmp_path, monkeypatch):
    import scripts.audit_personal_holdings as module

    base = tmp_path / "data/generated/stage03b/current-krx-holdings-capture"
    manifests = base / "manifests/KRX_ETF_PDF"
    objects = base / "objects"
    manifests.mkdir(parents=True)
    objects.mkdir()
    personal = tmp_path / "data/personal-local"
    personal.mkdir()
    (personal / "manifest.json").write_text(json.dumps({"personal_scope": {"krx_short_codes": ["123456"]}}))
    raw = "종목코드,시가총액 구성비중\n005930,\n000001,0\n000002,1.25\n".encode("cp949")
    (objects / "sample.csv").write_bytes(raw)
    (manifests / "krx-etf-pdf-123456-test.json").write_text(json.dumps({"objects": [{"object_key": "sample.csv", "sha256": hashlib.sha256(raw).hexdigest()}]}))
    rows = [{"observation_id": str(i), "numeric_value": value, "value_status": status,
        "reason_code": "SOURCE_VALUE_MISSING" if value is None else None,
        "locator": "sample.csv", "row": i + 2, "column": "시가총액 구성비중"}
        for i, (value, status) in enumerate([(None, "unknown"), (Decimal(0), "zero"), (Decimal('1.25'), "present")])]

    def connect(*args, **kwargs):
        assert "default_transaction_read_only=on" in kwargs["options"]
        return nullcontext(SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: rows)))

    monkeypatch.setattr(module.psycopg, "connect", connect)
    return tmp_path, rows, objects / "sample.csv"


def test_audit_distinguishes_blank_zero_and_value(capture):
    root, _, _ = capture
    result = audit(root)
    assert result["source_known_weights"] == result["db_known_weights"] == 2
    assert result["source_missing_weights"] == result["db_missing_weights"] == 1
    assert result["mismatches"] == []


def test_audit_finds_lost_populated_value(capture):
    root, rows, _ = capture
    rows[2].update(numeric_value=None, value_status="unknown", reason_code="SOURCE_VALUE_MISSING")
    assert audit(root)["mismatches"][0]["reason"] == "SOURCE_VALUE_MISMATCH"


def test_audit_blocks_changed_source(capture):
    root, _, source = capture
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SOURCE_CHECKSUM_MISMATCH"):
        audit(root)


def test_audit_reports_unmapped_rows(capture):
    root, rows, _ = capture
    rows.pop()
    assert audit(root)["raw_rows_without_weight_observation"] == 1


def test_audit_reports_missing_origin(capture):
    root, rows, _ = capture
    rows[0]["locator"] = None
    assert audit(root)["mismatches"][0]["reason"] == "SOURCE_NOT_FOUND"
