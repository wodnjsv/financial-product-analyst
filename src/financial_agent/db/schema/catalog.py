from __future__ import annotations

import sqlalchemy as sa

from financial_agent.db.metadata import metadata


SHA256_PATTERN = "^[0-9a-f]{64}$"


entity = sa.Table(
    "entity",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("entity_type", sa.Text, nullable=False),
    sa.Column("canonical_name", sa.Text, nullable=False),
    sa.Column("normalized_name", sa.Text, nullable=False),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_entity_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint("dataset_version", "entity_id", name="pk_entity"),
    sa.CheckConstraint(
        "entity_type IN "
        "('product','security','company','institution','index','theme')",
        name="entity_type",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="catalog",
)
sa.Index("ix_entity_entity_type", entity.c.entity_type)
sa.Index(
    "ix_entity_normalized_name_trgm",
    entity.c.normalized_name,
    postgresql_using="gin",
    postgresql_ops={"normalized_name": "gin_trgm_ops"},
)


product = sa.Table(
    "product",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("product_family", sa.Text, nullable=False),
    sa.Column("primary_currency", sa.Text),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_product_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_product_entity",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint("dataset_version", "entity_id", name="pk_product"),
    sa.CheckConstraint(
        "product_family IN "
        "('domestic_bond','domestic_etf','overseas_etf','public_fund')",
        name="product_family",
    ),
    schema="catalog",
)
sa.Index("ix_product_product_family", product.c.product_family)


security = sa.Table(
    "security",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("security_kind", sa.Text, nullable=False),
    sa.Column("ticker_display", sa.Text),
    sa.Column("isin_display", sa.Text),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_security_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_security_entity",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint("dataset_version", "entity_id", name="pk_security"),
    sa.CheckConstraint("security_kind <> ''", name="security_kind"),
    schema="catalog",
)


institution = sa.Table(
    "institution",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("institution_kind", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_institution_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_institution_entity",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "entity_id", name="pk_institution"
    ),
    sa.CheckConstraint("institution_kind <> ''", name="institution_kind"),
    schema="catalog",
)


identifier = sa.Table(
    "identifier",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("identifier_id", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("scheme", sa.Text, nullable=False),
    sa.Column("identifier_value", sa.Text, nullable=False),
    sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("valid_from", sa.Date),
    sa.Column("valid_to", sa.Date),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_identifier_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_identifier_entity",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "dataset_version", "identifier_id", name="pk_identifier"
    ),
    sa.CheckConstraint("scheme <> ''", name="scheme"),
    sa.CheckConstraint("identifier_value <> ''", name="identifier_value"),
    sa.CheckConstraint(
        "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
        name="valid_dates",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="catalog",
)
sa.Index(
    "uq_identifier_dataset_scheme_value",
    identifier.c.dataset_version,
    identifier.c.scheme,
    identifier.c.identifier_value,
    unique=True,
)
sa.Index(
    "ix_identifier_dataset_scheme_value",
    identifier.c.dataset_version,
    identifier.c.scheme,
    identifier.c.identifier_value,
)
sa.Index(
    "uq_identifier_primary_per_entity_scheme",
    identifier.c.dataset_version,
    identifier.c.entity_id,
    identifier.c.scheme,
    unique=True,
    postgresql_where=identifier.c.is_primary.is_(True),
)


alias = sa.Table(
    "alias",
    metadata,
    sa.Column("dataset_version", sa.Text, nullable=False),
    sa.Column("alias_id", sa.Text, nullable=False),
    sa.Column("entity_id", sa.Text, nullable=False),
    sa.Column("alias_text", sa.Text, nullable=False),
    sa.Column("normalized_alias_text", sa.Text, nullable=False),
    sa.Column("valid_from", sa.Date),
    sa.Column("valid_to", sa.Date),
    sa.Column("record_hash", sa.CHAR(64), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["dataset_version"],
        ["operations.dataset_version.dataset_version"],
        name="fk_alias_dataset_version",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_version", "entity_id"],
        ["catalog.entity.dataset_version", "catalog.entity.entity_id"],
        name="fk_alias_entity",
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint("dataset_version", "alias_id", name="pk_alias"),
    sa.CheckConstraint("alias_text <> ''", name="alias_text"),
    sa.CheckConstraint(
        "normalized_alias_text <> ''", name="normalized_alias_text"
    ),
    sa.CheckConstraint(
        "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
        name="valid_dates",
    ),
    sa.CheckConstraint(
        f"record_hash ~ '{SHA256_PATTERN}'",
        name="record_hash",
    ),
    schema="catalog",
)
sa.Index("ix_alias_normalized_alias_text", alias.c.normalized_alias_text)
sa.Index(
    "ix_alias_normalized_alias_text_trgm",
    alias.c.normalized_alias_text,
    postgresql_using="gin",
    postgresql_ops={"normalized_alias_text": "gin_trgm_ops"},
)
