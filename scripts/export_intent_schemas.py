import argparse
from pathlib import Path

from financial_agent.intent.schema_export import check_schemas, export_schemas

DEFAULT_OUTPUT = Path("schemas/intent/v1")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--schema-version",
        choices=("1.0", "2.0", "3.0"),
        default="1.0",
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.schema_version != "1.0" and args.output_dir is None:
        parser.error("--output-dir is required when --schema-version is not 1.0")
    output_dir = args.output_dir or DEFAULT_OUTPUT
    if args.check:
        check_schemas(output_dir, schema_version=args.schema_version)
    else:
        export_schemas(output_dir, schema_version=args.schema_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
