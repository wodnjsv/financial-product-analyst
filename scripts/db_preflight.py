"""Thin CLI wrapper for pre- and post-migration database verification."""

from financial_agent.db.preflight import main


if __name__ == "__main__":
    raise SystemExit(main())
