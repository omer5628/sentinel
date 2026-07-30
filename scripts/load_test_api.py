import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestResult:
    """Store the result of one HTTP request."""

    status_code: int
    latency_ms: float
    error: str | None = None


def send_prediction_request(
    url: str,
    scheduled_time: float,
    timeout_seconds: float,
) -> RequestResult:
    """Send one prediction request at its scheduled time."""

    sleep_seconds = scheduled_time - time.perf_counter()

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    request = urllib.request.Request(
        url=url,
        method="POST",
    )

    started_at = time.perf_counter()

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            response.read()
            status_code = response.status

        latency_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return RequestResult(
            status_code=status_code,
            latency_ms=latency_ms,
        )

    except urllib.error.HTTPError as error:
        latency_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return RequestResult(
            status_code=error.code,
            latency_ms=latency_ms,
            error=str(error),
        )

    except Exception as error:
        latency_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return RequestResult(
            status_code=0,
            latency_ms=latency_ms,
            error=str(error),
        )


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


def run_load_test(
    base_url: str,
    image_id: str,
    requests_per_second: int,
    duration_seconds: int,
    timeout_seconds: float,
) -> None:
    """Run a fixed-rate HTTP load test."""

    total_requests = (
        requests_per_second * duration_seconds
    )

    request_interval = 1 / requests_per_second
    prediction_url = (
        f"{base_url.rstrip('/')}/predict/{image_id}"
    )

    print("Starting load test")
    print(f"URL: {prediction_url}")
    print(
        f"Target rate: {requests_per_second} requests/second"
    )
    print(f"Duration: {duration_seconds} seconds")
    print(f"Total requests: {total_requests}")

    test_started_at = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(
            requests_per_second * 2,
            100,
        )
    ) as executor:
        futures = []

        for request_index in range(total_requests):
            scheduled_time = (
                test_started_at
                + request_index * request_interval
            )

            futures.append(
                executor.submit(
                    send_prediction_request,
                    prediction_url,
                    scheduled_time,
                    timeout_seconds,
                )
            )

        results = [
            future.result()
            for future in futures
        ]

    elapsed_seconds = (
        time.perf_counter() - test_started_at
    )

    successful_results = [
        result
        for result in results
        if result.status_code == 200
    ]

    failed_results = [
        result
        for result in results
        if result.status_code != 200
    ]

    latencies = [
        result.latency_ms
        for result in successful_results
    ]

    summary = {
        "total_requests": len(results),
        "successful_requests": len(successful_results),
        "failed_requests": len(failed_results),
        "elapsed_seconds": round(
            elapsed_seconds,
            3,
        ),
        "achieved_requests_per_second": round(
            len(results) / elapsed_seconds,
            2,
        ),
        "average_latency_ms": round(
            statistics.mean(latencies)
            if latencies
            else 0.0,
            2,
        ),
        "p50_latency_ms": round(
            percentile(latencies, 0.50),
            2,
        ),
        "p95_latency_ms": round(
            percentile(latencies, 0.95),
            2,
        ),
        "p99_latency_ms": round(
            percentile(latencies, 0.99),
            2,
        ),
    }

    print("\nLoad test results")
    print(
        json.dumps(
            summary,
            indent=2,
        )
    )

    if failed_results:
        print("\nFirst failures")

        for result in failed_results[:5]:
            print(
                {
                    "status_code": result.status_code,
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
            "Run a fixed-rate load test against "
            "the Sentinel prediction API."
        )
    )

    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
    )
    parser.add_argument(
        "--image-id",
        required=True,
    )
    parser.add_argument(
        "--rps",
        type=int,
        default=50,
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
    )

    return parser.parse_args()


def main() -> None:
    """Run the command-line load test."""

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
        base_url=arguments.base_url,
        image_id=arguments.image_id,
        requests_per_second=arguments.rps,
        duration_seconds=arguments.duration,
        timeout_seconds=arguments.timeout,
    )


if __name__ == "__main__":
    main()