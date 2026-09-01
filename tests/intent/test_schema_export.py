from hashlib import sha256
from pathlib import Path

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
