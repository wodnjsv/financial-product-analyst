import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .draft import IntentResolutionDraft
from .resolution import ResolverBuildManifest, ValidatedIntentResolution

SCHEMA_REGISTRY = {
    "intent-resolution-draft": IntentResolutionDraft,
    "resolver-build-manifest": ResolverBuildManifest,
    "validated-intent-resolution": ValidatedIntentResolution,
}


def export_schemas(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMA_REGISTRY.items():
        rendered = json.dumps(
            model.model_json_schema(mode="validation"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"
        (output_dir / f"{name}.schema.json").write_text(rendered, encoding="utf-8")


def check_schemas(expected_dir: Path) -> None:
    with TemporaryDirectory() as temporary_dir:
        generated_dir = Path(temporary_dir)
        export_schemas(generated_dir)
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
