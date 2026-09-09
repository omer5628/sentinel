import json
import os
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


SERVICE_ACCOUNT_DIRECTORY = Path(
    "/var/run/secrets/kubernetes.io/serviceaccount"
)
TOKEN_PATH = SERVICE_ACCOUNT_DIRECTORY / "token"
CA_CERTIFICATE_PATH = SERVICE_ACCOUNT_DIRECTORY / "ca.crt"

CONFIGMAP_NAME = "sentinel-ops-flags"
DEFAULT_NAMESPACE = "sentinel-dev"


def read_service_account_token() -> str:
    """Read the Kubernetes service account token."""

    if not TOKEN_PATH.exists():
        raise RuntimeError(
            "Kubernetes service account token was not found."
        )

    return TOKEN_PATH.read_text(
        encoding="utf-8"
    ).strip()


def build_configmap_url(
    namespace: str,
) -> str:
    """Build the Kubernetes API URL for the operations ConfigMap."""

    host = os.getenv("KUBERNETES_SERVICE_HOST")
    port = os.getenv(
        "KUBERNETES_SERVICE_PORT_HTTPS",
        "443",
    )

    if not host:
        raise RuntimeError(
            "KUBERNETES_SERVICE_HOST is not available."
        )

    encoded_namespace = quote(
        namespace,
        safe="",
    )
    encoded_configmap = quote(
        CONFIGMAP_NAME,
        safe="",
    )

    return (
        f"https://{host}:{port}"
        f"/api/v1/namespaces/{encoded_namespace}"
        f"/configmaps/{encoded_configmap}"
    )


def fetch_configmap(
    namespace: str,
) -> dict[str, object]:
    """Fetch the operations ConfigMap from the Kubernetes API."""

    token = read_service_account_token()
    url = build_configmap_url(namespace)

    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )

    ssl_context = ssl.create_default_context(
        cafile=str(CA_CERTIFICATE_PATH)
    )

    try:
        with urlopen(
            request,
            context=ssl_context,
            timeout=10,
        ) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise RuntimeError(
            "Kubernetes API returned "
            f"HTTP {error.code} while reading "
            f"{CONFIGMAP_NAME}."
        ) from error
    except URLError as error:
        raise RuntimeError(
            "Failed to connect to the Kubernetes API."
        ) from error

    payload = json.loads(body)

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Unexpected Kubernetes API response."
        )

    return payload


def read_ops_flag(
    flag_name: str,
    namespace: str,
) -> str:
    """Read one operation flag from the Sentinel ConfigMap."""

    configmap = fetch_configmap(namespace)

    data = configmap.get("data")

    if not isinstance(data, dict):
        raise RuntimeError(
            f"{CONFIGMAP_NAME} does not contain a data section."
        )

    value = data.get(flag_name)

    if not isinstance(value, str):
        raise RuntimeError(
            f"Flag {flag_name} was not found in {CONFIGMAP_NAME}."
        )

    return value.strip().lower()


def main() -> int:
    """Read and print one Sentinel operations flag."""

    if len(sys.argv) not in {2, 3}:
        print(
            "Usage: python scripts/read_ops_flag.py "
            "<FLAG_NAME> [NAMESPACE]",
            file=sys.stderr,
        )
        return 2

    flag_name = sys.argv[1]
    namespace = (
        sys.argv[2]
        if len(sys.argv) == 3
        else DEFAULT_NAMESPACE
    )

    try:
        value = read_ops_flag(
            flag_name=flag_name,
            namespace=namespace,
        )
    except (
        RuntimeError,
        json.JSONDecodeError,
        OSError,
    ) as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 1

    print(value)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())