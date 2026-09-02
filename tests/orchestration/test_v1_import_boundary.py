from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_v1_orchestration_imports_without_sqlalchemy_extra() -> None:
    code = """
import builtins
real_import = builtins.__import__
def blocked(name, *args, **kwargs):
    if name == 'sqlalchemy' or name.startswith('sqlalchemy.'):
        raise ModuleNotFoundError('sqlalchemy deliberately blocked')
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked
from financial_agent.orchestration.executors import (
    CapabilityExecutor, ExecutorRegistry, TaskExecutionInput, build_tool_result
)
assert TaskExecutionInput.__name__ == 'TaskExecutionInput'
assert CapabilityExecutor.__name__ == 'CapabilityExecutor'
assert ExecutorRegistry.__name__ == 'ExecutorRegistry'
assert callable(build_tool_result)
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
