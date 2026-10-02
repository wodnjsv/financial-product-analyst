"""Replay saved local search answers without API calls or modifying inputs."""

import argparse
import json
from pathlib import Path

from financial_agent.release.local_search_validation import validate_local_search_answer
from financial_agent.release.local_document_quotes import render_document_answer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", nargs="+", type=Path)
    parser.add_argument(
        "--render-document-quotes", action="store_true",
        help="Explicitly render a distinct source-only derivative from saved citation IDs; preserve original prose and verdict",
    )
    args = parser.parse_args()
    results = []
    for path in args.records:
        record = json.loads(path.read_text())
        errors = validate_local_search_answer(
            record.get("plan", {}).get("plan_id"),
            record.get("search", {}).get("rows"),
            record.get("answer"),
        )
        result = {
            "question_id": record.get("question_id"),
            "contract_passed": not errors,
            "errors": errors,
            "scope": "local raw output contract and source-owned document body; production truth and extraction quality are unverified",
        }
        if args.render_document_quotes and record.get("plan", {}).get("plan_id") == "document_risk":
            original = record.get("answer")
            draft = (
                {"citations": original.get("citations")}
                if isinstance(original, dict) else None
            )
            try:
                result["server_rendered_answer"] = render_document_answer(
                    record.get("search", {}).get("rows"), draft,
                )
                result["server_render_contract_passed"] = True
            except ValueError as exc:
                result["server_render_contract_passed"] = False
                result["server_render_errors"] = str(exc).split(",")
            result["replay_note"] = (
                "Explicit prose removed; distinct source-only derivative from saved citation IDs. "
                "Original answer file and original verdict preserved. No new model call."
            )
        results.append(result)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any(not result["contract_passed"] for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
