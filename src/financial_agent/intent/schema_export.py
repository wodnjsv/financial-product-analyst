import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from .draft import IntentResolutionDraft
from .proposal import IntentResolutionProposalV2
from .resolution import ResolverBuildManifest, ValidatedIntentResolution

SCHEMA_REGISTRY = {
    "intent-resolution-draft": IntentResolutionDraft,
    "resolver-build-manifest": ResolverBuildManifest,
    "validated-intent-resolution": ValidatedIntentResolution,
}
V2_SCHEMA_REGISTRY = {
    "intent-resolution-proposal": IntentResolutionProposalV2,
}


def export_schemas(
    output_dir: Path, *, schema_version: Literal["1.0", "2.0"] = "1.0"
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, model in _schema_registry(schema_version).items():
        rendered = json.dumps(
            model.model_json_schema(mode="validation"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"
        (output_dir / f"{name}.schema.json").write_text(rendered, encoding="utf-8")


def check_schemas(
    expected_dir: Path, *, schema_version: Literal["1.0", "2.0"] = "1.0"
) -> None:
    with TemporaryDirectory() as temporary_dir:
        generated_dir = Path(temporary_dir)
        export_schemas(generated_dir, schema_version=schema_version)
        generated = {path.name: path.read_bytes() for path in generated_dir.iterdir()}
        committed = (
            {
                path.name: path.read_bytes()
                for path in expected_dir.iterdir()
                if path.is_file()
            }
            if expected_dir.exists()
            else {}
        )
    if generated != committed:
        raise ValueError("committed intent schemas do not match fresh export")


def _schema_registry(schema_version: Literal["1.0", "2.0"]):
    if schema_version == "1.0":
        return SCHEMA_REGISTRY
    return V2_SCHEMA_REGISTRY
