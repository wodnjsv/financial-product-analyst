from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"


source_record = sa.Table(
    "source_record",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("source_id", sa.Text, nullable=False),
    sa.Column("publisher", sa.Text, nullable=False),
    sa.Column("publisher_type", sa.Text, nullable=False),
    sa.Column("source_title", sa.Text, nullable=False),
    sa.Column("source_type", sa.Text, nullable=False),
    sa.Column("authority_tier", sa.Text, nullable=False),
    sa.Column("source_locator_root", sa.Text, nullable=False),
    sa.Column("content_checksum", sa.CHAR(64), nullable=False),
    sa.Column("license_or_usage_note", sa.Text),
    sa.Column("eligible_for_claim", sa.Boolean, nullable=False),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_source_record_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "publisher"],
        [
            "catalog.institution.dataset_version",
            "catalog.institution.entity_id",
        ],
        name="fk_source_record_publisher",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "source_id", name="pk_source_record"
    ),
    sa.CheckConstraint("publisher_type <> ''", name="publisher_type"),
    sa.CheckConstraint("source_title <> ''", name="source_title"),
    sa.CheckConstraint("source_type <> ''", name="source_type"),
    sa.CheckConstraint("authority_tier <> ''", name="authority_tier"),
    sa.CheckConstraint("source_locator_root <> ''", name="source_locator_root"),
    sa.CheckConstraint(
        f"content_checksum ~ '{SHA256_PATTERN}'",
        name="content_checksum",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="evidence",
)


evidence_record = sa.Table(
    "evidence_record",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("evidence_id", sa.Text, nullable=False),
    sa.Column("evidence_kind", sa.Text, nullable=False),
    sa.Column("source_id", sa.Text, nullable=False),
    sa.Column("subject_id", sa.Text),
    sa.Column("predicate_id", sa.Text),
    sa.Column("value_or_object_id", postgresql.JSONB, nullable=False),
    sa.Column("normalized_value", postgresql.JSONB, nullable=False),
    sa.Column("unit", sa.Text),
    sa.Column("currency", sa.Text),
    sa.Column("applicable_date", sa.Date),
    sa.Column("valid_from", sa.Date),
    sa.Column("valid_to", sa.Date),
    sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("available_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("vintage_date", sa.Date),
    sa.Column("locator_type", sa.Text, nullable=False),
    sa.Column("locator_uri_or_object_key", sa.Text, nullable=False),
    sa.Column("locator_record_key", sa.Text),
    sa.Column("locator_sheet", sa.Text),
    sa.Column("locator_row", sa.Integer),
    sa.Column("locator_column", sa.Text),
    sa.Column("locator_page", sa.Integer),
    sa.Column("locator_section", sa.Text),
    sa.Column("locator_sentence_start", sa.Integer),
    sa.Column("locator_sentence_end", sa.Integer),
    sa.Column("raw_value_repr", sa.Text),
    sa.Column("parser_version", sa.Text, nullable=False),
    sa.Column("mapping_version", sa.Text, nullable=False),
    sa.Column("cutoff_status", sa.Text, nullable=False),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("scope_completeness", sa.Text),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_evidence_record_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "source_id"],
        ["evidence.source_record.dataset_version", "evidence.source_record.source_id"],
        name="fk_evidence_record_source",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "subject_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_evidence_record_subject",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "evidence_id", name="pk_evidence_record"
    ),
    sa.CheckConstraint(
        "evidence_kind IN ('observation','relation','document_span',"
        "'query_scope','exclusion','policy')",
        name="evidence_kind",
    ),
    sa.CheckConstraint(
        "evidence_kind NOT IN ('observation','relation','document_span') "
        "OR subject_id IS NOT NULL",
        name="origin_subject",
    ),
    sa.CheckConstraint(
        "(evidence_kind = 'query_scope' AND scope_completeness IS NOT NULL "
        "AND scope_completeness IN "
        "('closed_world','bounded_unknown')) OR "
        "(evidence_kind <> 'query_scope' AND scope_completeness IS NULL)",
        name="scope_completeness",
    ),
    sa.CheckConstraint(
        "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
        name="valid_dates",
    ),
    sa.CheckConstraint(
        "cutoff_status IN "
        "('eligible','after_cutoff','unknown_vintage','inapplicable')",
        name="cutoff_status",
    ),
    sa.CheckConstraint(
        "evidence.is_valid_tagged_value(value_or_object_id) "
        "AND value_or_object_id ->> 'type' <> 'tuple'",
        name="value_or_object_id",
    ),
    sa.CheckConstraint(
        "evidence.is_valid_tagged_value(normalized_value) "
        "AND normalized_value ->> 'type' <> 'tuple'",
        name="normalized_value",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="evidence",
)
sa.Index(
    "ix_evidence_record_subject_predicate_date",
    evidence_record.c.dataset_version,
    evidence_record.c.subject_id,
    evidence_record.c.predicate_id,
    evidence_record.c.applicable_date.desc(),
)
sa.Index(
    "ix_evidence_record_source",
    evidence_record.c.dataset_version,
    evidence_record.c.source_id,
)
sa.Index(
    "ix_evidence_record_eligible_cutoff",
    evidence_record.c.dataset_version,
    evidence_record.c.cutoff_status,
    postgresql_where=evidence_record.c.cutoff_status == "eligible",
)


