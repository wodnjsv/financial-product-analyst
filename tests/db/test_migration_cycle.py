from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from psycopg import sql

from financial_agent.db.preflight import (
    PreflightFailure,
    collect_database_objects,
    compare_database_object_manifests,
    normalize_psycopg_url,
    run_post_migration_preflight,
)
from scripts.export_database_objects import (
    DatabaseObjectManifestFailure,
    main as export_database_objects_main,
    write_or_check_manifest,
)
from scripts.verify_database_migrations import (
    MigrationVerificationFailure,
    _verify_foundation_behavior,
    configured_alembic_target_only,
    disposable_migration_database,
    migration_alembic_config,
    verify_migration_cycle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _object_manifest() -> dict[str, object]:
    return {
        "manifest_version": 1,
        "functions": [
            {
                "schema": "operations",
                "name": "finish_dataset_validation",
                "identity_arguments": "text",
                "definition": (
                    "CREATE FUNCTION operations.finish_dataset_validation(text)"
                ),
                "configuration": ["search_path=pg_catalog, operations, pg_temp"],
            }
        ],
        "views": [],
        "triggers": [],
        "checks": [],
        "owners": [
            {
                "object_type": "function",
                "schema": "operations",
                "name": "finish_dataset_validation(text)",
                "owner": "fa_migration",
            }
        ],
        "table_grants": [],
        "routine_grants": [],
        "schema_grants": [],
    }


def test_manifest_comparison_classifies_executable_definition_drift() -> None:
    expected = _object_manifest()
    actual = deepcopy(expected)
    actual["functions"][0]["definition"] += " changed"

    comparison = compare_database_object_manifests(expected, actual)

    assert comparison.object_drift is True
    assert comparison.permission_drift is False
    assert comparison.changed_sections == ("functions",)


def test_manifest_comparison_classifies_owner_and_acl_drift_as_permissions() -> None:
    expected = _object_manifest()
    actual = deepcopy(expected)
    actual["owners"][0]["owner"] = "__environment_owner__"
    actual["routine_grants"].append(
        {
            "schema": "operations",
            "name": "finish_dataset_validation",
            "identity_arguments": "text",
            "grantee": "PUBLIC",
            "privilege": "EXECUTE",
            "grantable": False,
        }
    )

    comparison = compare_database_object_manifests(expected, actual)

    assert comparison.object_drift is False
    assert comparison.permission_drift is True
    assert comparison.changed_sections == ("owners", "routine_grants")


@pytest.mark.postgres
def test_database_object_export_covers_non_table_ddl_and_permissions(
    migrated_database_url: str,
) -> None:
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        manifest = collect_database_objects(connection)

    assert manifest["manifest_version"] == 1
    assert {
        "functions",
        "views",
        "triggers",
        "checks",
        "owners",
        "table_grants",
        "routine_grants",
        "schema_grants",
    } <= manifest.keys()
    assert any(
        function["name"] == "finish_dataset_validation"
        and function["configuration"]
        == ["search_path=pg_catalog, operations, pg_temp"]
        for function in manifest["functions"]
    )
    assert any(
        view["name"] == "claim_eligible_evidence"
        for view in manifest["views"]
    )
    assert any(
        trigger["name"] == "derive_request_artifact"
        for trigger in manifest["triggers"]
    )
    assert any(
        check["name"] == "ck_dataset_version_cutoff_date"
        for check in manifest["checks"]
    )
    assert any(
        owner["owner"] == "fa_migration"
        for owner in manifest["owners"]
    )
    assert all(
        item.get("schema") != "cdb_admin"
        for section in manifest.values()
        if isinstance(section, list)
        for item in section
    )
    for section in manifest.values():
        if isinstance(section, list):
            assert section == sorted(
                section,
                key=lambda item: tuple(str(value) for value in item.values()),
            )


@pytest.mark.postgres
def test_manifest_check_is_byte_deterministic_and_classifies_drift(
    migrated_database_url: str,
    tmp_path,
) -> None:
    manifest_path = tmp_path / "database-objects.json"
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        write_or_check_manifest(connection, manifest_path, check=False)
        baseline_bytes = manifest_path.read_bytes()
        write_or_check_manifest(connection, manifest_path, check=True)
        write_or_check_manifest(connection, manifest_path, check=False)

    assert manifest_path.read_bytes() == baseline_bytes

    changed = json.loads(baseline_bytes)
    changed["functions"][0]["definition"] += " -- drift"
    manifest_path.write_text(
        json.dumps(changed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with psycopg.connect(
        normalize_psycopg_url(migrated_database_url)
    ) as connection:
        with pytest.raises(DatabaseObjectManifestFailure) as captured:
            write_or_check_manifest(connection, manifest_path, check=True)

    assert captured.value.code == "OBJECT_DEFINITION_DRIFT"
    assert "functions" in captured.value.changed_sections


def _apply_manifest_mutation(
    connection: psycopg.Connection,
    mutation: str,
) -> None:
    if mutation == "function_body":
        connection.execute(
            """
            CREATE OR REPLACE FUNCTION operations.validate_dataset_transition()
            RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog, operations, pg_temp
            AS $function$
            BEGIN
                RETURN NEW;
            END
            $function$
            """
        )
    elif mutation == "function_search_path":
        connection.execute(
            "ALTER FUNCTION operations.validate_dataset_transition() "
            "SET search_path = public"
        )
    elif mutation == "function_owner":
        owner = connection.execute("SELECT current_user").fetchone()[0]
        connection.execute(
            sql.SQL(
                "ALTER FUNCTION operations.validate_dataset_transition() OWNER TO {}"
            ).format(sql.Identifier(str(owner)))
        )
    elif mutation == "function_execute_acl":
        connection.execute(
            "GRANT EXECUTE ON FUNCTION "
            "operations.validate_dataset_transition() TO PUBLIC"
        )
    elif mutation == "view_predicate":
        definition = str(
            connection.execute(
                "SELECT pg_catalog.pg_get_viewdef("
                "'evidence.claim_eligible_evidence'::regclass, true)"
            ).fetchone()[0]
        ).rstrip().removesuffix(";")
        connection.execute(
            sql.SQL(
                "CREATE OR REPLACE VIEW evidence.claim_eligible_evidence AS "
            )
            + sql.SQL(definition)
            + sql.SQL(" AND false")
        )
    elif mutation == "trigger_timing":
        connection.execute(
            "DROP TRIGGER derive_request_artifact "
            "ON operations.request_artifact"
        )
        connection.execute(
            """
            CREATE TRIGGER derive_request_artifact
            AFTER INSERT ON operations.request_artifact
            FOR EACH ROW
            EXECUTE FUNCTION operations.derive_request_artifact()
            """
        )
    elif mutation == "cutoff_check":
        connection.execute(
            "ALTER TABLE operations.dataset_version "
            "DROP CONSTRAINT ck_dataset_version_cutoff_date"
        )
        connection.execute(
            "ALTER TABLE operations.dataset_version "
            "ADD CONSTRAINT ck_dataset_version_cutoff_date "
            "CHECK (cutoff_date <= DATE '2026-07-11')"
        )
    elif mutation == "runtime_grant":
        connection.execute(
            "GRANT INSERT ON operations.request_run TO fa_runtime"
        )
    else:  # pragma: no cover - the parametrization is exhaustive
        raise AssertionError(f"unknown manifest mutation: {mutation}")


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("mutation", "changed_section", "permission_drift"),
    (
        ("function_body", "functions", False),
        ("function_search_path", "functions", False),
        ("function_owner", "owners", True),
        ("function_execute_acl", "routine_grants", True),
        ("view_predicate", "views", False),
        ("trigger_timing", "triggers", False),
        ("cutoff_check", "checks", False),
        ("runtime_grant", "table_grants", True),
    ),
)
def test_manifest_detects_drift_alembic_autogenerate_does_not_cover(
    postgres_database_url: str,
    mutation: str,
    changed_section: str,
    permission_drift: bool,
) -> None:
    with disposable_migration_database(postgres_database_url) as database_url:
        config = migration_alembic_config(database_url)
        with configured_alembic_target_only():
            command.upgrade(config, "head")
        with psycopg.connect(
            normalize_psycopg_url(database_url)
        ) as connection:
            baseline = collect_database_objects(connection)
            _apply_manifest_mutation(connection, mutation)
        with configured_alembic_target_only():
            command.check(config)
        with psycopg.connect(
            normalize_psycopg_url(database_url)
        ) as connection:
            changed = collect_database_objects(connection)

    comparison = compare_database_object_manifests(baseline, changed)
    assert changed_section in comparison.changed_sections
    assert comparison.permission_drift is permission_drift
    assert comparison.object_drift is (not permission_drift)


def test_migration_verifier_refuses_a_nonlocal_or_nontest_source_url() -> None:
    with pytest.raises(MigrationVerificationFailure) as captured:
        verify_migration_cycle(
            "postgresql+psycopg://user:secret@db.invalid/production"
        )

    assert captured.value.code == "UNSAFE_DATABASE_TARGET"
    assert "secret" not in str(captured.value)


@pytest.mark.postgres
def test_postflight_classifies_a_base_database_as_migration_behind(
    postgres_database_url: str,
) -> None:
    with disposable_migration_database(postgres_database_url) as database_url:
        with pytest.raises(PreflightFailure) as captured:
            run_post_migration_preflight(database_url)

    assert captured.value.code == "MIGRATION_BEHIND"


@pytest.mark.postgres
def test_disposable_database_runs_base_head_base_head_cycle(
    postgres_database_url: str,
) -> None:
    report = verify_migration_cycle(postgres_database_url)

    assert report.alembic_head == "0005"
    assert report.application_schema_count == 7
    assert report.object_counts["tables"] > 0
    assert report.object_counts["checks"] > 0
    assert report.object_counts["foreign_keys"] > 0
    assert report.object_counts["indexes"] > 0
    assert report.object_counts["functions"] > 0
    assert report.object_counts["views"] > 0
    assert report.object_counts["triggers"] > 0
    assert report.ncp_extensions_preserved is True
    assert report.bootstrap_roles_preserved is True
    assert report.foundation_cutoff_enforced is True
    assert report.foundation_transition_enforced is True
    assert report.foundation_readiness_activation_enforced is True
    assert report.foundation_request_start_idempotent is True
    assert report.foundation_append_only_enforced is True
    assert report.foundation_concurrent_request_idempotent is True


def _mutate_second_head_behavior(
    connection: psycopg.Connection,
    mutation: str,
) -> None:
    if mutation == "readiness_activation":
        connection.execute(
            """
            CREATE OR REPLACE FUNCTION operations.activate_dataset(
                p_dataset_version text
            ) RETURNS text
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, operations, pg_temp
            AS $function$
            BEGIN
                RETURN p_dataset_version;
            END
            $function$
            """
        )
    elif mutation == "request_start":
        connection.execute(
            """
            CREATE OR REPLACE FUNCTION operations.start_request_run(
                p_run_id text, p_request_key text, p_question_id text,
                p_question text, p_schema_version text,
                p_dataset_version text, p_cutoff_date date,
                p_created_at timestamp with time zone,
                p_deadline_at timestamp with time zone
            ) RETURNS operations.request_run
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, operations, pg_temp
            AS $function$
            DECLARE
                empty_run operations.request_run%ROWTYPE;
            BEGIN
                RETURN empty_run;
            END
            $function$
            """
        )
    elif mutation == "append_only":
        connection.execute(
            "ALTER TABLE operations.request_artifact "
            "DISABLE TRIGGER reject_request_artifact_mutation"
        )
    elif mutation == "concurrent_idempotency":
        definition = str(
            connection.execute(
                "SELECT pg_catalog.pg_get_functiondef("
                "'operations.start_request_run(text,text,text,text,text,text,date,"
                "timestamp with time zone,timestamp with time zone)'::regprocedure)"
            ).fetchone()[0]
        )
        lock_statement = (
            "            PERFORM pg_catalog.pg_advisory_xact_lock(\n"
            "                pg_catalog.hashtextextended(p_run_id, 0)\n"
            "            );\n"
        )
        assert lock_statement in definition
        without_lock = definition.replace(
            lock_statement,
            "",
        )
        mutated = without_lock.replace(
            "            INSERT INTO operations.request_run (",
            "            PERFORM pg_catalog.pg_sleep(0.2);\n"
            "            INSERT INTO operations.request_run (",
        )
        assert "pg_advisory_xact_lock" not in mutated
        assert "pg_sleep(0.2)" in mutated
        connection.execute(mutated)
    else:  # pragma: no cover - parametrization is exhaustive
        raise AssertionError(f"unknown behavior mutation: {mutation}")


@pytest.mark.postgres
@pytest.mark.parametrize(
    "mutation",
    (
        "readiness_activation",
        "request_start",
        "append_only",
        "concurrent_idempotency",
    ),
)
def test_second_head_behavior_verifier_rejects_removed_invariants(
    postgres_database_url: str,
    mutation: str,
) -> None:
    with disposable_migration_database(postgres_database_url) as database_url:
        config = migration_alembic_config(database_url)
        with configured_alembic_target_only():
            command.upgrade(config, "head")
        with psycopg.connect(
            normalize_psycopg_url(database_url)
        ) as connection:
            _mutate_second_head_behavior(connection, mutation)

        with pytest.raises(MigrationVerificationFailure) as captured:
            _verify_foundation_behavior(database_url)

    assert captured.value.code == "FOUNDATION_INVARIANT_FAILED"


@pytest.mark.postgres
def test_migration_cycle_never_uses_an_ambient_database_url(
    postgres_database_url: str,
    monkeypatch,
) -> None:
    stale_url = (
        "postgresql+psycopg://secret_user:secret_password@"
        "127.0.0.1:1/secret_db"
    )
    monkeypatch.setenv("FINANCIAL_AGENT_DATABASE_URL", stale_url)

    report = verify_migration_cycle(postgres_database_url)

    assert report.alembic_head == "0005"
    assert os.environ["FINANCIAL_AGENT_DATABASE_URL"] == stale_url


def test_database_check_container_is_linux_amd64_and_uses_only_test_url() -> None:
    dockerfile = (
        PROJECT_ROOT / "docker" / "database-check.Dockerfile"
    ).read_text("utf-8")
    compose = (PROJECT_ROOT / "docker" / "postgres.compose.yml").read_text(
        "utf-8"
    )

    assert "PIP_CONSTRAINT=/app/requirements/storage.lock" in dockerfile
    assert 'python -m pip install ".[dev,storage]"' in dockerfile
    assert "scripts/verify_database_migrations.py" in dockerfile
    assert "tests/db" in dockerfile
    assert (
        "scripts/export_database_objects.py --check --database-url-env "
        "FINANCIAL_AGENT_TEST_DATABASE_URL"
    ) in dockerfile
    assert "COPY data/" not in dockerfile
    assert "db-check:" in compose
    assert "dockerfile: docker/database-check.Dockerfile" in compose
    assert compose.count("platform: linux/amd64") == 2
    assert "FINANCIAL_AGENT_TEST_DATABASE_URL:" in compose
    assert "FINANCIAL_AGENT_COMPOSE_DATABASE_CHECK: \"1\"" in compose
    assert "FINANCIAL_AGENT_DATABASE_URL:" not in compose
    assert "condition: service_healthy" in compose


def test_manifest_cli_requires_an_explicit_url_env_without_leaking_it(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv(
        "FINANCIAL_AGENT_TEST_DATABASE_URL",
        "postgresql://wrong_user:wrong_password@127.0.0.1:1/wrong_db",
    )
    monkeypatch.setenv(
        "FINANCIAL_AGENT_NCP_TEST_DATABASE_URL",
        "postgresql://secret_user:secret_password@127.0.0.1:1/secret_db",
    )

    exit_code = export_database_objects_main(
        [
            "--check",
            "--database-url-env",
            "FINANCIAL_AGENT_NCP_TEST_DATABASE_URL",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == (
        "DATABASE_QUERY_FAILED: database object export failed\n"
    )
    assert "secret_user" not in captured.err
    assert "secret_password" not in captured.err
    assert "secret_db" not in captured.err
    assert "wrong_user" not in captured.err
    assert "wrong_password" not in captured.err
    assert "wrong_db" not in captured.err
