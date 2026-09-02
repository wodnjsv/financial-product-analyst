"""Strict local operator interface for DART embedding builds."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Sequence

from sqlalchemy.exc import SQLAlchemyError

from financial_agent.db.config import DatabaseConfig, DatabaseConfigurationError
from financial_agent.db.engine import create_database_engine
from financial_agent.embeddings.builder import (
    EmbeddingBuildError,
    EmbeddingBuildService,
    RetrievalValidationCase,
)
from financial_agent.embeddings.contracts import APPROVED_MODEL
from financial_agent.embeddings.ncp import (
    EmbeddingProviderError,
    NcpEmbeddingClient,
)
from financial_agent.embeddings.repository import (
    EmbeddingRepository,
    EmbeddingRepositoryError,
)
from financial_agent.documents import SectionType
from financial_agent.retrieval.documents import DocumentCandidateRepository


class EmbeddingConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class EmbeddingConfiguration:
    command: str
    database_url: str
    dataset_version: str
    api_key: str
    report_path: Path
    expected_chunks: int | None
    product_name: str | None
    limit: int | None
    batch_size: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="financial-agent-embeddings")
    commands = parser.add_subparsers(dest="command", required=True)

    def expected(command: str) -> argparse.ArgumentParser:
        child = commands.add_parser(command)
        child.add_argument("--expected-chunks", type=int, default=37_629)
        return child

    expected("preflight")
    expected("canary")
    candidates = commands.add_parser("sample-candidates")
    candidates.add_argument("--limit", type=int, default=10)
    sample = expected("sample")
    sample.add_argument("--product-name", required=True)
    sample.add_argument("--limit", type=int, default=20)
    verify = commands.add_parser("verify")
    verify.add_argument("--product-name", required=True)
    full = expected("full")
    full.add_argument("--batch-size", type=int, default=25)
    expected("reconcile")
    return parser.parse_args(argv)


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def read_ncp_api_key(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        raise EmbeddingConfigurationError("ncp_api_key_invalid") from None
    matches: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if re.sub(r"[^A-Z0-9]", "", name.upper()) != "NCPCLOVASTUDIOAPI":
            continue
        secret = _strip_matching_quotes(value.strip())
        if secret:
            matches.append(secret)
    if len(matches) != 1:
        raise EmbeddingConfigurationError("ncp_api_key_invalid")
    return matches[0]


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise EmbeddingConfigurationError(f"{name.lower()}_required")
    return value.strip()


def load_configuration(arguments: argparse.Namespace) -> EmbeddingConfiguration:
    key_path = Path(_required_environment("FINANCIAL_AGENT_NCP_API_KEY_FILE"))
    report_path = Path(_required_environment("FINANCIAL_AGENT_EMBEDDING_REPORT"))
    repository_root = Path(__file__).resolve().parents[3]
    try:
        report_path.resolve(strict=False).relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise EmbeddingConfigurationError("report_path_inside_repository")
    if not report_path.parent.is_dir() or report_path.parent.is_symlink():
        raise EmbeddingConfigurationError("report_parent_invalid")
    expected_chunks = getattr(arguments, "expected_chunks", None)
    limit = getattr(arguments, "limit", None)
    batch_size = getattr(arguments, "batch_size", 25)
    if expected_chunks is not None and expected_chunks < 1:
        raise EmbeddingConfigurationError("expected_chunks_invalid")
    if limit is not None and not 1 <= limit <= 100:
        raise EmbeddingConfigurationError("limit_invalid")
    if not 1 <= batch_size <= 100:
        raise EmbeddingConfigurationError("batch_size_invalid")
    return EmbeddingConfiguration(
        command=arguments.command,
        database_url=_required_environment("FINANCIAL_AGENT_BUILD_DATABASE_URL"),
        dataset_version=_required_environment("FINANCIAL_AGENT_DATASET_VERSION"),
        api_key=read_ncp_api_key(key_path),
        report_path=report_path,
        expected_chunks=expected_chunks,
        product_name=getattr(arguments, "product_name", None),
        limit=limit,
        batch_size=batch_size,
    )


_SENSITIVE_REPORT_KEYS = {
    "api_key",
    "database_url",
    "embedding",
    "chunk_text",
    "query_text",
    "request_id",
    "product_name",
    "entity_id",
    "local_path",
}


def _assert_report_safe(value: object) -> None:
    if isinstance(value, dict):
        if _SENSITIVE_REPORT_KEYS.intersection(value):
            raise EmbeddingConfigurationError("report_sensitive_field")
        for item in value.values():
            _assert_report_safe(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_report_safe(item)


def write_report(report: dict[str, object], destination: Path) -> str:
    _assert_report_safe(report)
    payload = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".embedding-report-",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


async def run_command(configuration: EmbeddingConfiguration) -> int:
    engine = create_database_engine(DatabaseConfig(url=configuration.database_url))
    repository = EmbeddingRepository(engine)
    provider = NcpEmbeddingClient(configuration.api_key)
    service = EmbeddingBuildService(
        repository,
        provider,
        batch_size=configuration.batch_size,
    )
    try:
        if configuration.command == "preflight":
            result = await repository.preflight(
                configuration.dataset_version,
                APPROVED_MODEL,
            )
            if result.eligible_chunk_count != configuration.expected_chunks:
                raise EmbeddingBuildError("eligible_chunk_count_mismatch")
            report = {"stage": "preflight", **asdict(result)}
        elif configuration.command == "canary":
            result = await service.embed_canary(
                configuration.dataset_version,
                expected_chunk_count=configuration.expected_chunks or 0,
            )
            report = asdict(result)
        elif configuration.command == "sample-candidates":
            candidates = await repository.sample_candidates(
                configuration.dataset_version,
                limit=configuration.limit or 10,
            )
            for candidate in candidates:
                print(
                    f"{candidate.canonical_product_name}\t"
                    f"strategy={candidate.strategy_chunk_count}\t"
                    f"risk={candidate.risk_chunk_count}"
                )
            report = {"stage": "sample_candidates", "candidate_count": len(candidates)}
        elif configuration.command == "sample":
            result = await service.embed_sample(
                configuration.dataset_version,
                expected_chunk_count=configuration.expected_chunks or 0,
                canonical_product_name=configuration.product_name or "",
                limit=configuration.limit or 20,
            )
            report = asdict(result)
        elif configuration.command == "verify":
            product_name = configuration.product_name or ""
            cases = (
                RetrievalValidationCase(
                    "risk",
                    configuration.dataset_version,
                    product_name,
                    "주요 투자위험과 원금 손실 가능성",
                    "product_risk_factor",
                    (SectionType.INVESTMENT_STRATEGY, SectionType.RISK_FACTOR),
                    SectionType.RISK_FACTOR,
                ),
                RetrievalValidationCase(
                    "strategy",
                    configuration.dataset_version,
                    product_name,
                    "투자목적과 구체적인 운용전략",
                    "product_investment_strategy",
                    (SectionType.INVESTMENT_STRATEGY, SectionType.RISK_FACTOR),
                    SectionType.INVESTMENT_STRATEGY,
                ),
            )
            result = await service.verify_retrieval(
                cases,
                DocumentCandidateRepository(engine),
            )
            report = {"stage": "verify", **asdict(result)}
        elif configuration.command == "full":
            result = await service.embed_all(
                configuration.dataset_version,
                expected_chunk_count=configuration.expected_chunks or 0,
            )
            report = asdict(result)
        else:
            result = await repository.reconcile(
                configuration.dataset_version,
                APPROVED_MODEL,
            )
            if (
                result.eligible_count != configuration.expected_chunks
                or result.exact_count != configuration.expected_chunks
                or any(
                    (
                        result.missing_count,
                        result.duplicate_count,
                        result.stale_count,
                        result.orphan_count,
                        result.wrong_dimension_count,
                    )
                )
            ):
                raise EmbeddingBuildError("reconciliation_failed")
            report = {"stage": "reconcile", **asdict(result)}
        report_hash = write_report(report, configuration.report_path)
        print(f"EMBEDDING_{configuration.command.upper().replace('-', '_')}_OK report_hash={report_hash}")
        return 0
    finally:
        await engine.dispose()


_KNOWN_ERRORS = (
    EmbeddingConfigurationError,
    EmbeddingBuildError,
    EmbeddingProviderError,
    EmbeddingRepositoryError,
    DatabaseConfigurationError,
)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(run_command(load_configuration(parse_args(argv))))
    except _KNOWN_ERRORS as error:
        print(getattr(error, "code", "EMBEDDING_FAILED"), file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("DATABASE_UNREACHABLE", file=sys.stderr)
        return 2
    except Exception:
        print("EMBEDDING_FAILED", file=sys.stderr)
        return 2