evidence_observation_origin = sa.Table(
    "evidence_observation_origin",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("evidence_id", sa.Text, nullable=False),
    sa.Column("observation_id", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version", "evidence_id"],
        ["evidence.evidence_record.dataset_version", "evidence.evidence_record.evidence_id"],
        name="fk_evidence_observation_origin_evidence",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "observation_id"],
        [
            "observation.observation_record.dataset_version",
            "observation.observation_record.observation_id",
        ],
        name="fk_evidence_observation_origin_observation",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "evidence_id", name="pk_evidence_observation_origin"
    ),
    schema="evidence",
)


evidence_relation_origin = sa.Table(
    "evidence_relation_origin",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("evidence_id", sa.Text, nullable=False),
    sa.Column("relation_id", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version", "evidence_id"],
        ["evidence.evidence_record.dataset_version", "evidence.evidence_record.evidence_id"],
        name="fk_evidence_relation_origin_evidence",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "relation_id"],
        ["relation.relation_record.dataset_version", "relation.relation_record.relation_id"],
        name="fk_evidence_relation_origin_relation",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "evidence_id", name="pk_evidence_relation_origin"
    ),
    schema="evidence",
)


evidence_document_origin = sa.Table(
    "evidence_document_origin",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("evidence_id", sa.Text, nullable=False),
    sa.Column("chunk_id", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version", "evidence_id"],
        ["evidence.evidence_record.dataset_version", "evidence.evidence_record.evidence_id"],
        name="fk_evidence_document_origin_evidence",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "chunk_id"],
        ["document.document_chunk.dataset_version", "document.document_chunk.chunk_id"],
        name="fk_evidence_document_origin_chunk",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "evidence_id", name="pk_evidence_document_origin"
    ),
    schema="evidence",
)


