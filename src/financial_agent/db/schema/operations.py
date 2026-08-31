from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

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
        "cutoff_date IN (DATE '2026-07-11', DATE '2026-08-24')",
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
    sa.Column("final_verification_artifact_id", postgresql.UUID(as_uuid=True)),
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
    sa.CheckConstraint(
        "(finished_at IS NULL AND execution_outcome IS NULL "
        "AND verification_status IS NULL AND answer_disposition IS NULL "
        "AND http_status IS NULL AND terminal_failure_code IS NULL "
        "AND final_verification_artifact_id IS NULL) OR "
        "(finished_at IS NOT NULL AND execution_outcome IN "
        "('completed','completed_with_failures') "
        "AND verification_status = 'pass' AND answer_disposition IS NOT NULL "
        "AND http_status = 200 AND terminal_failure_code IS NULL "
        "AND final_verification_artifact_id IS NOT NULL) OR "
        "(finished_at IS NOT NULL AND execution_outcome = 'failed' "
        "AND verification_status IS NULL AND answer_disposition IS NULL "
        "AND http_status BETWEEN 500 AND 599 "
        "AND terminal_failure_code IS NOT NULL "
        "AND btrim(terminal_failure_code) <> '' "
        "AND final_verification_artifact_id IS NULL)",
        name="terminal_state",
    ),
    sa.UniqueConstraint(
        "run_id",
        "dataset_version",
        name="uq_request_run_run_dataset",
    ),
    sa.UniqueConstraint(
        "run_id",
        "request_key",
        "dataset_version",
        "cutoff_date",
        "schema_version",
        name="uq_request_run_artifact_scope",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "final_verification_artifact_id"],
        [
            "operations.request_artifact.run_id",
            "operations.request_artifact.artifact_record_id",
        ],
        name="fk_request_run_final_verification_artifact",
        ondelete="RESTRICT",
        use_alter=True,
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
    sa.Column("payload_hash", sa.CHAR(64)),
    sa.Column("payload_size_bytes", sa.BigInteger),
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
    sa.CheckConstraint(
        f"payload_hash IS NULL OR payload_hash ~ '{SHA256_PATTERN}'",
        name="payload_hash",
    ),
    sa.CheckConstraint(
        "payload_size_bytes IS NULL OR payload_size_bytes >= 0",
        name="payload_size_bytes",
    ),
    schema="operations",
)


ARTIFACT_TYPES = (
    "request_context",
    "intent_resolution",
    "query_plan",
    "execution_graph",
    "tool_result",
    "evidence_bundle",
    "verification_report",
    "answer_plan",
    "released_answer",
)


