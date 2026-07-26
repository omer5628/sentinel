import argparse
import time

import httpx
import redis

# Script for comparing the speed of 1,000 HTTP requests to FastAPI – Task 2.6

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379
DEFAULT_REQUEST_COUNT = 1000


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Benchmark Sentinel predictions through the HTTP API."
    )

    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="Base URL of the Sentinel FastAPI service.",
    )

    parser.add_argument(
        "--request-count",
        type=int,
        default=DEFAULT_REQUEST_COUNT,
        help="Maximum number of API requests to send.",
    )

    return parser.parse_args()


def fetch_image_ids(request_count: int) -> list[str]:
    """Fetch processed image IDs from Redis."""

    redis_client = redis.Redis(
        host=DEFAULT_REDIS_HOST,
        port=DEFAULT_REDIS_PORT,
        decode_responses=True,
    )

    image_ids: list[str] = []

    try:
        for key in redis_client.scan_iter(match="feat:*"):
            image_ids.append(key.removeprefix("feat:"))

            if len(image_ids) >= request_count:
                break
    finally:
        redis_client.close()

    return image_ids


def benchmark_api(
    api_url: str,
    image_ids: list[str],
) -> None:
    """Send sequential prediction requests and measure total time."""

    successful_requests = 0
    failed_requests = 0

    start_time = time.perf_counter()

    with httpx.Client(
        base_url=api_url,
        timeout=30.0,
    ) as client:
        for image_id in image_ids:
            try:
                response = client.post(f"/predict/{image_id}")

                if response.status_code == 200:
                    successful_requests += 1
                else:
                    failed_requests += 1

            except httpx.HTTPError as error:
                failed_requests += 1
                print(
                    f"Request failed for {image_id}: {error}",
                    flush=True,
                )

    elapsed_seconds = time.perf_counter() - start_time

    throughput = successful_requests / elapsed_seconds if elapsed_seconds > 0 else 0.0

    average_latency_ms = elapsed_seconds / len(image_ids) * 1000 if image_ids else 0.0

    print("")
    print("API benchmark completed.")
    print(f"Requests attempted: {len(image_ids)}")
    print(f"Successful requests: {successful_requests}")
    print(f"Failed requests: {failed_requests}")
    print(f"Elapsed time: {elapsed_seconds:.2f} seconds")
    print(f"Throughput: {throughput:.2f} requests/second")
    print(f"Average latency: {average_latency_ms:.2f} ms/request")


def main() -> None:
    """Run the API benchmark."""

    arguments = parse_arguments()

    if arguments.request_count <= 0:
        raise ValueError("request-count must be greater than zero.")

    image_ids = fetch_image_ids(arguments.request_count)

    if not image_ids:
        raise RuntimeError(
            "No feature keys were found in Redis. Run the producer and worker first."
        )

    print(
        f"Found {len(image_ids)} processed images in Redis.",
        flush=True,
    )

    if len(image_ids) < arguments.request_count:
        print(
            f"Warning: requested {arguments.request_count} images, "
            f"but only {len(image_ids)} are currently available.",
            flush=True,
        )

    benchmark_api(
        api_url=arguments.api_url,
        image_ids=image_ids,
    )


if __name__ == "__main__":
    main()