calculation_record = sa.Table(
    "calculation_record",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("calculation_id", sa.Text, nullable=False),
    sa.Column("calculation_type", sa.Text, nullable=False),
    sa.Column("formula_id", sa.Text, nullable=False),
    sa.Column("formula_version", sa.Text, nullable=False),
    sa.Column("tie_break_rule", sa.Text),
    sa.Column("result_value", postgresql.JSONB, nullable=False),
    sa.Column("unit", sa.Text),
    sa.Column("currency", sa.Text),
    sa.Column("rounding_rule", sa.Text),
    sa.Column("calculation_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version"],
        ["operations.request_run.run_id", "operations.request_run.dataset_version"],
        name="fk_calculation_record_request_dataset",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint("run_id", "calculation_id", name="pk_calculation_record"),
    sa.UniqueConstraint(
        "run_id",
        "dataset_version",
        "calculation_id",
        name="uq_calculation_record_run_dataset_calculation",
    ),
    sa.CheckConstraint(
        "calculation_type IN "
        "('conversion','return','ranking','aggregation','comparison','similarity')",
        name="calculation_type",
    ),
    sa.CheckConstraint(
        "evidence.is_valid_tagged_value(result_value) "
        "AND result_value ->> 'type' <> 'tuple'",
        name="result_value",
    ),
    sa.CheckConstraint(
        f"calculation_hash ~ '{SHA256_PATTERN}'",
        name="calculation_hash",
    ),
    schema="evidence",
)
sa.Index(
    "ix_calculation_record_run_hash",
    calculation_record.c.run_id,
    calculation_record.c.calculation_hash,
)


calculation_parameter = sa.Table(
    "calculation_parameter",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("calculation_id", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("parameter_id", sa.Text, nullable=False),
    sa.Column("value", postgresql.JSONB, nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "calculation_id"],
        [
            "evidence.calculation_record.run_id",
            "evidence.calculation_record.dataset_version",
            "evidence.calculation_record.calculation_id",
        ],
        name="fk_calculation_parameter_calculation",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "run_id", "calculation_id", "ordinal", name="pk_calculation_parameter"
    ),
    sa.UniqueConstraint(
        "run_id",
        "calculation_id",
        "parameter_id",
        name="uq_calculation_parameter_id",
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    sa.CheckConstraint(
        "evidence.is_valid_tagged_value(value)", name="value"
    ),
    schema="evidence",
)


calculation_evidence_input = sa.Table(
    "calculation_evidence_input",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("calculation_id", sa.Text, nullable=False),
    sa.Column("evidence_id", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "calculation_id"],
        [
            "evidence.calculation_record.run_id",
            "evidence.calculation_record.dataset_version",
            "evidence.calculation_record.calculation_id",
        ],
        name="fk_calculation_evidence_input_calculation",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "evidence_id"],
        ["evidence.evidence_record.dataset_version", "evidence.evidence_record.evidence_id"],
        name="fk_calculation_evidence_input_evidence",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "run_id", "calculation_id", "ordinal", name="pk_calculation_evidence_input"
    ),
    sa.UniqueConstraint(
        "run_id",
        "calculation_id",
        "evidence_id",
        name="uq_calculation_evidence_input_evidence",
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    schema="evidence",
)


calculation_dependency = sa.Table(
    "calculation_dependency",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("calculation_id", sa.Text, nullable=False),
    sa.Column("input_calculation_id", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "calculation_id"],
        [
            "evidence.calculation_record.run_id",
            "evidence.calculation_record.dataset_version",
            "evidence.calculation_record.calculation_id",
        ],
        name="fk_calculation_dependency_calculation",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "input_calculation_id"],
        [
            "evidence.calculation_record.run_id",
            "evidence.calculation_record.dataset_version",
            "evidence.calculation_record.calculation_id",
        ],
        name="fk_calculation_dependency_input",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "run_id", "calculation_id", "ordinal", name="pk_calculation_dependency"
    ),
    sa.UniqueConstraint(
        "run_id",
        "calculation_id",
        "input_calculation_id",
        name="uq_calculation_dependency_input",
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    sa.CheckConstraint("calculation_id <> input_calculation_id", name="not_self"),
    schema="evidence",
)


calculation_exclusion = sa.Table(
    "calculation_exclusion",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("calculation_id", sa.Text, nullable=False),
    sa.Column("evidence_id", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "calculation_id"],
        [
            "evidence.calculation_record.run_id",
            "evidence.calculation_record.dataset_version",
            "evidence.calculation_record.calculation_id",
        ],
        name="fk_calculation_exclusion_calculation",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "evidence_id"],
        ["evidence.evidence_record.dataset_version", "evidence.evidence_record.evidence_id"],
        name="fk_calculation_exclusion_evidence",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "run_id", "calculation_id", "ordinal", name="pk_calculation_exclusion"
    ),
    sa.UniqueConstraint(
        "run_id",
        "calculation_id",
        "evidence_id",
        name="uq_calculation_exclusion_evidence",
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    schema="evidence",
)