request_artifact = sa.Table(
    "request_artifact",
    metadata,
    sa.Column(
        "artifact_record_id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    ),
    sa.Column("contract_object_id", sa.Text),
    sa.Column("artifact_type", sa.Text, nullable=False),
    sa.Column("schema_version", sa.Text, nullable=False),
    sa.Column("request_key", sa.CHAR(64), nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("cutoff_date", sa.Date, nullable=False),
    sa.Column("producer", sa.Text, nullable=False),
    sa.Column("model_id", sa.Text),
    sa.Column("prompt_version", sa.Text),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("canonical_payload", sa.Text, nullable=False),
    sa.Column("payload_jsonb", postgresql.JSONB, nullable=False),
    sa.Column("payload_hash", sa.CHAR(64), nullable=False),
    sa.ForeignKeyConstraint(
        [
            "run_id",
            "request_key",
            "dataset_version",
            "cutoff_date",
            "schema_version",
        ],
        [
            "operations.request_run.run_id",
            "operations.request_run.request_key",
            "operations.request_run.dataset_version",
            "operations.request_run.cutoff_date",
            "operations.request_run.schema_version",
        ],
        name="fk_request_artifact_run_scope",
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "run_id",
        "artifact_record_id",
        name="uq_request_artifact_run_record",
    ),
    sa.UniqueConstraint(
        "artifact_record_id",
        "run_id",
        "dataset_version",
        name="uq_request_artifact_record_scope",
    ),
    sa.UniqueConstraint(
        "run_id",
        "artifact_type",
        "payload_hash",
        name="uq_request_artifact_retry",
    ),
    sa.CheckConstraint(
        "artifact_type IN ("
        + ",".join(f"'{artifact_type}'" for artifact_type in ARTIFACT_TYPES)
        + ")",
        name="artifact_type",
    ),
    sa.CheckConstraint(
        f"request_key ~ '{SHA256_PATTERN}'",
        name="request_key",
    ),
    sa.CheckConstraint(
        f"payload_hash ~ '{SHA256_PATTERN}'",
        name="payload_hash",
    ),
    sa.CheckConstraint(
        "octet_length(canonical_payload) > 0",
        name="canonical_payload",
    ),
    sa.CheckConstraint(
        "(model_id IS NULL) = (prompt_version IS NULL) AND "
        "(artifact_type = 'intent_resolution' AND model_id IS NOT NULL OR "
        "artifact_type = 'answer_plan' OR "
        "artifact_type NOT IN ('intent_resolution','answer_plan') "
        "AND model_id IS NULL)",
        name="model_metadata",
    ),
    schema="operations",
)
sa.Index(
    "uq_request_artifact_contract_object",
    request_artifact.c.run_id,
    request_artifact.c.artifact_type,
    request_artifact.c.contract_object_id,
    unique=True,
    postgresql_where=request_artifact.c.contract_object_id.is_not(None),
)
sa.Index(
    "ix_request_artifact_request_created",
    request_artifact.c.request_key,
    request_artifact.c.run_id,
    request_artifact.c.artifact_type,
    request_artifact.c.created_at,
)
sa.Index(
    "ix_request_artifact_dataset_cutoff",
    request_artifact.c.dataset_version,
    request_artifact.c.cutoff_date,
)
sa.Index(
    "ix_request_artifact_producer_schema",
    request_artifact.c.producer,
    request_artifact.c.schema_version,
)


artifact_evidence_ref = sa.Table(
    "artifact_evidence_ref",
    metadata,
    sa.Column("artifact_record_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("evidence_id", sa.Text, nullable=False),
    sa.Column("reference_role", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["artifact_record_id", "run_id", "dataset_version"],
        [
            "operations.request_artifact.artifact_record_id",
            "operations.request_artifact.run_id",
            "operations.request_artifact.dataset_version",
        ],
        name="fk_artifact_evidence_ref_artifact",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "evidence_id"],
        ["evidence.evidence_record.dataset_version", "evidence.evidence_record.evidence_id"],
        name="fk_artifact_evidence_ref_evidence",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "artifact_record_id",
        "reference_role",
        "ordinal",
        name="pk_artifact_evidence_ref",
    ),
    sa.CheckConstraint("btrim(reference_role) <> ''", name="reference_role"),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    schema="operations",
)
sa.Index(
    "ix_artifact_evidence_ref_target",
    artifact_evidence_ref.c.dataset_version,
    artifact_evidence_ref.c.evidence_id,
)


artifact_calculation_ref = sa.Table(
    "artifact_calculation_ref",
    metadata,
    sa.Column("artifact_record_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("calculation_id", sa.Text, nullable=False),
    sa.Column("reference_role", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["artifact_record_id", "run_id", "dataset_version"],
        [
            "operations.request_artifact.artifact_record_id",
            "operations.request_artifact.run_id",
            "operations.request_artifact.dataset_version",
        ],
        name="fk_artifact_calculation_ref_artifact",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "calculation_id"],
        [
            "evidence.calculation_record.run_id",
            "evidence.calculation_record.dataset_version",
            "evidence.calculation_record.calculation_id",
        ],
        name="fk_artifact_calculation_ref_calculation",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "artifact_record_id",
        "reference_role",
        "ordinal",
        name="pk_artifact_calculation_ref",
    ),
    sa.CheckConstraint("btrim(reference_role) <> ''", name="reference_role"),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    schema="operations",
)
sa.Index(
    "ix_artifact_calculation_ref_target",
    artifact_calculation_ref.c.run_id,
    artifact_calculation_ref.c.calculation_id,
)


artifact_claim_ref = sa.Table(
    "artifact_claim_ref",
    metadata,
    sa.Column("artifact_record_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("claim_id", sa.Text, nullable=False),
    sa.Column("reference_role", sa.Text, nullable=False),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.ForeignKeyConstraint(
        ["artifact_record_id", "run_id", "dataset_version"],
        [
            "operations.request_artifact.artifact_record_id",
            "operations.request_artifact.run_id",
            "operations.request_artifact.dataset_version",
        ],
        name="fk_artifact_claim_ref_artifact",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "dataset_version", "claim_id"],
        [
            "evidence.atomic_claim.run_id",
            "evidence.atomic_claim.dataset_version",
            "evidence.atomic_claim.claim_id",
        ],
        name="fk_artifact_claim_ref_claim",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "artifact_record_id",
        "reference_role",
        "ordinal",
        name="pk_artifact_claim_ref",
    ),
    sa.CheckConstraint("btrim(reference_role) <> ''", name="reference_role"),
    sa.CheckConstraint("ordinal >= 0", name="ordinal"),
    schema="operations",
)
sa.Index(
    "ix_artifact_claim_ref_target",
    artifact_claim_ref.c.run_id,
    artifact_claim_ref.c.claim_id,
)
