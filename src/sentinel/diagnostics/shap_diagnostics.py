import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import psycopg2
from psycopg2.extensions import connection as PostgreSQLConnection


DEFAULT_DRIFT_SAMPLE_SIZE = 5
DEFAULT_BACKGROUND_SAMPLE_SIZE = 20
DEFAULT_LOOKBACK_MINUTES = 5


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
class SamplingConfig:
    """Configuration for drift and background sampling."""

    alert_class: int
    drift_sample_size: int
    background_sample_size: int
    lookback_minutes: int

    def validate(self) -> None:
        """Validate sampling configuration."""

        if self.alert_class < 0:
            raise ValueError(
                "alert_class must be non-negative."
            )

        if self.drift_sample_size <= 0:
            raise ValueError(
                "drift_sample_size must be greater than zero."
            )

        if self.background_sample_size <= 0:
            raise ValueError(
                "background_sample_size must be greater than zero."
            )

        if self.lookback_minutes <= 0:
            raise ValueError(
                "lookback_minutes must be greater than zero."
            )


@dataclass(frozen=True)
class FeatureSample:
    """Represent a matrix of sampled feature vectors."""

    image_ids: tuple[str, ...]
    timestamps: tuple[datetime, ...]
    matrix: np.ndarray


@dataclass(frozen=True)
class DriftSamplingResult:
    """Contain drift and background samples."""

    alert_class: int
    anchor_time: datetime
    window_start: datetime
    drift: FeatureSample
    background: FeatureSample


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


def find_drift_anchor_time(
    connection: PostgreSQLConnection,
    alert_class: int,
) -> datetime:
    """Return the newest prediction timestamp for the drifted class."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT MAX(created_at)
            FROM inference_log
            WHERE predicted_class = %s
            """,
            (alert_class,),
        )

        row = cursor.fetchone()

    if row is None or row[0] is None:
        raise RuntimeError(
            "No inference history was found for "
            f"predicted class {alert_class}."
        )

    anchor_time = row[0]

    if not isinstance(anchor_time, datetime):
        raise RuntimeError(
            "PostgreSQL returned an invalid inference timestamp."
        )

    return anchor_time


def load_drift_rows(
    connection: PostgreSQLConnection,
    alert_class: int,
    window_start: datetime,
    anchor_time: datetime,
    sample_size: int,
) -> list[tuple[str, datetime, Any]]:
    """Load recent distinct images for the drifted class."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH recent_predictions AS (
                SELECT DISTINCT ON (i.image_id)
                    i.image_id,
                    i.created_at
                FROM inference_log AS i
                WHERE i.predicted_class = %s
                  AND i.created_at >= %s
                  AND i.created_at <= %s
                ORDER BY
                    i.image_id,
                    i.created_at DESC
            )
            SELECT
                prediction.image_id,
                prediction.created_at,
                feature.vector
            FROM recent_predictions AS prediction
            JOIN LATERAL (
                SELECT
                    feature_log.vector
                FROM feature_log
                WHERE feature_log.image_id = prediction.image_id
                  AND feature_log.timestamp <= prediction.created_at
                ORDER BY feature_log.timestamp DESC
                LIMIT 1
            ) AS feature
                ON TRUE
            ORDER BY prediction.created_at DESC
            LIMIT %s
            """,
            (
                alert_class,
                window_start,
                anchor_time,
                sample_size,
            ),
        )

        rows = cursor.fetchall()

    return [
        (
            str(row[0]),
            row[1],
            row[2],
        )
        for row in rows
    ]


