from __future__ import annotations

import pytest

from financial_agent.db.capabilities import (
    CapabilityProbeFailure,
    CapabilityResult,
    choose_permission_layout,
    main,
    probe_ncp_capabilities,
)


def _capabilities(**overrides: bool) -> CapabilityResult:
    values = {
        "create_nologin_role": True,
        "drop_role": True,
        "create_schema": True,
        "transfer_schema_owner": True,
        "create_security_definer": True,
        "grant_revoke": True,
        "manage_role_membership": True,
    }
    values.update(overrides)
    return CapabilityResult(**values)


def test_capability_probe_selects_group_roles_when_every_capability_exists() -> None:
    assert choose_permission_layout(_capabilities()) == "group_roles"


def test_capability_probe_falls_back_to_direct_users_without_role_admin() -> None:
    capabilities = _capabilities(
        create_nologin_role=False,
        drop_role=False,
        transfer_schema_owner=False,
        manage_role_membership=False,
    )

    assert choose_permission_layout(capabilities) == "direct_users"


@pytest.mark.parametrize(
    "missing_capability",
    ("create_schema", "create_security_definer", "grant_revoke"),
)
def test_capability_probe_rejects_missing_core_migration_capabilities(
    missing_capability: str,
) -> None:
    with pytest.raises(CapabilityProbeFailure) as captured:
        choose_permission_layout(_capabilities(**{missing_capability: False}))

    assert captured.value.code == "NCP_CAPABILITY_INSUFFICIENT"


def test_capability_probe_cli_rejects_an_unset_url_without_identifiers(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("MISSING_NCP_DATABASE_URL", raising=False)

    exit_code = main(
        ["--database-url-env", "MISSING_NCP_DATABASE_URL"]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == (
        "MISSING_DATABASE_URL: requested environment variable is unset\n"
    )


def test_capability_probe_hides_connection_identifiers_on_failure() -> None:
    url = "postgresql://secret_user:secret_password@127.0.0.1:1/secret_db"

    with pytest.raises(CapabilityProbeFailure) as captured:
        probe_ncp_capabilities(url, connect_timeout_seconds=1)

    assert captured.value.code == "DATABASE_UNREACHABLE"
    assert "secret_user" not in str(captured.value)
    assert "secret_password" not in str(captured.value)
    assert "secret_db" not in str(captured.value)
