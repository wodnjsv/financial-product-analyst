from pathlib import Path

import pytest

from financial_agent.intent.schema_export import check_schemas, export_schemas


def test_v2_schema_export_generates_only_the_finalized_proposal(tmp_path: Path) -> None:
    export_schemas(tmp_path, schema_version="2.0")

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "intent-resolution-proposal.schema.json",
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
