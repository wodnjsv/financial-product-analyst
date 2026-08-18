from __future__ import annotations

from financial_agent.db.preflight import main


def test_preflight_cli_rejects_an_unset_url_without_printing_credentials(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("MISSING_TEST_DATABASE_URL", raising=False)

    exit_code = main(
        [
            "--phase",
            "pre-migration",
            "--database-url-env",
            "MISSING_TEST_DATABASE_URL",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == (
        "MISSING_DATABASE_URL: requested environment variable is unset\n"
    )
