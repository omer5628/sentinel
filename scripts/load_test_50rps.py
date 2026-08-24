import concurrent.futures
import os
import statistics
import time

import requests


IMAGE_ID = os.getenv(
    "SENTINEL_IMAGE_ID",
    "load-test-zero",
)

URL = (
    f"http://localhost:8000/predict/{IMAGE_ID}"
)

TARGET_RPS = 50
DURATION_SECONDS = 30


def send_request() -> tuple[int, float]:
    """Send one prediction request and measure latency."""

    start_time = time.perf_counter()

    try:
        response = requests.post(
            URL,
            timeout=5,
        )

        latency_seconds = (
            time.perf_counter()
            - start_time
        )

        return (
            response.status_code,
            latency_seconds,
        )

    except requests.RequestException:
        latency_seconds = (
            time.perf_counter()
            - start_time
        )

        return (
            0,
            latency_seconds,
        )


def percentile(
    values: list[float],
    percentile_value: float,
) -> float:
    """Calculate a percentile from sorted values."""

    if not values:
        return 0.0

    sorted_values = sorted(values)

    index = int(
        round(
            percentile_value
            / 100
            * (len(sorted_values) - 1)
        )
    )

    return sorted_values[index]


def main() -> None:
    """Generate approximately 50 requests per second."""

    total_requests = (
        TARGET_RPS
        * DURATION_SECONDS
    )

    interval = 1 / TARGET_RPS

    start_time = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=100
    ) as executor:
        futures = []

        for request_index in range(
            total_requests
        ):
            target_time = (
                start_time
                + request_index * interval
            )

            sleep_time = (
                target_time
                - time.perf_counter()
            )

            if sleep_time > 0:
                time.sleep(
                    sleep_time
                )

            futures.append(
                executor.submit(
                    send_request
                )
            )

        results = [
            future.result()
            for future in futures
        ]

    elapsed = (
        time.perf_counter()
        - start_time
    )

    statuses = [
        status_code
        for status_code, _ in results
    ]

    latencies_ms = [
        latency_seconds * 1000
        for _, latency_seconds in results
    ]

    successful = sum(
        1
        for status_code in statuses
        if status_code == 200
    )

    failed = (
        len(statuses)
        - successful
    )

    achieved_rps = (
        len(statuses)
        / elapsed
    )

    average_latency = statistics.mean(
        latencies_ms
    )

    p95_latency = percentile(
        latencies_ms,
        95,
    )

    p99_latency = percentile(
        latencies_ms,
        99,
    )

    print(
        f"Image ID: {IMAGE_ID}"
    )
    print(
        f"Total requests: {len(statuses)}"
    )
    print(
        f"Successful requests: {successful}"
    )
    print(
        f"Failed requests: {failed}"
    )
    print(
        f"Elapsed seconds: {elapsed:.2f}"
    )
    print(
        f"Achieved RPS: {achieved_rps:.2f}"
    )
    print(
        f"Average latency: {average_latency:.2f} ms"
    )
    print(
        f"P95 latency: {p95_latency:.2f} ms"
    )
    print(
        f"P99 latency: {p99_latency:.2f} ms"
    )


if __name__ == "__main__":
    main()