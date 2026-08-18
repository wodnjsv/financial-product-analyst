from __future__ import annotations

import os
from dataclasses import dataclass, field


class DatabaseConfigurationError(ValueError):
    """Raised when database configuration violates the storage contract."""


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    url: str = field(repr=False)
    db_read_concurrency_limit: int = 4
    pool_size: int = 5
    max_overflow: int = 0
    pool_timeout_seconds: int = 5
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 5_000
    application_name: str = "financial-product-agent"
    search_path: str = field(
        default='"$user", public, cdb_admin',
        init=False,
    )

    def __post_init__(self) -> None:
        if not self.url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise DatabaseConfigurationError("database URL must use PostgreSQL")

        positive_fields = (
            "db_read_concurrency_limit",
            "pool_size",
            "pool_timeout_seconds",
            "connect_timeout_seconds",
            "statement_timeout_ms",
        )
        for name in positive_fields:
            if getattr(self, name) <= 0:
                raise DatabaseConfigurationError(f"{name} must be positive")
        if self.max_overflow < 0:
            raise DatabaseConfigurationError("max_overflow must be nonnegative")
        if self.pool_size < self.db_read_concurrency_limit + 1:
            raise DatabaseConfigurationError(
                "pool_size must be at least db_read_concurrency_limit + 1"
            )

    @classmethod
    def from_env(
        cls,
        variable: str = "FINANCIAL_AGENT_DATABASE_URL",
    ) -> "DatabaseConfig":
        url = os.environ.get(variable)
        if not url:
            raise DatabaseConfigurationError(f"{variable} is required")
        return cls(url=url)
