import os
from io import BytesIO
from typing import Any
from uuid import UUID

import psycopg2
import streamlit as st
from PIL import Image
from psycopg2.extras import RealDictCursor


DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DATABASE = "sentinel"
DEFAULT_POSTGRES_USERNAME = "sentinel"
DEFAULT_POSTGRES_PASSWORD = "sentinel"

LABELS = [str(number) for number in range(10)]
DISCARD_LABEL = "Discard"


def create_postgres_connection():
    """Create a connection to the offline feature store."""

    return psycopg2.connect(
        host=os.getenv(
            "POSTGRES_HOST",
            DEFAULT_POSTGRES_HOST,
        ),
        port=int(
            os.getenv(
                "POSTGRES_PORT",
                str(DEFAULT_POSTGRES_PORT),
            )
        ),
        dbname=os.getenv(
            "POSTGRES_DB",
            DEFAULT_POSTGRES_DATABASE,
        ),
        user=os.getenv(
            "POSTGRES_USER",
            DEFAULT_POSTGRES_USERNAME,
        ),
        password=os.getenv(
            "POSTGRES_PASSWORD",
            DEFAULT_POSTGRES_PASSWORD,
        ),
    )


def fetch_unlabeled_event() -> dict[str, Any] | None:
    """Fetch the oldest event that has not been labeled."""

    with create_postgres_connection() as connection:
        with connection.cursor(
            cursor_factory=RealDictCursor,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    event_id,
                    image_id,
                    timestamp,
                    raw_image
                FROM feature_log
                WHERE label IS NULL
                ORDER BY timestamp ASC
                LIMIT 1
                """
            )

            row = cursor.fetchone()

    if row is None:
        return None

    return dict(row)


def fetch_labeling_stats() -> tuple[int, int]:
    """Return the number of labeled and unlabeled events."""

    with create_postgres_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE label IS NOT NULL
                    ) AS labeled_count,
                    COUNT(*) FILTER (
                        WHERE label IS NULL
                    ) AS unlabeled_count
                FROM feature_log
                """
            )

            result = cursor.fetchone()

        if result is None:
            raise RuntimeError("Failed to fetch labeling statistics.")

        labeled_count, unlabeled_count = result

    return int(labeled_count), int(unlabeled_count)


def update_label(
    event_id: UUID | str,
    label: str,
) -> bool:
    """Attach a human label to one feature event."""

    with create_postgres_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE feature_log
                SET label = %s
                WHERE event_id = %s
                  AND label IS NULL
                """,
                (
                    label,
                    str(event_id),
                ),
            )

            updated_rows = cursor.rowcount

        connection.commit()

    return updated_rows == 1


def display_stats(
    labeled_count: int,
    unlabeled_count: int,
) -> None:
    """Display annotation progress."""

    total_count = labeled_count + unlabeled_count

    if total_count == 0:
        progress = 0.0
    else:
        progress = labeled_count / total_count

    st.write(f"**Labeled: {labeled_count} / Unlabeled: {unlabeled_count}**")
    st.progress(progress)


def display_label_buttons(event_id: UUID | str) -> None:
    """Display MNIST label buttons and update the selected event."""

    st.subheader("Choose the correct label")

    columns = st.columns(5)

    for index, label in enumerate(LABELS):
        column = columns[index % len(columns)]

        if column.button(
            label,
            key=f"label-{event_id}-{label}",
            use_container_width=True,
        ):
            if update_label(event_id, label):
                st.success(f"Saved label: {label}")
                st.rerun()

            st.warning("This event was already labeled.")
            st.rerun()

    if st.button(
        DISCARD_LABEL,
        key=f"discard-{event_id}",
        type="secondary",
        use_container_width=True,
    ):
        if update_label(event_id, DISCARD_LABEL):
            st.success("Image discarded.")
            st.rerun()

        st.warning("This event was already labeled.")
        st.rerun()


def main() -> None:
    """Run the Sentinel data-labeling cockpit."""

    st.set_page_config(
        page_title="Sentinel Labeling Cockpit",
        page_icon="🏷️",
        layout="centered",
    )

    st.title("Sentinel Labeling Cockpit")
    st.caption("Human annotation tool for MNIST events")

    try:
        labeled_count, unlabeled_count = fetch_labeling_stats()
        display_stats(
            labeled_count=labeled_count,
            unlabeled_count=unlabeled_count,
        )

        event = fetch_unlabeled_event()

    except psycopg2.Error as error:
        st.error(f"PostgreSQL connection failed: {error}")
        st.stop()

    if event is None:
        st.success("All available images have been labeled.")
        st.stop()

    raw_image = event["raw_image"]

    if raw_image is None:
        st.error("The selected event does not contain a raw image.")
        st.stop()

    try:
        image = Image.open(BytesIO(bytes(raw_image)))
        image.load()
    except Exception as error:
        st.error(f"Could not decode the stored image: {error}")
        st.stop()

    st.image(
        image,
        caption=f"Image ID: {event['image_id']}",
        width=280,
    )

    st.code(str(event["image_id"]), language=None)

    display_label_buttons(event["event_id"])


if __name__ == "__main__":
    main()
