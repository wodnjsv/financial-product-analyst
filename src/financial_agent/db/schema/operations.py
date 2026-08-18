from __future__ import annotations

import sqlalchemy as sa

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"


dataset_version = sa.Table(
    "dataset_version",
    metadata,
    sa.Column("dataset_version", sa.Text, primary_key=True),
    sa.Column("cutoff_date", sa.Date, nullable=False),
    sa.Column(
        "status",
        sa.Text,
        nullable=False,
        server_default=sa.text("'building'"),
    ),
    sa.Column("manifest_hash", sa.CHAR(64), nullable=False),
    sa.Column(
        "previous_dataset_version",
        sa.Text,
        sa.ForeignKey(
            "operations.dataset_version.dataset_version",
            ondelete="RESTRICT",
        ),
    ),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("validated_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("activated_at", sa.TIMESTAMP(timezone=True)),
    sa.CheckConstraint(
        "cutoff_date = DATE '2026-07-11'",
        name="cutoff_date",
    ),
    sa.CheckConstraint(
        "status IN ('building','validated','active','retired','failed')",
        name="status",
    ),
    sa.CheckConstraint(
        f"manifest_hash ~ '{SHA256_PATTERN}'",
        name="manifest_hash",
    ),
    sa.UniqueConstraint(
        "dataset_version",
        "manifest_hash",
        name="uq_dataset_version_manifest_hash",
    ),
    sa.UniqueConstraint(
        "dataset_version",
        "cutoff_date",
        name="uq_dataset_version_cutoff_date",
    ),
    schema="operations",
)
sa.Index(
    "uq_dataset_version_one_active",
    dataset_version.c.status,
    unique=True,
    postgresql_where=dataset_version.c.status == "active",
)


dataset_validation_run = sa.Table(
    "dataset_validation_run",
    metadata,
    sa.Column("validation_run_id", sa.Text, primary_key=True),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("dataset_manifest_hash", sa.CHAR(64), nullable=False),
    sa.Column("validator_id", sa.Text, nullable=False),
    sa.Column("validator_version", sa.Text, nullable=False),
    sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("report_hash", sa.CHAR(64), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version", "dataset_manifest_hash"],
        [
            "operations.dataset_version.dataset_version",
            "operations.dataset_version.manifest_hash",
        ],
        name="fk_validation_run_dataset_manifest",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "status IN ('pass','fail')",
        name="status",
    ),
    sa.CheckConstraint(
        "finished_at >= started_at",
        name="time_order",
    ),
    sa.CheckConstraint(
        f"dataset_manifest_hash ~ '{SHA256_PATTERN}'",
        name="dataset_manifest_hash",
    ),
    sa.CheckConstraint(
        f"report_hash ~ '{SHA256_PATTERN}'",
        name="report_hash",
    ),
    sa.UniqueConstraint(
        "validation_run_id",
        "dataset_version",
        "status",
        name="uq_validation_run_dataset_status",
    ),
    schema="operations",
)


dataset_readiness = sa.Table(
    "dataset_readiness",
    metadata,
    sa.Column("dataset_version", sa.Text, primary_key=True),
    sa.Column("component", sa.Text, primary_key=True),
    sa.Column("validation_run_id", sa.Text, nullable=False),
    sa.Column(
        "validation_status",
        sa.Text,
        nullable=False,
        server_default=sa.text("'pass'"),
    ),
    sa.Column("dataset_manifest_hash", sa.CHAR(64), nullable=False),
    sa.Column("component_manifest_hash", sa.CHAR(64), nullable=False),
    sa.Column("validated_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("validator_version", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version", "dataset_manifest_hash"],
        [
            "operations.dataset_version.dataset_version",
            "operations.dataset_version.manifest_hash",
        ],
        name="fk_readiness_dataset_manifest",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["validation_run_id", "dataset_version", "validation_status"],
        [
            "operations.dataset_validation_run.validation_run_id",
            "operations.dataset_validation_run.dataset_version",
            "operations.dataset_validation_run.status",
        ],
        name="fk_readiness_successful_validation",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "component IN ('postgres','graph','vector','evidence')",
        name="component",
    ),
    sa.CheckConstraint(
        "validation_status = 'pass'",
        name="validation_status",
    ),
    sa.CheckConstraint(
        f"dataset_manifest_hash ~ '{SHA256_PATTERN}'",
        name="dataset_manifest_hash",
    ),
    sa.CheckConstraint(
        f"component_manifest_hash ~ '{SHA256_PATTERN}'",
        name="component_manifest_hash",
    ),
    schema="operations",
)