calculation_population = sa.Table(
    "calculation_population",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("calculation_id", sa.Text, nullable=False),
    sa.Column("population_id", sa.Text, nullable=False),
    sa.Column("scope_evidence_id", sa.Text, nullable=False),
    sa.Column("member_count", sa.Integer, nullable=False),
    sa.Column("population_hash", sa.CHAR(64), nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "calculation_id"],
        [
            "evidence.calculation_record.run_id",
            "evidence.calculation_record.dataset_version",
            "evidence.calculation_record.calculation_id",
        ],
        name="fk_calculation_population_calculation",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "scope_evidence_id"],
        ["evidence.evidence_record.dataset_version", "evidence.evidence_record.evidence_id"],
        name="fk_calculation_population_scope_evidence",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "run_id", "calculation_id", name="pk_calculation_population"
    ),
    sa.UniqueConstraint(
        "run_id",
        "dataset_version",
        "calculation_id",
        name="uq_calculation_population_run_dataset_calculation",
    ),
    sa.UniqueConstraint(
        "run_id", "population_id", name="uq_calculation_population_id"
    ),
    sa.CheckConstraint("member_count >= 0", name="member_count"),
    sa.CheckConstraint(
        f"population_hash ~ '{SHA256_PATTERN}'", name="population_hash"
    ),
    schema="evidence",
)


calculation_population_filter = sa.Table(
    "calculation_population_filter",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("calculation_id", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("filter_id", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "calculation_id"],
        [
            "evidence.calculation_population.run_id",
            "evidence.calculation_population.dataset_version",
            "evidence.calculation_population.calculation_id",
        ],
        name="fk_calculation_population_filter_population",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "run_id",
        "calculation_id",
        "ordinal",
        name="pk_calculation_population_filter",
    ),
    sa.UniqueConstraint(
        "run_id",
        "calculation_id",
        "filter_id",
        name="uq_calculation_population_filter_id",
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    schema="evidence",
)


atomic_claim = sa.Table(
    "atomic_claim",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("claim_id", sa.Text, nullable=False),
    sa.Column("claim_type", sa.Text, nullable=False),
    sa.Column("subtask_id", sa.Text, nullable=False),
    sa.Column("subject_id", sa.Text, nullable=False),
    sa.Column("subject_kind", sa.Text, nullable=False),
    sa.Column("subject_entity_id", sa.Text),
    sa.Column("request_subject_id", sa.Text),
    sa.Column("predicate_id", sa.Text, nullable=False),
    sa.Column("object_id", sa.Text),
    sa.Column("value", postgresql.JSONB),
    sa.Column("unit", sa.Text),
    sa.Column("currency", sa.Text),
    sa.Column("display_policy_id", sa.Text, nullable=False),
    sa.Column("claim_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version"],
        ["operations.request_run.run_id", "operations.request_run.dataset_version"],
        name="fk_atomic_claim_request_dataset",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "subtask_id"],
        ["operations.request_subtask.run_id", "operations.request_subtask.subtask_id"],
        name="fk_atomic_claim_subtask",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "subject_entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_atomic_claim_subject_entity",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "request_subject_id"],
        ["operations.request_subtask.run_id", "operations.request_subtask.subtask_id"],
        name="fk_atomic_claim_request_subject",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "object_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_atomic_claim_object",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint("run_id", "claim_id", name="pk_atomic_claim"),
    sa.UniqueConstraint(
        "run_id",
        "dataset_version",
        "claim_id",
        name="uq_atomic_claim_run_dataset_claim",
    ),
    sa.CheckConstraint(
        "claim_type IN ('direct_fact','relation','derived_metric','rank',"
        "'similarity','no_match','data_limitation','policy_boundary')",
        name="claim_type",
    ),
    sa.CheckConstraint(
        "(claim_type IN ('direct_fact','relation','derived_metric','rank','similarity') "
        "AND subject_kind = 'entity' AND subject_entity_id IS NOT NULL "
        "AND subject_entity_id = subject_id "
        "AND request_subject_id IS NULL) OR "
        "(claim_type IN ('no_match','data_limitation','policy_boundary') "
        "AND subject_kind = 'request' AND subject_entity_id IS NULL "
        "AND request_subject_id IS NOT NULL AND request_subject_id = subject_id "
        "AND subject_id = subtask_id)",
        name="subject_scope",
    ),
    sa.CheckConstraint(
        "(num_nonnulls(object_id, value) = 1) OR "
        "(claim_type IN ('data_limitation','policy_boundary') "
        "AND object_id IS NULL AND value IS NULL)",
        name="target",
    ),
    sa.CheckConstraint(
        "value IS NULL OR (evidence.is_valid_tagged_value(value) "
        "AND value ->> 'type' <> 'tuple')",
        name="value",
    ),
    sa.CheckConstraint(f"claim_hash ~ '{SHA256_PATTERN}'", name="claim_hash"),
    schema="evidence",
)
sa.Index(
    "ix_atomic_claim_run_hash",
    atomic_claim.c.run_id,
    atomic_claim.c.claim_hash,
)


