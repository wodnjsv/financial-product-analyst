from pathlib import Path

import pytest

from financial_agent.intent.schema_export import check_schemas, export_schemas


def test_schema_export_generates_exactly_three_contracts(tmp_path: Path) -> None:
    export_schemas(tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "intent-resolution-draft.schema.json",
        "resolver-build-manifest.schema.json",
        "validated-intent-resolution.schema.json",
    ]
    check_schemas(tmp_path)


@pytest.mark.parametrize("unexpected_name", ["extra.schema.json", "missing"])
def test_schema_check_rejects_extra_missing_or_changed_contract_files(
    tmp_path: Path,
    unexpected_name: str,
) -> None:
    export_schemas(tmp_path)
    target = tmp_path / "intent-resolution-draft.schema.json"
    if unexpected_name == "missing":
        target.unlink()
    else:
        (tmp_path / unexpected_name).write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="do not match"):
        check_schemas(tmp_path)
