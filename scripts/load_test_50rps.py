import concurrent.futures
import time

import requests


URL = "http://localhost:8000/predict/load-test-zero"

TARGET_RPS = 50
DURATION_SECONDS = 30


def send_request() -> int:
    """Send one prediction request."""

    try:
        response = requests.post(
            URL,
            timeout=5,
        )
        return response.status_code
    except requests.RequestException:
        return 0


def main() -> None:
    """Generate approximately 50 requests per second."""

    total_requests = TARGET_RPS * DURATION_SECONDS
    interval = 1 / TARGET_RPS

    start_time = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=100
    ) as executor:
        futures = []

        for request_index in range(total_requests):
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

        statuses = [
            future.result()
            for future in futures
        ]

    elapsed = (
        time.perf_counter()
        - start_time
    )

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


if __name__ == "__main__":
    main()