claim_qualifier = sa.Table(
    "claim_qualifier",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("claim_id", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("qualifier_id", sa.Text, nullable=False),
    sa.Column("value", postgresql.JSONB, nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "claim_id"],
        [
            "evidence.atomic_claim.run_id",
            "evidence.atomic_claim.dataset_version",
            "evidence.atomic_claim.claim_id",
        ],
        name="fk_claim_qualifier_claim",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "run_id", "claim_id", "ordinal", name="pk_claim_qualifier"
    ),
    sa.UniqueConstraint(
        "run_id", "claim_id", "qualifier_id", name="uq_claim_qualifier_id"
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    sa.CheckConstraint("evidence.is_valid_tagged_value(value)", name="value"),
    schema="evidence",
)


claim_support = sa.Table(
    "claim_support",
    metadata,
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("claim_id", sa.Text, nullable=False),
    sa.Column("support_kind", sa.Text, nullable=False),
    sa.Column("evidence_id", sa.Text),
    sa.Column("calculation_id", sa.Text),
    sa.Column("support_role", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "claim_id"],
        [
            "evidence.atomic_claim.run_id",
            "evidence.atomic_claim.dataset_version",
            "evidence.atomic_claim.claim_id",
        ],
        name="fk_claim_support_claim",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "evidence_id"],
        ["evidence.evidence_record.dataset_version", "evidence.evidence_record.evidence_id"],
        name="fk_claim_support_evidence",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "calculation_id"],
        [
            "evidence.calculation_record.run_id",
            "evidence.calculation_record.dataset_version",
            "evidence.calculation_record.calculation_id",
        ],
        name="fk_claim_support_calculation",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "run_id", "claim_id", "ordinal", name="pk_claim_support"
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    sa.CheckConstraint(
        "support_kind IN ('direct','calculation','scope','exclusion','policy')",
        name="support_kind",
    ),
    sa.CheckConstraint(
        "(support_kind = 'calculation' AND calculation_id IS NOT NULL "
        "AND evidence_id IS NULL) OR "
        "(support_kind <> 'calculation' AND evidence_id IS NOT NULL "
        "AND calculation_id IS NULL)",
        name="target",
    ),
    schema="evidence",
)
sa.Index(
    "ix_claim_support_evidence",
    claim_support.c.dataset_version,
    claim_support.c.evidence_id,
)
sa.Index(
    "ix_claim_support_calculation",
    claim_support.c.run_id,
    claim_support.c.calculation_id,
)
