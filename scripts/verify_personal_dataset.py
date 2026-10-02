"""Read-only acceptance of the personal local SQL dataset."""

import argparse
import json
from pathlib import Path
import shutil

import psycopg
from psycopg.rows import dict_row

from financial_agent.ingestion.local_budget import StorageBudget, require_local_target
from financial_agent.ingestion.pipeline import SOURCE_SPECS


DATASET = "personal-2026-08-24-v1"


def verify(root: Path, url: str):
    require_local_target(url)
    output = root / "data/personal-local"
    report = json.loads((output / "structured-report.json").read_text())
    for source, spec in SOURCE_SPECS.items():
        assert report["source_counts"][source]["rows"] == spec.expected_row_count
    assert report["passed"]
    with psycopg.connect(url, row_factory=dict_row,
                        options="-c default_transaction_read_only=on -c role=fa_runtime") as c:
        family_counts = c.execute("""SELECT product_family,count(*) AS count
            FROM catalog.product WHERE dataset_version=%s
            GROUP BY product_family ORDER BY product_family""", (DATASET,)).fetchall()
        assert len(family_counts) == 4 and all(r["count"] > 0 for r in family_counts)
        holdings = c.execute("""SELECT p.product_family,count(DISTINCT r.subject_id) AS products,
            count(*) AS relations FROM relation.relation_record r
            JOIN catalog.product p ON p.dataset_version=r.dataset_version AND p.entity_id=r.subject_id
            WHERE r.dataset_version=%s AND r.predicate_id='holdsSecurity'
            GROUP BY p.product_family ORDER BY p.product_family""", (DATASET,)).fetchall()
        assert {r["product_family"] for r in holdings} == {"domestic_etf", "overseas_etf"}
        assert all(0 < r["products"] <= 50 for r in holdings)
        documents = c.execute("SELECT count(*) AS count FROM document.document_record WHERE dataset_version=%s", (DATASET,)).fetchone()["count"]
        assert documents == 100
        vector_counts = c.execute("""SELECT count(*) AS embeddings,
            count(*) FILTER (WHERE ch.chunk_id IS NULL OR v.dimension<>1024
                OR cdb_admin.vector_dims(v.embedding)<>1024) AS anomalies
            FROM search.document_embedding v
            LEFT JOIN document.document_chunk ch ON ch.dataset_version=v.dataset_version
                AND ch.document_id=v.document_id AND ch.chunk_id=v.chunk_id
                AND ch.content_hash=v.chunk_content_hash
            WHERE v.dataset_version=%s""", (DATASET,)).fetchone()
        chunks = c.execute("SELECT count(*) AS count FROM document.document_chunk WHERE dataset_version=%s", (DATASET,)).fetchone()["count"]
        assert vector_counts["anomalies"] == 0 and vector_counts["embeddings"] == chunks > 0
        unsupported_holdings = c.execute("""SELECT count(*) AS count FROM relation.relation_record r
            WHERE r.dataset_version=%s AND r.predicate_id='holdsSecurity'
            AND NOT EXISTS (SELECT 1 FROM evidence.evidence_relation_origin er
                WHERE er.dataset_version=r.dataset_version AND er.relation_id=r.relation_id)""", (DATASET,)).fetchone()["count"]
        assert unsupported_holdings == 0
        missing_observations = c.execute("""SELECT count(*) AS count FROM observation.observation_record o
            WHERE o.dataset_version=%s AND NOT EXISTS (
                SELECT 1 FROM evidence.evidence_observation_origin e
                WHERE e.dataset_version=o.dataset_version AND e.observation_id=o.observation_id)""", (DATASET,)).fetchone()["count"]
        assert missing_observations == 0
        state = c.execute("SELECT status FROM operations.dataset_version WHERE dataset_version=%s", (DATASET,)).fetchone()["status"]
        assert state == "building"
        # Migrations create a singleton row with a NULL pointer before activation.
        assert c.execute("""SELECT count(*) AS count FROM operations.active_dataset
            WHERE dataset_version IS NOT NULL OR activated_at IS NOT NULL""").fetchone()["count"] == 0
        size = c.execute("SELECT pg_database_size(current_database()) AS size").fetchone()["size"]
        counts = c.execute("""SELECT (SELECT count(*) FROM observation.observation_record WHERE dataset_version=%s) AS observations,
            (SELECT count(*) FROM evidence.evidence_record WHERE dataset_version=%s) AS evidence,
            (SELECT count(*) FROM relation.relation_record WHERE dataset_version=%s) AS relations""", (DATASET, DATASET, DATASET)).fetchone()
    free = shutil.disk_usage(root).free
    budget = StorageBudget(**json.loads((output / "budget.json").read_text()))
    budget.check(size, free)
    result = {"passed": True, "dataset_version": DATASET, "state": state,
        "family_counts": family_counts, "holdings": holdings,
        "documents": documents, "chunks": chunks, **vector_counts, **counts,
        "unsupported_holding_relations": unsupported_holdings,
        "observations_without_evidence": missing_observations,
        "database_bytes": size, "free_bytes": free,
        "disk_growth_bytes": budget.initial_free_bytes-free}
    (output / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--database-url", default="postgresql://localhost/financial_agent_local")
    args = parser.parse_args()
    verify(args.workspace_root.resolve(), args.database_url)
