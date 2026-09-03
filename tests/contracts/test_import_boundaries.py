from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "statements",
    (
        (
            "from financial_agent.intent.service import IntentResolverService",
            "import financial_agent.planning",
            "import financial_agent.contracts",
        ),
        (
            "import financial_agent.planning",
            "import financial_agent.contracts",
            "from financial_agent.intent.service import IntentResolverService",
        ),
        (
            "import financial_agent.contracts",
            "from financial_agent.contracts import ResolvedQueryContractSetV2",
            "from financial_agent.contracts import LogicalQueryPlanV2",
            "from financial_agent.intent.service import IntentResolverService",
            "import financial_agent.planning",
        ),
    ),
)
def test_public_modules_import_in_a_clean_interpreter(
    statements: tuple[str, ...],
) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", ";".join(statements)],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_contract_intent_and_planning_import_without_storage_dependencies() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    program = "\n".join(
        (
            "import sys",
            "class BlockStorageImports:",
            "    def find_spec(self, fullname, path=None, target=None):",
            "        if fullname.split('.')[0] in {'alembic', 'psycopg', 'sqlalchemy'}:",
            "            raise ModuleNotFoundError(fullname)",
            "        return None",
            "sys.meta_path.insert(0, BlockStorageImports())",
            "import financial_agent.contracts",
            "from financial_agent.intent.service import IntentResolverService",
            "import financial_agent.planning",
            "from financial_agent.contracts import ResolvedQueryContractSetV2",
            "from financial_agent.contracts import LogicalQueryPlanV2",
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
