from __future__ import annotations

from financial_agent.db.repositories.documents import (
    DocumentCorpusRepository,
)
from financial_agent.documents.carry_forward import rebase_captured_corpus
from tests.db.test_document_repository import _captured, _corpus


def test_rebase_captured_corpus_changes_only_dataset_scoped_identity() -> None:
    source = _captured(_corpus(dataset_version="source-v1"))

    target = rebase_captured_corpus(source, target_dataset="target-v1")

    DocumentCorpusRepository.validate_captured_corpus(target)
    assert target.source == source.source
    assert target.corpus.dataset_version == "target-v1"
    assert target.corpus.document_id == source.corpus.document_id
    assert target.corpus.content_checksum == source.corpus.content_checksum
    assert target.corpus.profile.dataset_version == "target-v1"
    assert target.corpus.profile.record_hash != source.corpus.profile.record_hash
    assert target.corpus.entity_bindings[0].dataset_version == "target-v1"
    assert (
        target.corpus.entity_bindings[0].record_hash
        != source.corpus.entity_bindings[0].record_hash
    )
    assert target.corpus.chunks[0].dataset_version == "target-v1"
    assert target.corpus.chunks[0].chunk_id == source.corpus.chunks[0].chunk_id
    assert target.corpus.chunks[0].exact_text == source.corpus.chunks[0].exact_text
    assert target.corpus.chunks[0].record_hash != source.corpus.chunks[0].record_hash
    assert target.corpus.coverage.dataset_version == "target-v1"
    assert target.corpus.coverage.coverage_id == (
        "coverage:target-v1:product-one:product_summary"
    )
    assert target.corpus.coverage.record_hash != source.corpus.coverage.record_hash
    assert target.source_artifact.dataset_version == "target-v1"
    assert (
        target.source_artifact.record_hash
        != source.source_artifact.record_hash
    )
