import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PRODUCER_MODULE = "sentinel.producers.camera_feed"

PID_FILE = Path("/tmp/sentinel-ui-producer.pid")
LOG_FILE = Path("/tmp/sentinel-ui-producer.log")


def _read_pid() -> int | None:
    """Read the managed Producer PID from disk."""

    try:
        return int(PID_FILE.read_text().strip())
    except (
        FileNotFoundError,
        ValueError,
    ):
        return None


def _process_exists(pid: int) -> bool:
    """Return whether a process with the given PID exists."""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    return True


def _is_producer_process(pid: int) -> bool:
    """Verify that the PID belongs to the Sentinel Producer."""

    if not _process_exists(pid):
        return False

    try:
        command_line = (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\x00", b" ")
            .decode(errors="replace")
        )
    except OSError:
        return False

    return PRODUCER_MODULE in command_line


def get_producer_pid() -> int | None:
    """Return the active managed Producer PID."""

    pid = _read_pid()

    if pid is None:
        return None

    if _is_producer_process(pid):
        return pid

    PID_FILE.unlink(missing_ok=True)

    return None


def is_producer_running() -> bool:
    """Return whether the managed Producer is running."""

    return get_producer_pid() is not None


def start_producer() -> int:
    """Start the managed Sentinel Producer."""

    existing_pid = get_producer_pid()

    if existing_pid is not None:
        return existing_pid

    environment = os.environ.copy()

    with LOG_FILE.open("ab") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                PRODUCER_MODULE,
            ],
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    PID_FILE.write_text(str(process.pid))

    time.sleep(0.25)

    if process.poll() is not None:
        PID_FILE.unlink(missing_ok=True)

        raise RuntimeError(
            "Producer failed to start. "
            f"See {LOG_FILE} for details."
        )

    return process.pid


def stop_producer(
    timeout_seconds: float = 5.0,
) -> bool:
    """Stop the managed Sentinel Producer."""

    pid = get_producer_pid()

    if pid is None:
        return False

    os.kill(pid, signal.SIGINT)

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        if not _is_producer_process(pid):
            PID_FILE.unlink(missing_ok=True)
            return True

        time.sleep(0.1)

    if _is_producer_process(pid):
        os.kill(pid, signal.SIGTERM)

    PID_FILE.unlink(missing_ok=True)

    return True