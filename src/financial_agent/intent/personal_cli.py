"""Shared credential and loopback target validation for personal CLIs."""

from __future__ import annotations

import os
import re
from pathlib import Path

from pydantic import SecretStr
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from .nvidia_config import NvidiaResolverConfig


class PersonalIntentCliError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def load_nvidia_config(key_file: Path | None) -> NvidiaResolverConfig:
    """Read an explicitly provided local file; never copy credentials into env."""
    if key_file is None:
        return NvidiaResolverConfig.from_env()
    try:
        text = key_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise PersonalIntentCliError("API_KEY_FILE_INVALID") from None
    keys = re.findall(
        r"^[ \t]*Nvidia[ \t]+API[ \t]*=[ \t]*(\S+)[ \t]*$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if len(keys) != 1:
        raise PersonalIntentCliError("API_KEY_FILE_INVALID")
    return NvidiaResolverConfig(
        api_key=SecretStr(keys[0]),
        model_id=os.environ.get("FINANCIAL_AGENT_INTENT_MODEL_ID", "z-ai/glm-5.3-flash"),
    )


def local_database_url(value: str) -> URL:
    try:
        target = make_url(value)
        valid = (
            target.drivername in ("postgresql", "postgresql+psycopg")
            and target.host in ("localhost", "127.0.0.1", "::1")
            and target.database == "financial_agent_local"
            and not target.query
            and (target.port is None or 0 < target.port <= 65_535)
        )
    except (TypeError, ValueError, ArgumentError):
        valid = False
    if not valid:
        raise PersonalIntentCliError("LOCAL_DATABASE_TARGET_REQUIRED")
    return target.set(drivername="postgresql+psycopg")
