import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sentinel.retraining.fetch_data import (
    DatabaseConfig,
    create_postgres_connection,
)


class WritableDatabaseConnection(Protocol):
    """Database connection interface used by checkpoint updates."""

    def cursor(self) -> Any:
        """Return a database cursor."""
        ...

    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    def rollback(self) -> None:
        """Roll back the current transaction."""
        ...


@dataclass(frozen=True)
class RetrainingCheckpointConfig:
    """Configuration for a successful retraining checkpoint."""

    pipeline_name: str
    cutoff: datetime

    @classmethod
    def from_environment(
        cls,
    ) -> "RetrainingCheckpointConfig":
        """Load checkpoint configuration from environment variables."""

        cutoff_text = _required_environment_variable(
            "RETRAINING_CUTOFF"
        )

        cutoff = datetime.fromisoformat(
            cutoff_text.replace(
                "Z",
                "+00:00",
            )
        )

        config = cls(
            pipeline_name=_required_environment_variable(
                "RETRAINING_PIPELINE_NAME"
            ),
            cutoff=cutoff,
        )

        config.validate()

        return config

    def validate(self) -> None:
        """Validate checkpoint configuration."""

        if not self.pipeline_name.strip():
            raise ValueError(
                "pipeline_name must not be empty."
            )

        if self.cutoff.tzinfo is None:
            raise ValueError(
                "cutoff must include timezone information."
            )


@dataclass(frozen=True)
class RetrainingCheckpointResult:
    """Result of storing a successful retraining checkpoint."""

    previous_cutoff: datetime | None
    current_cutoff: datetime

    @property
    def advanced(self) -> bool:
        """Return whether the checkpoint moved forward."""

        return (
            self.previous_cutoff is None
            or self.current_cutoff
            > self.previous_cutoff
        )


def _required_environment_variable(
    name: str,
) -> str:
    """Read one required environment variable."""

    value = os.getenv(
        name
    )

    if value is None or not value.strip():
        raise RuntimeError(
            f"Required environment variable '{name}' is missing."
        )

    return value.strip()


def _fetch_existing_cutoff(
    cursor: Any,
    pipeline_name: str,
) -> datetime | None:
    """Read the currently stored successful retraining cutoff."""

    cursor.execute(
        """
        SELECT last_successful_cutoff
        FROM retraining_state
        WHERE pipeline_name = %s
        """,
        (
            pipeline_name,
        ),
    )

    row = cursor.fetchone()

    if row is None:
        return None

    cutoff = row[0]

    if not isinstance(
        cutoff,
        datetime,
    ):
        raise RuntimeError(
            "PostgreSQL returned an invalid retraining checkpoint."
        )

    return cutoff


def update_retraining_checkpoint(
    connection: WritableDatabaseConnection,
    config: RetrainingCheckpointConfig,
) -> RetrainingCheckpointResult:
    """Store the cutoff of a successfully completed retraining run."""

    config.validate()

    try:
        with connection.cursor() as cursor:
            previous_cutoff = (
                _fetch_existing_cutoff(
                    cursor,
                    config.pipeline_name,
                )
            )

            if (
                previous_cutoff is not None
                and config.cutoff < previous_cutoff
            ):
                raise ValueError(
                    "Refusing to move the retraining checkpoint backwards."
                )

            cursor.execute(
                """
                INSERT INTO retraining_state (
                    pipeline_name,
                    last_successful_cutoff,
                    updated_at
                )
                VALUES (
                    %s,
                    %s,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (pipeline_name)
                DO UPDATE
                SET
                    last_successful_cutoff =
                        EXCLUDED.last_successful_cutoff,
                    updated_at =
                        CASE
                            WHEN retraining_state.last_successful_cutoff
                                 < EXCLUDED.last_successful_cutoff
                            THEN CURRENT_TIMESTAMP
                            ELSE retraining_state.updated_at
                        END
                WHERE retraining_state.last_successful_cutoff
                      <= EXCLUDED.last_successful_cutoff
                RETURNING last_successful_cutoff
                """,
                (
                    config.pipeline_name,
                    config.cutoff,
                ),
            )

            row = cursor.fetchone()

            if (
                row is None
                or not isinstance(
                    row[0],
                    datetime,
                )
            ):
                raise RuntimeError(
                    "Checkpoint update was rejected by PostgreSQL."
                )

            current_cutoff = row[0]

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    return RetrainingCheckpointResult(
        previous_cutoff=previous_cutoff,
        current_cutoff=current_cutoff,
    )


def _print_result(
    result: RetrainingCheckpointResult,
) -> None:
    """Print machine-readable checkpoint output."""

    previous_cutoff = ""

    if result.previous_cutoff is not None:
        previous_cutoff = (
            result.previous_cutoff.isoformat()
        )

    status = (
        "advanced"
        if result.advanced
        else "unchanged"
    )

    print(
        f"checkpoint_status={status}"
    )
    print(
        "previous_successful_cutoff="
        f"{previous_cutoff}"
    )
    print(
        "last_successful_cutoff="
        f"{result.current_cutoff.isoformat()}"
    )


def main() -> int:
    """Store a successful retraining checkpoint."""

    database_config = (
        DatabaseConfig.from_environment()
    )

    checkpoint_config = (
        RetrainingCheckpointConfig.from_environment()
    )

    connection = create_postgres_connection(
        database_config
    )

    try:
        result = update_retraining_checkpoint(
            connection,
            checkpoint_config,
        )
    finally:
        connection.close()

    _print_result(
        result
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )