import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from .draft import (
    IntentResolutionDraft,
    IntentResolutionDraftV2,
    IntentResolutionDraftV3,
)
from .hybrid_proposal import IntentResolutionProposalV3
from .proposal import IntentResolutionProposalV2
from .resolution import (
    ResolverBuildManifest,
    ValidatedIntentResolution,
    ValidatedIntentResolutionV2,
    ValidatedIntentResolutionV3,
)

SCHEMA_REGISTRY = {
    "intent-resolution-draft": IntentResolutionDraft,
    "resolver-build-manifest": ResolverBuildManifest,
    "validated-intent-resolution": ValidatedIntentResolution,
}
V2_SCHEMA_REGISTRY = {
    "intent-resolution-proposal": IntentResolutionProposalV2,
    "resolver-build-manifest": ResolverBuildManifest,
    "intent-resolution-draft": IntentResolutionDraftV2,
    "validated-intent-resolution": ValidatedIntentResolutionV2,
}
V3_SCHEMA_REGISTRY = {
    "intent-resolution-proposal": IntentResolutionProposalV3,
    "resolver-build-manifest": ResolverBuildManifest,
    "intent-resolution-draft": IntentResolutionDraftV3,
    "validated-intent-resolution": ValidatedIntentResolutionV3,
}


def export_schemas(
    output_dir: Path, *, schema_version: Literal["1.0", "2.0", "3.0"] = "1.0"
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
    expected_dir: Path, *, schema_version: Literal["1.0", "2.0", "3.0"] = "1.0"
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


def _schema_registry(schema_version: Literal["1.0", "2.0", "3.0"]):
    if schema_version == "1.0":
        return SCHEMA_REGISTRY
    if schema_version == "2.0":
        return V2_SCHEMA_REGISTRY
    return V3_SCHEMA_REGISTRY
