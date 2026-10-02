"""Render saved local query results with server-owned missingness and sources."""

import argparse
import json
from pathlib import Path

from financial_agent.release.local_search_display import render_local_search_results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.records:
        record = json.loads(path.read_text())
        result = render_local_search_results(record["plan"]["plan_id"], record["search"])
        print(f"{record.get('question_id', '')}: {record.get('question', '')}")
        print("서버 생성 조회 결과 — 저장된 모델 답변은 사용하지 않음")
        print(result["answer"])
        print()


if __name__ == "__main__":
    main()
