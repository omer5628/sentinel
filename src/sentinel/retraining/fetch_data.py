import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import psycopg2
from psycopg2.extensions import connection as PostgreSQLConnection

class DatabaseConnection(Protocol):
    """Minimal database connection interface used by retraining."""

    def cursor(self) -> Any:
        """Return a database cursor."""
        ...

@dataclass(frozen=True)
class DatabaseConfig:
    """PostgreSQL connection configuration."""

    host: str
    port: int
    database: str
    username: str
    password: str

    @classmethod
    def from_environment(cls) -> "DatabaseConfig":
        """Load PostgreSQL configuration from environment variables."""

        return cls(
            host=_required_environment_variable(
                "POSTGRES_HOST"
            ),
            port=int(
                _required_environment_variable(
                    "POSTGRES_PORT"
                )
            ),
            database=_required_environment_variable(
                "POSTGRES_DB"
            ),
            username=_required_environment_variable(
                "POSTGRES_USER"
            ),
            password=_required_environment_variable(
                "POSTGRES_PASSWORD"
            ),
        )


@dataclass(frozen=True)
class RetrainingGateConfig:
    """Configuration for the labeled-data retraining gate."""

    pipeline_name: str
    minimum_new_rows: int
    discard_label: str

    @classmethod
    def from_environment(cls) -> "RetrainingGateConfig":
        """Load retraining gate configuration from environment variables."""

        config = cls(
            pipeline_name=_required_environment_variable(
                "RETRAINING_PIPELINE_NAME"
            ),
            minimum_new_rows=int(
                _required_environment_variable(
                    "RETRAINING_MIN_NEW_ROWS"
                )
            ),
            discard_label=_required_environment_variable(
                "RETRAINING_DISCARD_LABEL"
            ),
        )

        config.validate()

        return config

    def validate(self) -> None:
        """Validate retraining gate configuration."""

        if not self.pipeline_name.strip():
            raise ValueError(
                "pipeline_name must not be empty."
            )

        if self.minimum_new_rows <= 0:
            raise ValueError(
                "minimum_new_rows must be greater than zero."
            )

        if not self.discard_label.strip():
            raise ValueError(
                "discard_label must not be empty."
            )


@dataclass(frozen=True)
class RetrainingGateResult:
    """Snapshot of labeled data available for retraining."""

    cutoff: datetime
    last_successful_cutoff: datetime | None
    new_rows: int
    eligible_rows: int
    minimum_new_rows: int

    @property
    def should_retrain(self) -> bool:
        """Return whether enough new labeled rows are available."""

        return self.new_rows >= self.minimum_new_rows


def _required_environment_variable(
    name: str,
) -> str:
    """Read one required environment variable."""

    value = os.getenv(name)

    if value is None or not value.strip():
        raise RuntimeError(
            f"Required environment variable '{name}' is missing."
        )

    return value.strip()


def create_postgres_connection(
    config: DatabaseConfig,
) -> PostgreSQLConnection:
    """Create a PostgreSQL connection."""

    return psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.database,
        user=config.username,
        password=config.password,
    )


def _fetch_cutoff(
    cursor: Any,
) -> datetime:
    """Read the fixed retraining cutoff from PostgreSQL."""

    cursor.execute(
        """
        SELECT CURRENT_TIMESTAMP
        """
    )

    row = cursor.fetchone()

    if (
        row is None
        or not isinstance(row[0], datetime)
    ):
        raise RuntimeError(
            "PostgreSQL returned an invalid retraining cutoff."
        )

    return row[0]


def _fetch_last_successful_cutoff(
    cursor: Any,
    pipeline_name: str,
) -> datetime | None:
    """Read the previous successful retraining checkpoint."""

    cursor.execute(
        """
        SELECT last_successful_cutoff
        FROM retraining_state
        WHERE pipeline_name = %s
        """,
        (pipeline_name,),
    )

    row = cursor.fetchone()

    if row is None:
        return None

    value = row[0]

    if not isinstance(value, datetime):
        raise RuntimeError(
            "PostgreSQL returned an invalid retraining checkpoint."
        )

    return value


def _count_eligible_rows(
    cursor: Any,
    *,
    discard_label: str,
    cutoff: datetime,
) -> int:
    """Count all labeled rows eligible for retraining."""

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM feature_log
        WHERE label IS NOT NULL
          AND label <> %s
          AND labeled_at IS NOT NULL
          AND labeled_at <= %s
        """,
        (
            discard_label,
            cutoff,
        ),
    )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "PostgreSQL did not return an eligible-row count."
        )

    return int(row[0])


def _count_new_rows(
    cursor: Any,
    *,
    discard_label: str,
    cutoff: datetime,
    last_successful_cutoff: datetime | None,
) -> int:
    """Count newly labeled rows since the previous successful retraining."""

    if last_successful_cutoff is None:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM feature_log
            WHERE label IS NOT NULL
              AND label <> %s
              AND labeled_at IS NOT NULL
              AND labeled_at <= %s
            """,
            (
                discard_label,
                cutoff,
            ),
        )
    else:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM feature_log
            WHERE label IS NOT NULL
              AND label <> %s
              AND labeled_at IS NOT NULL
              AND labeled_at > %s
              AND labeled_at <= %s
            """,
            (
                discard_label,
                last_successful_cutoff,
                cutoff,
            ),
        )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "PostgreSQL did not return a new-row count."
        )

    return int(row[0])


def evaluate_retraining_gate(
    connection: DatabaseConnection,
    config: RetrainingGateConfig,
) -> RetrainingGateResult:
    """Evaluate whether enough new labeled data exists for retraining."""

    config.validate()

    with connection.cursor() as cursor:
        cutoff = _fetch_cutoff(
            cursor
        )

        last_successful_cutoff = (
            _fetch_last_successful_cutoff(
                cursor,
                config.pipeline_name,
            )
        )

        eligible_rows = _count_eligible_rows(
            cursor,
            discard_label=config.discard_label,
            cutoff=cutoff,
        )

        new_rows = _count_new_rows(
            cursor,
            discard_label=config.discard_label,
            cutoff=cutoff,
            last_successful_cutoff=(
                last_successful_cutoff
            ),
        )

    return RetrainingGateResult(
        cutoff=cutoff,
        last_successful_cutoff=(
            last_successful_cutoff
        ),
        new_rows=new_rows,
        eligible_rows=eligible_rows,
        minimum_new_rows=config.minimum_new_rows,
    )


def _print_result(
    result: RetrainingGateResult,
) -> None:
    """Print machine-readable retraining gate output."""

    previous_cutoff = ""

    if result.last_successful_cutoff is not None:
        previous_cutoff = (
            result.last_successful_cutoff.isoformat()
        )

    gate_status = (
        "passed"
        if result.should_retrain
        else "blocked"
    )

    print(
        f"retraining_cutoff={result.cutoff.isoformat()}"
    )
    print(
        "last_successful_cutoff="
        f"{previous_cutoff}"
    )
    print(
        f"new_rows={result.new_rows}"
    )
    print(
        f"eligible_rows={result.eligible_rows}"
    )
    print(
        "minimum_new_rows="
        f"{result.minimum_new_rows}"
    )
    print(
        f"retraining_gate={gate_status}"
    )


def main() -> int:
    """Run the retraining data gate."""

    database_config = (
        DatabaseConfig.from_environment()
    )

    gate_config = (
        RetrainingGateConfig.from_environment()
    )

    connection = create_postgres_connection(
        database_config
    )

    try:
        result = evaluate_retraining_gate(
            connection,
            gate_config,
        )
    finally:
        connection.close()

    _print_result(
        result
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
