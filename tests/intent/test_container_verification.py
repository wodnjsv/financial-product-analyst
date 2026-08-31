from __future__ import annotations

from collections.abc import Callable
from fnmatch import fnmatch
import json
from pathlib import Path, PurePosixPath
import shlex
from typing import Any

import pytest

from financial_agent.intent.evaluation import (
    CountMetric,
    CoverageMetric,
    PromotionEvidence,
    assess_promotion,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = PROJECT_ROOT / "docker" / "resolver-check.Dockerfile"
COMPOSE = PROJECT_ROOT / "docker" / "postgres.compose.yml"
DOCKERIGNORE = PROJECT_ROOT / ".dockerignore"

APPROVED_COPY_SOURCES = {
    ".dockerignore",
    "alembic.ini",
    "alembic/",
    "config/intent/",
    "docker/initdb/001-ncp-extension-layout.sql",
    "docker/postgres.compose.yml",
    "docker/resolver-check.Dockerfile",
    "ontology/",
    "pyproject.toml",
    "requirements/resolver.lock",
    "schemas/",
    "scripts/",
    "src/",
    "tests/",
}

PROMOTION_GATE_NAMES = (
    "unknown_registered_id_acceptance",
    "invalid_context_graph_acceptance",
    "deterministic_candidate_reproducibility",
    "candidate_recall_at_5",
    "first_pass_structured_output_validity",
    "held_out_joint_frame_exact_match",
    "held_out_context_link_exact_match",
    "ood_false_fast_rate",
)


def _logical_dockerfile_lines(source: str) -> tuple[str, ...]:
    logical: list[str] = []
    pending = ""
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical.append(pending)
        pending = ""
    assert not pending, "Dockerfile has an unterminated continuation"
    return tuple(logical)


def _dockerfile_instructions(source: str) -> tuple[tuple[str, str], ...]:
    instructions: list[tuple[str, str]] = []
    for line in _logical_dockerfile_lines(source):
        instruction, separator, argument = line.partition(" ")
        assert separator, f"Dockerfile instruction has no argument: {line}"
        instructions.append((instruction.upper(), argument.strip()))
    return tuple(instructions)


def _copy_sources(argument: str) -> tuple[str, ...]:
    if argument.startswith("["):
        values = json.loads(argument)
        assert isinstance(values, list) and len(values) >= 2
        return tuple(str(value) for value in values[:-1])
    tokens = tuple(
        token for token in shlex.split(argument) if not token.startswith("--")
    )
    assert len(tokens) >= 2
    return tokens[:-1]


def _cmd_shell_tokens(instructions: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    commands = [argument for instruction, argument in instructions if instruction == "CMD"]
    assert len(commands) == 1, "resolver verification image needs exactly one CMD"
    value = json.loads(commands[0])
    assert value[:2] == ["sh", "-c"] and len(value) == 3
    lexer = shlex.shlex(value[2], posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return tuple(lexer)


def _contains_sequence(tokens: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    width = len(expected)
    return any(tokens[index : index + width] == expected for index in range(len(tokens)))


def _assert_resolver_dockerfile_policy(source: str) -> None:
    instructions = _dockerfile_instructions(source)
    base_images = [
        tuple(shlex.split(argument))
        for instruction, argument in instructions
        if instruction == "FROM"
    ]
    assert len(base_images) == 1
    assert "--platform=linux/amd64" in base_images[0]

    copy_sources = {
        item
        for instruction, argument in instructions
        if instruction == "COPY"
        for item in _copy_sources(argument)
    }
    assert copy_sources == APPROVED_COPY_SOURCES
    assert "." not in copy_sources

    image_environment = {
        token.split("=", 1)[0]: token.split("=", 1)[1]
        for instruction, argument in instructions
        if instruction in {"ARG", "ENV"}
        for token in shlex.split(argument)
        if "=" in token
    }
    forbidden_fragments = ("CLOVA", "API_KEY", "MODEL_ID", "NCP")
    assert not {
        name
        for name in image_environment
        if any(fragment in name.upper() for fragment in forbidden_fragments)
    }
    assert image_environment["PIP_CONSTRAINT"] == "/app/requirements/resolver.lock"
    assert image_environment["FINANCIAL_AGENT_PROJECT_ROOT"] == "/app"

    build_steps = [
        tuple(shlex.split(argument))
        for instruction, argument in instructions
        if instruction == "RUN"
    ]
    assert any(
        _contains_sequence(
            step,
            ("python", "-m", "pip", "install", ".[dev,storage,graph,resolver]"),
        )
        for step in build_steps
    )

    tokens = _cmd_shell_tokens(instructions)
    assert _contains_sequence(
        tokens, ("python", "scripts/export_contract_schemas.py", "--check")
    )
    assert _contains_sequence(
        tokens, ("python", "scripts/export_intent_schemas.py", "--check")
    )
    assert _contains_sequence(
        tokens,
        (
            "python",
            "-m",
            "pytest",
            "tests/intent",
            "tests/evaluation/intent",
        ),
    )
    assert _contains_sequence(
        tokens, ("python", "scripts/verify_database_migrations.py")
    )
    assert _contains_sequence(
        tokens,
        (
            "python",
            "-m",
            "pytest",
            "tests/db/test_intent_entity_repository.py",
            "tests/db/test_artifact_repository.py",
        ),
    )
    assert any("FINANCIAL_AGENT_TEST_DATABASE_URL" in token for token in tokens)
    assert "not postgres and not clova_integration" in tokens
    assert _contains_sequence(
        tokens,
        (
            "python",
            "scripts/export_database_objects.py",
            "--check",
            "--database-url-env",
            "FINANCIAL_AGENT_TEST_DATABASE_URL",
        ),
    )
    assert "||" not in tokens
    assert "&" not in tokens


def _parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_mapping_only_yaml(source: str) -> dict[str, Any]:
    """Parse the mapping subset used by resolver-check's Compose block."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key, separator, value = stripped.partition(":")
        assert separator, f"unsupported Compose syntax: {raw_line}"
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if value.strip():
            parent[key] = _parse_scalar(value)
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
    return root


def _dockerignore_match(pattern: str, path: str) -> bool:
    normalized = pattern.lstrip("/")
    if normalized.endswith("/"):
        directory = normalized.rstrip("/")
        if directory.startswith("**/"):
            directory = directory[3:]
            parts = PurePosixPath(path).parts
            return directory in parts[:-1]
        return path == directory or path.startswith(f"{directory}/")
    if "/" not in normalized:
        return fnmatch(PurePosixPath(path).name, normalized)
    return fnmatch(path, normalized) or PurePosixPath(path).match(normalized)


def _dockerignore_excludes(source: str, path: str) -> bool:
    excluded = False
    for raw_line in source.splitlines():
        pattern = raw_line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:]
        if _dockerignore_match(pattern, path):
            excluded = not negated
    return excluded


def _passing_promotion_evidence() -> PromotionEvidence:
    return PromotionEvidence(
        unknown_registered_id_acceptance=CountMetric(numerator=0, denominator=10),
        invalid_context_graph_acceptance=CountMetric(numerator=0, denominator=10),
        validation_probe_coverage=CoverageMetric(numerator=20, denominator=20),
        deterministic_candidate_reproducibility=CountMetric(
            numerator=155, denominator=155
        ),
        deterministic_candidate_reproducibility_coverage=CoverageMetric(
            numerator=155, denominator=155
        ),
        candidate_recall_at_5=CountMetric(numerator=195, denominator=196),
        first_pass_structured_output_validity=CountMetric(
            numerator=159, denominator=160
        ),
        held_out_joint_frame_exact_match=CountMetric(
            numerator=144, denominator=160
        ),
        held_out_context_link_exact_match=CountMetric(
            numerator=152, denominator=160
        ),
        ood_false_fast_rate=CountMetric(numerator=1, denominator=50),
    )


def test_resolver_dockerfile_uses_a_bounded_non_live_verification_chain() -> None:
    assert DOCKERFILE.is_file(), "resolver verification Dockerfile is missing"
    _assert_resolver_dockerfile_policy(DOCKERFILE.read_text("utf-8"))


def test_dockerfile_policy_rejects_broad_copy_and_short_circuit_success() -> None:
    unsafe = """
FROM python:3.12-slim
COPY . /app
CMD ["sh", "-c", "python scripts/export_intent_schemas.py --check || true"]
"""
    with pytest.raises(AssertionError):
        _assert_resolver_dockerfile_policy(unsafe)


@pytest.mark.parametrize(
    "unsafe_source",
    (
        lambda source: source.replace("--platform=linux/amd64", "--platform=linux/arm64"),
        lambda source: source.replace(
            "PIP_CONSTRAINT=/app/requirements/resolver.lock", "PIP_CONSTRAINT=/tmp/other.lock"
        ),
        lambda source: source.replace(
            'RUN python -m pip install ".[dev,storage,graph,resolver]"',
            "RUN true",
        ),
        lambda source: source.replace("not postgres and not clova_integration", "not postgres"),
        lambda source: source.replace(
            "python scripts/export_database_objects.py --check --database-url-env FINANCIAL_AGENT_TEST_DATABASE_URL",
            "true",
        ),
    ),
)
def test_dockerfile_policy_rejects_wrong_runtime_or_incomplete_gates(
    unsafe_source: Callable[[str], str],
) -> None:
    source = DOCKERFILE.read_text("utf-8")

    with pytest.raises(AssertionError):
        _assert_resolver_dockerfile_policy(unsafe_source(source))


def test_resolver_compose_service_is_disposable_and_has_no_live_model_surface() -> None:
    compose = _parse_mapping_only_yaml(COMPOSE.read_text("utf-8"))
    services = compose["services"]
    assert set(services) == {"postgres", "db-check", "resolver-check"}

    resolver = services["resolver-check"]
    assert resolver["platform"] == "linux/amd64"
    assert resolver["build"] == {
        "context": "..",
        "dockerfile": "docker/resolver-check.Dockerfile",
    }
    assert resolver["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert resolver["environment"] == {
        "FINANCIAL_AGENT_COMPOSE_DATABASE_CHECK": "1",
        "FINANCIAL_AGENT_TEST_DATABASE_URL": (
            "postgresql+psycopg://financial_agent_test:financial_agent_test@"
            "postgres:5432/financial_agent_test"
        ),
    }
    assert "command" not in resolver
    assert "restart" not in resolver


def test_dockerignore_excludes_sensitive_and_generated_inputs() -> None:
    source = DOCKERIGNORE.read_text("utf-8")
    excluded_paths = (
        ".env",
        ".env.local",
        "config/.env",
        ".git/config",
        "data/organizer/master.xlsx",
        "docs/organizer-brief.pdf",
        "build/reports/intent-resolver-live.json",
        "raw_responses/provider.json",
        "local/state.db",
        "local/facts.parquet",
        "indexes/catalog.index",
        "vector_store/intent.faiss",
        "model_cache/resolver/model.safetensors",
        "credentials/provider-token.txt",
        "output/graph.nq",
    )
    assert all(_dockerignore_excludes(source, path) for path in excluded_paths)

    approved_paths = (
        "requirements/resolver.lock",
        "config/intent/semantic-catalog.json",
        "ontology/financial-products.ttl",
        "schemas/intent/intent-resolution.schema.json",
        "src/financial_agent/intent/evaluation.py",
        "tests/evaluation/intent/intent_resolution_heldout_ko_v3.json",
    )
    assert not any(_dockerignore_excludes(source, path) for path in approved_paths)


def test_promotion_requires_every_gate_to_be_measured_and_passing() -> None:
    decision = assess_promotion(_passing_promotion_evidence())

    assert decision.eligible is True
    assert decision.blocking_gate_names == ()
    assert tuple(gate.name for gate in decision.gates) == PROMOTION_GATE_NAMES
    assert {gate.status for gate in decision.gates} == {"passed"}


def test_promotion_blocks_failed_candidate_recall_and_unmeasured_live_metrics() -> None:
    evidence = PromotionEvidence(
        deterministic_candidate_reproducibility=CountMetric(
            numerator=155, denominator=155
        ),
        deterministic_candidate_reproducibility_coverage=CoverageMetric(
            numerator=155, denominator=155
        ),
        candidate_recall_at_5=CountMetric(numerator=118, denominator=196),
    )

    decision = assess_promotion(evidence)
    statuses = {gate.name: gate.status for gate in decision.gates}

    assert decision.eligible is False
    assert decision.blocking_gate_names == (
        "unknown_registered_id_acceptance",
        "invalid_context_graph_acceptance",
        "candidate_recall_at_5",
        "first_pass_structured_output_validity",
        "held_out_joint_frame_exact_match",
        "held_out_context_link_exact_match",
        "ood_false_fast_rate",
    )
    assert statuses["deterministic_candidate_reproducibility"] == "passed"
    assert statuses["candidate_recall_at_5"] == "failed"
    assert statuses["first_pass_structured_output_validity"] == "unmeasured"


def test_promotion_does_not_treat_zero_denominators_as_passing() -> None:
    zero = CountMetric(numerator=0, denominator=0)
    no_coverage = CoverageMetric(numerator=0, denominator=0)
    evidence = PromotionEvidence(
        unknown_registered_id_acceptance=zero,
        invalid_context_graph_acceptance=zero,
        validation_probe_coverage=no_coverage,
        deterministic_candidate_reproducibility=zero,
        deterministic_candidate_reproducibility_coverage=no_coverage,
        candidate_recall_at_5=zero,
        first_pass_structured_output_validity=zero,
        held_out_joint_frame_exact_match=zero,
        held_out_context_link_exact_match=zero,
        ood_false_fast_rate=zero,
    )

    decision = assess_promotion(evidence)

    assert decision.eligible is False
    assert decision.blocking_gate_names == PROMOTION_GATE_NAMES
    assert {gate.status for gate in decision.gates} == {"unmeasured"}


@pytest.mark.parametrize(
    ("field_name", "numerator", "denominator"),
    (
        ("candidate_recall_at_5", 194, 196),
        ("first_pass_structured_output_validity", 158, 160),
        ("held_out_joint_frame_exact_match", 143, 160),
        ("held_out_context_link_exact_match", 151, 160),
        ("ood_false_fast_rate", 1, 49),
    ),
)
def test_promotion_thresholds_fail_on_the_wrong_side_of_the_boundary(
    field_name: str,
    numerator: int,
    denominator: int,
) -> None:
    evidence = _passing_promotion_evidence().model_copy(
        update={field_name: CountMetric(numerator=numerator, denominator=denominator)}
    )
    evidence = PromotionEvidence.model_validate(evidence)

    decision = assess_promotion(evidence)

    assert decision.eligible is False
    assert decision.blocking_gate_names == (field_name,)
    assert next(gate for gate in decision.gates if gate.name == field_name).status == "failed"


def test_incomplete_supporting_coverage_keeps_dependent_gates_unmeasured() -> None:
    evidence = _passing_promotion_evidence().model_copy(
        update={
            "validation_probe_coverage": CoverageMetric(
                numerator=19, denominator=20
            ),
            "deterministic_candidate_reproducibility_coverage": CoverageMetric(
                numerator=154, denominator=155
            ),
        }
    )
    evidence = PromotionEvidence.model_validate(evidence)

    decision = assess_promotion(evidence)
    statuses = {gate.name: gate.status for gate in decision.gates}

    assert decision.eligible is False
    assert statuses["unknown_registered_id_acceptance"] == "unmeasured"
    assert statuses["invalid_context_graph_acceptance"] == "unmeasured"
    assert statuses["deterministic_candidate_reproducibility"] == "unmeasured"


def test_supporting_coverage_must_match_the_measured_gate_denominators() -> None:
    evidence = _passing_promotion_evidence().model_copy(
        update={
            "unknown_registered_id_acceptance": CountMetric(
                numerator=0, denominator=1
            ),
            "invalid_context_graph_acceptance": CountMetric(
                numerator=0, denominator=1
            ),
            "deterministic_candidate_reproducibility": CountMetric(
                numerator=1, denominator=1
            ),
        }
    )
    evidence = PromotionEvidence.model_validate(evidence)

    decision = assess_promotion(evidence)
    statuses = {gate.name: gate.status for gate in decision.gates}

    assert statuses["unknown_registered_id_acceptance"] == "unmeasured"
    assert statuses["invalid_context_graph_acceptance"] == "unmeasured"
    assert statuses["deterministic_candidate_reproducibility"] == "unmeasured"
