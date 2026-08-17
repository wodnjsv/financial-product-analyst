import argparse
from pathlib import Path

from financial_agent.contracts.schema_export import check_schemas, export_schemas

DEFAULT_OUTPUT = Path("schemas/contracts/v1")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_schemas(DEFAULT_OUTPUT)
    else:
        export_schemas(DEFAULT_OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
