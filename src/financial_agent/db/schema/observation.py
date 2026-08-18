from __future__ import annotations

import sqlalchemy as sa

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"


metric_definition = sa.Table(
    "metric_definition",
    metadata,
    sa.Column("metric_id", sa.Text, nullable=False),
    sa.Column("definition_version", sa.Text, nullable=False),
    sa.Column("semantic_family", sa.Text, nullable=False),
    sa.Column("value_kind", sa.Text, nullable=False),
    sa.Column("default_unit", sa.Text),
    sa.Column("description", sa.Text),
    sa.Column("definition_hash", sa.CHAR(64), nullable=False),
    sa.Column("approved_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint(
        "metric_id", "definition_version", name="pk_metric_definition"
    ),
    sa.CheckConstraint("metric_id <> ''", name="metric_id"),
    sa.CheckConstraint("definition_version <> ''", name="definition_version"),
    sa.CheckConstraint("semantic_family <> ''", name="semantic_family"),
    sa.CheckConstraint(
        "value_kind IN ('numeric','text','boolean','date','timestamp')",
        name="value_kind",
    ),
    sa.CheckConstraint(
        f"definition_hash ~ '{SHA256_PATTERN}'",
        name="definition_hash",
    ),
    schema="observation",
)


observation_record = sa.Table(
    "observation_record",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("observation_id", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text),
    sa.Column("relation_id", sa.Text),
    sa.Column("metric_id", sa.Text, nullable=False),
    sa.Column("metric_definition_version", sa.Text, nullable=False),
    sa.Column("value_status", sa.Text, nullable=False),
    sa.Column("numeric_value", sa.Numeric(38, 12)),
    sa.Column("text_value", sa.Text),
    sa.Column("boolean_value", sa.Boolean),
    sa.Column("date_value", sa.Date),
    sa.Column("timestamp_value", sa.TIMESTAMP(timezone=True)),
    sa.Column("unit", sa.Text),
    sa.Column("currency", sa.Text),
    sa.Column("period_start", sa.Date),
    sa.Column("period_end", sa.Date),
    sa.Column("applicable_date", sa.Date),
    sa.Column("published_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("available_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("vintage_date", sa.Date),
    sa.Column("reason_code", sa.Text),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_observation_record_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_observation_record_entity",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "relation_id"],
        [
            "relation.relation_record.dataset_version",
            "relation.relation_record.relation_id",
        ],
        name="fk_observation_record_relation",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["metric_id", "metric_definition_version"],
        [
            "observation.metric_definition.metric_id",
            "observation.metric_definition.definition_version",
        ],
        name="fk_observation_record_metric_definition",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "observation_id", name="pk_observation_record"
    ),
    sa.CheckConstraint(
        "(entity_id IS NOT NULL) <> (relation_id IS NOT NULL)",
        name="target_xor",
    ),
    sa.CheckConstraint(
        "value_status IN "
        "('present','zero','missing','placeholder','unavailable',"
        "'inapplicable','unknown')",
        name="value_status",
    ),
    sa.CheckConstraint(
        "(value_status = 'present' "
        " AND num_nonnulls(numeric_value, text_value, boolean_value, "
        "date_value, timestamp_value) = 1 "
        " AND (numeric_value IS NULL OR numeric_value <> 0) "
        " AND reason_code IS NULL) "
        "OR (value_status = 'zero' AND numeric_value = 0 "
        " AND text_value IS NULL AND boolean_value IS NULL "
        " AND date_value IS NULL AND timestamp_value IS NULL "
        " AND reason_code IS NULL) "
        "OR (value_status IN "
        "('missing','placeholder','unavailable','inapplicable','unknown') "
        " AND num_nonnulls(numeric_value, text_value, boolean_value, "
        "date_value, timestamp_value) = 0 "
        " AND reason_code IS NOT NULL AND reason_code <> '')",
        name="typed_value_status",
    ),
    sa.CheckConstraint(
        "period_end IS NULL OR period_start IS NULL OR period_end >= period_start",
        name="period_dates",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="observation",
)
sa.Index(
    "ix_observation_record_entity_metric_date",
    observation_record.c.dataset_version,
    observation_record.c.entity_id,
    observation_record.c.metric_id,
    observation_record.c.applicable_date,
)
sa.Index(
    "ix_observation_record_relation_metric_date",
    observation_record.c.dataset_version,
    observation_record.c.relation_id,
    observation_record.c.metric_id,
    observation_record.c.applicable_date,
)
