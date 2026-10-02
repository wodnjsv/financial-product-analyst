"""Resolve and route a natural-language question without executing product queries."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Sequence

from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.intent.personal_cli import PersonalIntentCliError, load_nvidia_config, local_database_url
from financial_agent.intent.personal_runtime import create_personal_intent_service


async def _resolve(args: argparse.Namespace) -> dict[str, object]:
    config = load_nvidia_config(args.api_key_file)
    target = local_database_url(args.database_url)
    engine = create_async_engine(
        target,
        pool_size=2,
        max_overflow=0,
        connect_args={
            "options": (
                "-c role=fa_runtime -c default_transaction_read_only=on "
                "-c statement_timeout=5000 -c timezone=UTC"
            ),
            "connect_timeout": 5,
        },
    )
    try:
        service = await create_personal_intent_service(
            Path(__file__).resolve().parents[1], engine, config,
        )
        result = await service.resolve(args.question, question_id=args.question_id)
        return result.to_dict()
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--question-id", default="local-intent")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--database-url", default="postgresql+psycopg://localhost/financial_agent_local")
    args = parser.parse_args(argv)
    try:
        output = asyncio.run(_resolve(args))
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except Exception as error:
        code = getattr(error, "code", "PERSONAL_INTENT_FAILED")
        if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code) is None:
            code = "PERSONAL_INTENT_FAILED"
        print(json.dumps({"error": code, "execution_performed": False}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
