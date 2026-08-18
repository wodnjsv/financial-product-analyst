import json
from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "contracts" / "v1"


@pytest.fixture
def load_fixture() -> Callable[[str], dict[str, object]]:
    def load(name: str) -> dict[str, object]:
        return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))

    return load


@pytest.fixture
def load_fixture_json() -> Callable[[str], str]:
    def load(name: str) -> str:
        return (FIXTURE_ROOT / name).read_text(encoding="utf-8")

    return load


@pytest.fixture
def dump_json() -> Callable[[object], str]:
    def dump(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    return dump
