from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
from pathlib import Path
import sys

import psycopg

from financial_agent.db.preflight import (
    collect_database_objects,
    compare_database_object_manifests,
    normalize_psycopg_url,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = (
    PROJECT_ROOT / "schemas" / "postgresql" / "v1" / "database-objects.json"
)


class DatabaseObjectManifestFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        changed_sections: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.changed_sections = changed_sections


def render_database_objects(manifest: object) -> bytes:
    return (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    ).encode("utf-8")


def write_or_check_manifest(
    connection: psycopg.Connection,
    manifest_path: Path,
    *,
    check: bool,
) -> None:
    actual = collect_database_objects(connection)
    actual_bytes = render_database_objects(actual)
    if not check:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(actual_bytes)
        return

    try:
        expected_bytes = manifest_path.read_bytes()
        expected = json.loads(expected_bytes)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise DatabaseObjectManifestFailure(
            "OBJECT_DEFINITION_DRIFT",
            "reviewed database-object manifest is missing or invalid",
            changed_sections=("manifest",),
        ) from error

    comparison = compare_database_object_manifests(expected, actual)
    if comparison.object_drift:
        raise DatabaseObjectManifestFailure(
            "OBJECT_DEFINITION_DRIFT",
            "database object definitions differ from the reviewed manifest",
            changed_sections=comparison.changed_sections,
        )
    if comparison.permission_drift:
        raise DatabaseObjectManifestFailure(
            "DATABASE_PERMISSION_DRIFT",
            "database permissions differ from the reviewed manifest",
            changed_sections=comparison.changed_sections,
        )
    if expected_bytes != actual_bytes:
        raise DatabaseObjectManifestFailure(
            "OBJECT_DEFINITION_DRIFT",
            "database-object manifest serialization is not deterministic",
            changed_sections=("serialization",),
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)

    database_url = os.environ.get(
        "FINANCIAL_AGENT_TEST_DATABASE_URL"
    ) or os.environ.get("FINANCIAL_AGENT_NCP_TEST_DATABASE_URL")
    if not database_url:
        print(
            "MISSING_DATABASE_URL: no test database URL is configured",
            file=sys.stderr,
        )
        return 2
    try:
        with psycopg.connect(normalize_psycopg_url(database_url)) as connection:
            write_or_check_manifest(
                connection,
                DEFAULT_MANIFEST_PATH,
                check=arguments.check,
            )
    except DatabaseObjectManifestFailure as error:
        sections = ",".join(error.changed_sections)
        print(f"{error.code}: {error}; sections={sections}", file=sys.stderr)
        return 2
    except psycopg.Error:
        print("DATABASE_QUERY_FAILED: database object export failed", file=sys.stderr)
        return 2

    mode = "check" if arguments.check else "write"
    print(f"DATABASE_OBJECTS_OK mode={mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