def load_background_rows(
    connection: PostgreSQLConnection,
    cutoff_time: datetime,
    sample_size: int,
) -> list[tuple[str, datetime, Any]]:
    """Load distinct historical features before the drift window."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH historical_features AS (
                SELECT DISTINCT ON (feature_log.image_id)
                    feature_log.image_id,
                    feature_log.timestamp,
                    feature_log.vector
                FROM feature_log
                WHERE feature_log.timestamp < %s
                ORDER BY
                    feature_log.image_id,
                    feature_log.timestamp DESC
            )
            SELECT
                image_id,
                timestamp,
                vector
            FROM historical_features
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (
                cutoff_time,
                sample_size,
            ),
        )

        rows = cursor.fetchall()

    return [
        (
            str(row[0]),
            row[1],
            row[2],
        )
        for row in rows
    ]


def flatten_feature_vector(
    vector: Any,
) -> np.ndarray:
    """Convert a stored feature value into a flat float32 vector."""

    try:
        feature_array = np.asarray(
            vector,
            dtype=np.float32,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Feature vector could not be converted to float32."
        ) from error

    if feature_array.size == 0:
        raise ValueError(
            "Feature vector cannot be empty."
        )

    if not np.isfinite(feature_array).all():
        raise ValueError(
            "Feature vector contains non-finite values."
        )

    return np.ascontiguousarray(
        feature_array.reshape(-1),
        dtype=np.float32,
    )


def rows_to_feature_sample(
    rows: list[tuple[str, datetime, Any]],
    sample_name: str,
) -> FeatureSample:
    """Convert PostgreSQL rows into a validated feature matrix."""

    if not rows:
        raise RuntimeError(
            f"No rows were found for {sample_name}."
        )

    image_ids: list[str] = []
    timestamps: list[datetime] = []
    vectors: list[np.ndarray] = []

    expected_feature_count: int | None = None

    for image_id, timestamp, vector in rows:
        flattened_vector = flatten_feature_vector(
            vector
        )

        feature_count = int(
            flattened_vector.shape[0]
        )

        if expected_feature_count is None:
            expected_feature_count = feature_count

        elif feature_count != expected_feature_count:
            raise RuntimeError(
                f"{sample_name} contains inconsistent "
                "feature vector sizes."
            )

        image_ids.append(
            image_id
        )
        timestamps.append(
            timestamp
        )
        vectors.append(
            flattened_vector
        )

    matrix = np.stack(
        vectors,
        axis=0,
    ).astype(
        np.float32,
        copy=False,
    )

    return FeatureSample(
        image_ids=tuple(image_ids),
        timestamps=tuple(timestamps),
        matrix=matrix,
    )


def load_drift_sampling_result(
    database_config: DatabaseConfig,
    sampling_config: SamplingConfig,
) -> DriftSamplingResult:
    """Load and validate drift and background feature samples."""

    sampling_config.validate()

    connection = create_postgres_connection(
        database_config
    )

    try:
        anchor_time = find_drift_anchor_time(
            connection=connection,
            alert_class=sampling_config.alert_class,
        )

        window_start = (
            anchor_time
            - timedelta(
                minutes=sampling_config.lookback_minutes
            )
        )

        drift_rows = load_drift_rows(
            connection=connection,
            alert_class=sampling_config.alert_class,
            window_start=window_start,
            anchor_time=anchor_time,
            sample_size=sampling_config.drift_sample_size,
        )

        background_rows = load_background_rows(
            connection=connection,
            cutoff_time=window_start,
            sample_size=sampling_config.background_sample_size,
        )

    finally:
        connection.close()

    drift_sample = rows_to_feature_sample(
        rows=drift_rows,
        sample_name="drift sample",
    )

    background_sample = rows_to_feature_sample(
        rows=background_rows,
        sample_name="background sample",
    )

    drift_feature_count = int(
        drift_sample.matrix.shape[1]
    )
    background_feature_count = int(
        background_sample.matrix.shape[1]
    )

    if drift_feature_count != background_feature_count:
        raise RuntimeError(
            "Drift and background samples contain "
            "different feature vector sizes."
        )

    return DriftSamplingResult(
        alert_class=sampling_config.alert_class,
        anchor_time=anchor_time,
        window_start=window_start,
        drift=drift_sample,
        background=background_sample,
    )


def print_sampling_summary(
    result: DriftSamplingResult,
) -> None:
    """Print a concise summary of the loaded samples."""

    print(
        f"alert_class={result.alert_class}"
    )
    print(
        f"anchor_time={result.anchor_time.isoformat()}"
    )
    print(
        f"window_start={result.window_start.isoformat()}"
    )
    print(
        f"feature_count={result.drift.matrix.shape[1]}"
    )
    print(
        f"drift_sample_size={result.drift.matrix.shape[0]}"
    )
    print(
        "drift_image_ids="
        + ",".join(
            result.drift.image_ids
        )
    )
    print(
        "background_sample_size="
        f"{result.background.matrix.shape[0]}"
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Load drift and background samples "
            "for Sentinel SHAP diagnostics."
        )
    )

    parser.add_argument(
        "--alert-class",
        type=int,
        required=True,
        help="Predicted class reported by the drift alert.",
    )

    parser.add_argument(
        "--drift-sample-size",
        type=int,
        default=DEFAULT_DRIFT_SAMPLE_SIZE,
        help="Maximum number of distinct drift images.",
    )

    parser.add_argument(
        "--background-sample-size",
        type=int,
        default=DEFAULT_BACKGROUND_SAMPLE_SIZE,
        help="Maximum number of historical background images.",
    )

    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=DEFAULT_LOOKBACK_MINUTES,
        help="Drift window measured backward from the latest prediction.",
    )

    return parser.parse_args()


def main() -> None:
    """Run the drift sampling diagnostic."""

    arguments = parse_arguments()

    database_config = (
        DatabaseConfig.from_environment()
    )

    sampling_config = SamplingConfig(
        alert_class=arguments.alert_class,
        drift_sample_size=(
            arguments.drift_sample_size
        ),
        background_sample_size=(
            arguments.background_sample_size
        ),
        lookback_minutes=(
            arguments.lookback_minutes
        ),
    )

    result = load_drift_sampling_result(
        database_config=database_config,
        sampling_config=sampling_config,
    )

    print_sampling_summary(
        result
    )


if __name__ == "__main__":
    main()