"""Resolve and route a natural-language question without executing product queries."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Sequence

from pydantic import SecretStr
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.intent.nvidia_config import NvidiaResolverConfig
from financial_agent.intent.personal_runtime import create_personal_intent_service


class PersonalIntentCliError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def load_nvidia_config(key_file: Path | None) -> NvidiaResolverConfig:
    """Read an explicitly provided local file; never copy credentials into env."""
    if key_file is None:
        return NvidiaResolverConfig.from_env()
    try:
        text = key_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise PersonalIntentCliError("API_KEY_FILE_INVALID") from None
    keys = re.findall(
        r"^[ \t]*Nvidia[ \t]+API[ \t]*=[ \t]*(\S+)[ \t]*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if len(keys) != 1:
        raise PersonalIntentCliError("API_KEY_FILE_INVALID")
    return NvidiaResolverConfig(
        api_key=SecretStr(keys[0]),
        model_id=os.environ.get("FINANCIAL_AGENT_INTENT_MODEL_ID", "z-ai/glm-5.3-flash"),
    )


def local_database_url(value: str) -> URL:
    try:
        target = make_url(value)
        valid = (
            target.drivername in ("postgresql", "postgresql+psycopg")
            and target.host in ("localhost", "127.0.0.1", "::1")
            and target.database == "financial_agent_local"
            and not target.query
            and (target.port is None or 0 < target.port <= 65_535)
        )
    except (TypeError, ValueError, ArgumentError):
        valid = False
    if not valid:
        raise PersonalIntentCliError("LOCAL_DATABASE_TARGET_REQUIRED")
    return target.set(drivername="postgresql+psycopg")


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
