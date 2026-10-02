"""Read-only reconciliation of personal KRX weights against retained captures."""

import argparse
import csv
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DATASET = "personal-2026-08-24-v1"


def audit(root: Path) -> dict:
    capture = root / "data/generated/stage03b/current-krx-holdings-capture"
    manifest = json.loads((root / "data/personal-local/manifest.json").read_text())
    codes = manifest["personal_scope"]["krx_short_codes"]
    raw_values = {}
    files = set()
    for code in codes:
        paths = list((capture / "manifests/KRX_ETF_PDF").glob(f"krx-etf-pdf-{code}-*.json"))
        if len(paths) != 1:
            raise ValueError("SOURCE_MANIFEST_AMBIGUOUS")
        source = json.loads(paths[0].read_text())
        obj = source["objects"][0]
        path = (capture / "objects" / obj["object_key"]).resolve()
        if not path.is_relative_to((capture / "objects").resolve()):
            raise ValueError("SOURCE_PATH_INVALID")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != obj["sha256"]:
            raise ValueError("SOURCE_CHECKSUM_MISMATCH")
        files.add(obj["object_key"])
        for number, row in enumerate(csv.DictReader(io.StringIO(raw.decode("cp949"))), 2):
            value = row["시가총액 구성비중"].strip().replace(",", "")
            raw_values[(obj["object_key"], number)] = (
                None if value in ("", "-") else Decimal(value)
            )
    with psycopg.connect(
        "postgresql://localhost/financial_agent_local", row_factory=dict_row,
        options="-c role=fa_runtime -c default_transaction_read_only=on -c statement_timeout=30000",
    ) as conn:
        rows = conn.execute("""
            SELECT o.observation_id,o.numeric_value,o.value_status,o.reason_code,
                   er.locator_uri_or_object_key AS locator,er.locator_row AS row,
                   er.locator_column AS column
            FROM observation.observation_record o
            LEFT JOIN evidence.evidence_observation_origin eo
              ON eo.dataset_version=o.dataset_version AND eo.observation_id=o.observation_id
            LEFT JOIN evidence.evidence_record er
              ON er.dataset_version=eo.dataset_version AND er.evidence_id=eo.evidence_id
            WHERE o.dataset_version=%s AND o.metric_id='krx_etf_holding_weight_pct'
            ORDER BY o.observation_id
        """, (DATASET,)).fetchall()
    seen = set()
    matched_sources = set()
    mismatches = []
    for row in rows:
        key = (row["locator"], row["row"])
        if row["observation_id"] in seen:
            mismatches.append({"observation_id": str(row["observation_id"]), "reason": "MULTIPLE_ORIGINS"})
        seen.add(row["observation_id"])
        if key not in raw_values or row["column"] != "시가총액 구성비중":
            mismatches.append({"observation_id": str(row["observation_id"]), "reason": "SOURCE_NOT_FOUND"})
            continue
        matched_sources.add(key)
        value = raw_values[key]
        status = "unknown" if value is None else "zero" if value == 0 else "present"
        reason = "SOURCE_VALUE_MISSING" if value is None else None
        if (row["numeric_value"], row["value_status"], row["reason_code"]) != (value, status, reason):
            mismatches.append({"observation_id": str(row["observation_id"]), "reason": "SOURCE_VALUE_MISMATCH"})
    return {
        "dataset": DATASET, "read_only": True, "source_files": len(files),
        "source_rows": len(raw_values),
        "source_known_weights": sum(v is not None for v in raw_values.values()),
        "source_missing_weights": sum(v is None for v in raw_values.values()),
        "db_observations": len(seen),
        "db_known_weights": sum(r["numeric_value"] is not None for r in rows),
        "db_missing_weights": sum(r["numeric_value"] is None for r in rows),
        "raw_rows_without_weight_observation": len(set(raw_values) - matched_sources),
        "unmapped_known_weights": sum(raw_values[key] is not None for key in set(raw_values) - matched_sources),
        "mismatches": mismatches,
        "note": "Source blanks remain unknown. Unmapped raw rows are not evidence of absent holdings.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    result = audit(parser.parse_args().workspace_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["mismatches"] else 0)
