import argparse
import concurrent.futures
import statistics
import time
from dataclasses import dataclass

import numpy as np

from sentinel.serving.inference_client import TritonInferenceClient


@dataclass(frozen=True)
class RequestResult:
    """Store the result of one Triton inference request."""

    success: bool
    latency_ms: float
    error: str | None = None


def percentile(
    values: list[float],
    percentile_value: float,
) -> float:
    """Calculate a percentile using linear interpolation."""

    if not values:
        return 0.0

    sorted_values = sorted(values)

    index = (
        len(sorted_values) - 1
    ) * percentile_value

    lower_index = int(index)
    upper_index = min(
        lower_index + 1,
        len(sorted_values) - 1,
    )

    fraction = index - lower_index

    return (
        sorted_values[lower_index]
        + (
            sorted_values[upper_index]
            - sorted_values[lower_index]
        )
        * fraction
    )


def send_request(
    client: TritonInferenceClient,
    feature_array: np.ndarray,
    scheduled_time: float,
) -> RequestResult:
    """Send one Triton inference request at its scheduled time."""

    sleep_seconds = (
        scheduled_time - time.perf_counter()
    )

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    started_at = time.perf_counter()

    try:
        client.predict(
            feature_array
        )

        latency_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return RequestResult(
            success=True,
            latency_ms=latency_ms,
        )

    except Exception as error:
        latency_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return RequestResult(
            success=False,
            latency_ms=latency_ms,
            error=str(error),
        )


def run_load_test(
    url: str,
    requests_per_second: int,
    duration_seconds: int,
) -> None:
    """Run a fixed-rate gRPC load test against Triton."""

    total_requests = (
        requests_per_second
        * duration_seconds
    )

    request_interval = (
        1 / requests_per_second
    )

    feature_array = np.zeros(
        shape=(1, 1, 28, 28),
        dtype=np.float32,
    )

    client = TritonInferenceClient(
        url=url,
        model_name="sentinel-mnist_1",
        model_version="1",
    )

    if not client.is_ready():
        client.close()

        raise RuntimeError(
            "Triton model is not ready."
        )

    print("Starting Triton gRPC load test")
    print(f"URL: {url}")
    print(
        f"Target rate: "
        f"{requests_per_second} requests/second"
    )
    print(
        f"Duration: "
        f"{duration_seconds} seconds"
    )
    print(
        f"Total requests: "
        f"{total_requests}"
    )

    test_started_at = time.perf_counter()

    try:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(
                requests_per_second * 2,
                100,
            )
        ) as executor:
            futures = []

            for request_index in range(
                total_requests
            ):
                scheduled_time = (
                    test_started_at
                    + request_index
                    * request_interval
                )

                futures.append(
                    executor.submit(
                        send_request,
                        client,
                        feature_array,
                        scheduled_time,
                    )
                )

            results = [
                future.result()
                for future in futures
            ]

    finally:
        client.close()

    elapsed_seconds = (
        time.perf_counter()
        - test_started_at
    )

    successful_results = [
        result
        for result in results
        if result.success
    ]

    failed_results = [
        result
        for result in results
        if not result.success
    ]

    latencies = [
        result.latency_ms
        for result in successful_results
    ]

    achieved_rps = (
        len(results) / elapsed_seconds
        if elapsed_seconds > 0
        else 0.0
    )

    print()
    print("Triton gRPC load test results")
    print("-" * 40)

    print(
        f"Total requests: "
        f"{len(results)}"
    )
    print(
        f"Successful requests: "
        f"{len(successful_results)}"
    )
    print(
        f"Failed requests: "
        f"{len(failed_results)}"
    )
    print(
        f"Elapsed seconds: "
        f"{elapsed_seconds:.3f}"
    )
    print(
        f"Achieved RPS: "
        f"{achieved_rps:.2f}"
    )

    if latencies:
        print(
            f"Average latency: "
            f"{statistics.mean(latencies):.2f} ms"
        )
        print(
            f"P50 latency: "
            f"{percentile(latencies, 0.50):.2f} ms"
        )
        print(
            f"P95 latency: "
            f"{percentile(latencies, 0.95):.2f} ms"
        )
        print(
            f"P99 latency: "
            f"{percentile(latencies, 0.99):.2f} ms"
        )

    if failed_results:
        print()
        print("First failures")

        for result in failed_results[:5]:
            print(
                {
                    "latency_ms": round(
                        result.latency_ms,
                        2,
                    ),
                    "error": result.error,
                }
            )


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description=(
            "Run a fixed-rate gRPC load test "
            "against Triton."
        )
    )

    parser.add_argument(
        "--url",
        default="localhost:8001",
    )
    parser.add_argument(
        "--rps",
        type=int,
        default=500,
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=10,
    )

    return parser.parse_args()


def main() -> None:
    """Run the Triton gRPC load test."""

    arguments = parse_arguments()

    if arguments.rps <= 0:
        raise ValueError(
            "Requests per second must be positive."
        )

    if arguments.duration <= 0:
        raise ValueError(
            "Duration must be positive."
        )

    run_load_test(
        url=arguments.url,
        requests_per_second=arguments.rps,
        duration_seconds=arguments.duration,
    )


if __name__ == "__main__":
    main()