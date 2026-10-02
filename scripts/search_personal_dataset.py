"""Query local PostgreSQL and print server-owned results, without LLM calls."""

import argparse

from financial_agent.retrieval.personal_search import search_personal_dataset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", choices=("rank_return", "holding_weight", "document_risk"), required=True)
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    print(search_personal_dataset(args.plan, args.keyword, args.limit)["answer"])
