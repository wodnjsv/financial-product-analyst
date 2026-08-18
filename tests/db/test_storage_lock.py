from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[2]
STORAGE_LOCK = ROOT / "requirements" / "storage.lock"
CONTRACTS_LOCK = ROOT / "requirements" / "contracts.lock"
PYPROJECT = ROOT / "pyproject.toml"

FROZEN_CONTRACTS_LOCK_SHA256 = (
    "7598aa70bded36c41dad9dcfd0962fa52cc5eb66f0aca781ab30101dd6017525"
)

REQUIRED_STORAGE_PACKAGES = {
    "alembic",
    "greenlet",
    "pgvector",
    "psycopg",
    "psycopg-binary",
    "pytest-asyncio",
    "sqlalchemy",
}


def _locked_requirements() -> tuple[Requirement, ...]:
    return tuple(
        Requirement(line)
        for line in STORAGE_LOCK.read_text("utf-8").splitlines()
        if line and not line.startswith("#")
    )


def test_stage_01_contract_lock_remains_frozen() -> None:
    assert hashlib.sha256(CONTRACTS_LOCK.read_bytes()).hexdigest() == (
        FROZEN_CONTRACTS_LOCK_SHA256
    )


def test_storage_lock_contains_only_exact_registry_pins() -> None:
    requirements = _locked_requirements()

    assert requirements
    assert all(requirement.url is None for requirement in requirements)
    assert all(
        len(requirement.specifier) == 1
        and next(iter(requirement.specifier)).operator == "=="
        for requirement in requirements
    )


def test_storage_lock_contains_the_database_runtime_and_test_toolchain() -> None:
    locked_names = {
        canonicalize_name(requirement.name)
        for requirement in _locked_requirements()
    }

    assert REQUIRED_STORAGE_PACKAGES <= locked_names


def test_pyproject_declares_the_bounded_stage_02_dependencies() -> None:
    project = tomllib.loads(PYPROJECT.read_text("utf-8"))["project"]
    storage_declared = {
        canonicalize_name(requirement.name): str(requirement.specifier)
        for requirement in map(
            Requirement,
            project["optional-dependencies"]["storage"],
        )
    }
    assert storage_declared["sqlalchemy"] == "<3,>=2.0"
    assert storage_declared["alembic"] == "<2,>=1.13"
    assert storage_declared["psycopg"] == "<4,>=3.2"
    assert storage_declared["pgvector"] == "<1,>=0.3"
    assert storage_declared["pytest-asyncio"] == "<1,>=0.24"


def test_stage_02_dependencies_do_not_expand_the_frozen_contract_groups() -> None:
    project = tomllib.loads(PYPROJECT.read_text("utf-8"))["project"]

    assert project["dependencies"] == ["pydantic>=2.10,<3"]
    assert project["optional-dependencies"]["dev"] == [
        "jsonschema>=4.23,<5",
        "pytest>=8,<9",
    ]
