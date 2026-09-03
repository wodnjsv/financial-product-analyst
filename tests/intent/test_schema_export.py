from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Literal

import pytest

from financial_agent.intent.schema_export import check_schemas, export_schemas


def test_v2_schema_export_generates_the_complete_v2_contract_bundle(
    tmp_path: Path,
) -> None:
    export_schemas(tmp_path, schema_version="2.0")

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "intent-resolution-draft.schema.json",
        "intent-resolution-proposal.schema.json",
        "resolver-build-manifest.schema.json",
        "validated-intent-resolution.schema.json",
    ]
    check_schemas(tmp_path, schema_version="2.0")


@pytest.mark.parametrize("unexpected_name", ["extra.schema.json", "missing"])
def test_v2_schema_check_rejects_extra_missing_or_changed_contract_files(
    tmp_path: Path,
    unexpected_name: str,
) -> None:
    export_schemas(tmp_path, schema_version="2.0")
    target = tmp_path / "intent-resolution-proposal.schema.json"
    if unexpected_name == "missing":
        target.unlink()
    else:
        (tmp_path / unexpected_name).write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="do not match"):
        check_schemas(tmp_path, schema_version="2.0")


def test_v2_schema_check_rejects_byte_drift(tmp_path: Path) -> None:
    export_schemas(tmp_path, schema_version="2.0")
    target = tmp_path / "intent-resolution-proposal.schema.json"
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(ValueError, match="do not match"):
        check_schemas(tmp_path, schema_version="2.0")


def test_v1_schema_files_are_preserved() -> None:
    project_root = Path(__file__).resolve().parents[2]

    check_schemas(project_root / "schemas/intent/v1")


def test_committed_v1_schema_files_retain_their_historical_bytes() -> None:
    project_root = Path(__file__).resolve().parents[2]
    schema_dir = project_root / "schemas/intent/v1"

    assert {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in schema_dir.iterdir()
        if path.is_file()
    } == {
        "intent-resolution-draft.schema.json": "e73e4fc6b1b7558bce2a621b0dce73d91094f21cf81f07337f707dc26e77939f",
        "resolver-build-manifest.schema.json": "5cf9f01ea4ad1ac5d9c68a19a89454e63af77e1c05b3aaa1eed29a7e2a65ddcb",
        "validated-intent-resolution.schema.json": "d9bddafe11b4f35461da7ce1e30bef9ae4758e65dea4b2752ffec55085e56162",
    }


def test_committed_v2_schema_files_match_a_fresh_export() -> None:
    project_root = Path(__file__).resolve().parents[2]

    check_schemas(project_root / "schemas/intent/v2", schema_version="2.0")


def test_v3_schema_export_generates_the_complete_v3_contract_bundle(
    tmp_path: Path,
) -> None:
    export_schemas(tmp_path, schema_version="3.0")

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "intent-resolution-draft.schema.json",
        "intent-resolution-proposal.schema.json",
        "resolver-build-manifest.schema.json",
        "validated-intent-resolution.schema.json",
    ]
    proposal_schema = json.loads(
        (tmp_path / "intent-resolution-proposal.schema.json").read_text(
            encoding="utf-8"
        )
    )
    resolution_schema = json.loads(
        (tmp_path / "validated-intent-resolution.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        proposal_schema["properties"]["proposal_schema_version"]["const"]
        == "3.0"
    )
    assert "proposal_schema_version" in proposal_schema["required"]
    assert "semantic_links" in resolution_schema["required"]
    check_schemas(tmp_path, schema_version="3.0")


def test_v3_intent_schemas_are_fresh() -> None:
    project_root = Path(__file__).resolve().parents[2]

    check_schemas(project_root / "schemas/intent/v3", schema_version="3.0")


@pytest.mark.parametrize("schema_version", ("2.0", "3.0"))
def test_cli_requires_explicit_output_dir_for_nondefault_schema_versions(
    tmp_path: Path,
    schema_version: Literal["2.0", "3.0"],
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    v1_dir = project_root / "schemas/intent/v1"
    v1_before = {path.name: path.read_bytes() for path in v1_dir.iterdir()}
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project_root)

    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts/export_intent_schemas.py"),
            "--schema-version",
            schema_version,
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 2
    assert (
        "--output-dir is required when --schema-version is not 1.0"
        in completed.stderr
    )
    assert {path.name: path.read_bytes() for path in v1_dir.iterdir()} == v1_before
    assert not (tmp_path / "schemas").exists()


@pytest.mark.parametrize("schema_version", ("2.0", "3.0"))
def test_cli_exports_nondefault_schema_versions_to_explicit_output_dir(
    tmp_path: Path,
    schema_version: Literal["2.0", "3.0"],
) -> None:
    project_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/export_intent_schemas.py",
            "--schema-version",
            schema_version,
            "--output-dir",
            str(tmp_path),
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    check_schemas(tmp_path, schema_version=schema_version)


def test_cli_no_arguments_retains_v1_export_and_check_behavior(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(project_root)
    command = [sys.executable, str(project_root / "scripts/export_intent_schemas.py")]

    exported = subprocess.run(
        command,
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    checked = subprocess.run(
        [*command, "--check"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert exported.returncode == 0, exported.stderr
    assert checked.returncode == 0, checked.stderr
    check_schemas(tmp_path / "schemas/intent/v1")


@pytest.mark.parametrize("unknown_version", ("", "1", "2", "3", "4.0", "v3"))
def test_public_schema_export_rejects_every_unknown_runtime_version(
    tmp_path: Path,
    unknown_version: str,
) -> None:
    """Catches the public export API silently falling through to V3."""
    with pytest.raises(ValueError, match="unsupported intent schema version"):
        export_schemas(
            tmp_path / "unknown-export",
            schema_version=unknown_version,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("unknown_version", ("", "1", "2", "3", "4.0", "v3"))
def test_public_schema_check_rejects_every_unknown_runtime_version(
    tmp_path: Path,
    unknown_version: str,
) -> None:
    """Catches the public freshness API treating an unknown version as V3."""
    expected_dir = tmp_path / "v3"
    export_schemas(expected_dir, schema_version="3.0")

    with pytest.raises(ValueError, match="unsupported intent schema version"):
        check_schemas(
            expected_dir,
            schema_version=unknown_version,  # type: ignore[arg-type]
        )