active_dataset = sa.Table(
    "active_dataset",
    metadata,
    sa.Column(
        "singleton",
        sa.Boolean,
        primary_key=True,
        server_default=sa.true(),
    ),
    sa.Column(
        "dataset_version",
        sa.Text,
        sa.ForeignKey(
            "operations.dataset_version.dataset_version",
            ondelete="RESTRICT",
        ),
    ),
    sa.Column("activated_at", sa.TIMESTAMP(timezone=True)),
    sa.CheckConstraint("singleton", name="singleton"),
    schema="operations",
)


request_run = sa.Table(
    "request_run",
    metadata,
    sa.Column("run_id", sa.Text, primary_key=True),
    sa.Column("request_key", sa.CHAR(64), nullable=False),
    sa.Column("question_id", sa.Text, nullable=False),
    sa.Column("question", sa.Text, nullable=False),
    sa.Column("schema_version", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("cutoff_date", sa.Date, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("deadline_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("execution_outcome", sa.Text),
    sa.Column("verification_status", sa.Text),
    sa.Column("answer_disposition", sa.Text),
    sa.Column("http_status", sa.SmallInteger),
    sa.Column("terminal_failure_code", sa.Text),
    sa.ForeignKeyConstraint(
        ["dataset_version", "cutoff_date"],
        [
            "operations.dataset_version.dataset_version",
            "operations.dataset_version.cutoff_date",
        ],
        name="fk_request_run_dataset_cutoff",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        f"request_key ~ '{SHA256_PATTERN}'",
        name="request_key",
    ),
    sa.CheckConstraint(
        "created_at < deadline_at "
        "AND deadline_at <= created_at + interval '55 seconds'",
        name="deadline",
    ),
    sa.CheckConstraint(
        "finished_at IS NULL OR finished_at >= created_at",
        name="finished_at",
    ),
    sa.CheckConstraint(
        "execution_outcome IS NULL OR execution_outcome IN "
        "('completed','completed_with_failures','failed')",
        name="execution_outcome",
    ),
    sa.CheckConstraint(
        "verification_status IS NULL OR verification_status IN ('pass','fail')",
        name="verification_status",
    ),
    sa.CheckConstraint(
        "answer_disposition IS NULL OR answer_disposition IN "
        "('answer','partial','limitation','abstain')",
        name="answer_disposition",
    ),
    sa.CheckConstraint(
        "execution_outcome IS DISTINCT FROM 'failed' "
        "OR answer_disposition IS NULL",
        name="failed_without_disposition",
    ),
    sa.CheckConstraint(
        "http_status IS NULL OR http_status BETWEEN 100 AND 599",
        name="http_status",
    ),
    schema="operations",
)


request_subtask = sa.Table(
    "request_subtask",
    metadata,
    sa.Column("run_id", sa.Text, primary_key=True),
    sa.Column("subtask_id", sa.Text, primary_key=True),
    sa.Column("importance", sa.Text, nullable=False),
    sa.Column(
        "created_at",
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    sa.ForeignKeyConstraint(
        ["run_id"],
        ["operations.request_run.run_id"],
        name="fk_request_subtask_run",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "importance IN ('critical','required_independent','optional')",
        name="importance",
    ),
    schema="operations",
)


failure_event = sa.Table(
    "failure_event",
    metadata,
    sa.Column("event_id", sa.Text, primary_key=True),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("task_id", sa.Text),
    sa.Column("stage", sa.Text, nullable=False),
    sa.Column("code", sa.Text, nullable=False),
    sa.Column("category", sa.Text, nullable=False),
    sa.Column("retryable", sa.Boolean, nullable=False),
    sa.Column("attempt", sa.Integer, nullable=False),
    sa.Column("remaining_budget_ms", sa.Integer, nullable=False),
    sa.Column("duration_ms", sa.Integer, nullable=False),
    sa.Column("dependency", sa.Text),
    sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["run_id"],
        ["operations.request_run.run_id"],
        name="fk_failure_event_run",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "category IN "
        "('transient','deadline','internal_invariant',"
        "'planner_contract','answer_contract')",
        name="category",
    ),
    sa.CheckConstraint("attempt > 0", name="attempt"),
    sa.CheckConstraint(
        "remaining_budget_ms >= 0",
        name="remaining_budget_ms",
    ),
    sa.CheckConstraint("duration_ms >= 0", name="duration_ms"),
    schema="operations",
)
