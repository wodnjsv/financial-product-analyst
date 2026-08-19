from __future__ import annotations

import re
import tomllib
from importlib.metadata import distribution
from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[2]
LOCK_FILE = ROOT / "requirements" / "contracts.lock"
DOCKERFILE = ROOT / "docker" / "contracts.Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"


def _normalized_name(requirement: str) -> str:
    name = re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in LOCK_FILE.read_text("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[^=\s]+", line), line
        entries[_normalized_name(line)] = line
    return entries


def _installed_dependency_graph(root_names: set[str]) -> set[str]:
    discovered: set[str] = set()
    pending = list(root_names)
    while pending:
        name = pending.pop()
        if name in discovered:
            continue
        discovered.add(name)
        for raw_requirement in distribution(name).requires or ():
            requirement = Requirement(raw_requirement)
            if requirement.marker is not None and not requirement.marker.evaluate(
                {"extra": ""}
            ):
                continue
            dependency_name = _normalized_name(requirement.name)
            if dependency_name not in discovered:
                pending.append(dependency_name)
    return discovered


def test_contract_dependencies_have_exact_verification_pins() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    declared = [
        *project["dependencies"],
        *project["optional-dependencies"]["dev"],
    ]

    root_names = {_normalized_name(requirement) for requirement in declared}
    locked = _lock_entries()

    assert _installed_dependency_graph(root_names) <= locked.keys()


def test_contracts_image_installs_with_the_verification_lock() -> None:
    dockerfile = DOCKERFILE.read_text("utf-8")

    assert "PIP_CONSTRAINT=/app/requirements/contracts.lock" in dockerfile
    assert "COPY requirements/contracts.lock ./requirements/contracts.lock" in dockerfile


def test_docker_context_policy_covers_protected_local_artifacts() -> None:
    patterns = {
        line.strip()
        for line in DOCKERIGNORE.read_text("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        ".git/",
        ".gstack/",
        ".agents/",
        ".codex/",
        ".env",
        ".env.*",
        "data/",
        "*.key",
        "*.pem",
        "*.db",
        "*.parquet",
        ".venv/",
        "__pycache__/",
        ".pytest_cache/",
        "*.log",
        "outputs/",
    } <= patterns
