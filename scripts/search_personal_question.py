"""Resolve a question with NVIDIA and print verified local PostgreSQL results."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
from typing import Sequence

from sqlalchemy.ext.asyncio import create_async_engine

from financial_agent.intent.personal_runtime import create_personal_intent_service
from financial_agent.intent.personal_search import create_personal_search
from financial_agent.intent.personal_cli import load_nvidia_config, local_database_url


async def _search(args):
    config = load_nvidia_config(args.api_key_file)
    engine = create_async_engine(
        local_database_url(args.database_url), pool_size=2, max_overflow=0,
        connect_args={'options': '-c role=fa_runtime -c default_transaction_read_only=on -c statement_timeout=5000 -c timezone=UTC',
                      'connect_timeout': 5},
    )
    try:
        root = Path(__file__).resolve().parents[1]
        intent = await create_personal_intent_service(root, engine, config)
        result = await create_personal_search(intent, root, engine).search(
            args.question, args.question_id, args.display_limit,
        )
        return result.text
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question', required=True)
    parser.add_argument('--question-id', default='local-search')
    parser.add_argument('--api-key-file', type=Path)
    parser.add_argument('--database-url', default='postgresql+psycopg://localhost/financial_agent_local')
    parser.add_argument('--display-limit', type=int, default=5)
    args = parser.parse_args(argv)
    try:
        print(asyncio.run(_search(args)))
    except Exception as error:
        code = getattr(error, 'code', 'PERSONAL_SEARCH_FAILED')
        if not isinstance(code, str) or re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}', code) is None:
            code = 'PERSONAL_SEARCH_FAILED'
        print(f'실행 실패: {code}')
        if code == 'SQL_RESULT_ROW_LIMIT_EXCEEDED':
            print('조회 결과가 로컬 한도 10,000건을 초과했습니다. 상품명·날짜·조건으로 범위를 좁혀 주세요.')
        elif code == 'PERSONAL_SQL_TIMEOUT':
            print('읽기 전용 조회 시간 한도를 초과했습니다. 상품명·날짜·조건으로 범위를 좁혀 주세요.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
